"""A top-level overview of what a public body has been doing, across years.

WHY NOT FROM THE TRANSCRIPTS. Every earlier attempt started from the full
transcripts and came back heavily weighted toward one meeting -- which is a
false picture of a multi-year committee, and the failure is structural rather
than a prompting mistake: 100 meetings of City-Council-length transcript is
millions of characters, so whatever survives truncation IS the answer. The
input here is the per-meeting summaries instead. For the High School Building
Committee that is 84k characters for 58 meetings -- 21k tokens, one request --
and every meeting is represented at comparable length by construction.

That the input is itself machine-written is the cost, and it compounds: this
is a summary of summaries, two inferences away from what was said. Two things
hold it down. The page says so in those words, and every claim must cite a
meeting a reader can open at the moment in question.

CITATIONS ARE TOKENS, NOT TIMESTAMPS. Each source item is labelled `M07#4` in
the prompt and the model may only cite those labels, so verification is exact
set membership and a mangled number cannot become a link to the wrong moment.
summarize_meeting learned the same lesson with raw seconds, where it had to
check every citation against the meeting duration; a token cannot be off by a
digit and still resolve. An unknown token is dropped, and a thread left with
no surviving citation is dropped with it.

EVEN WEIGHTING IS MEASURED, NOT ASSUMED, because "it over-weights one meeting"
is the thing this is meant to fix and a prompt cannot promise it. The output
records how many distinct meetings were cited and the largest share any single
meeting took; --check prints them for a written overview without calling the
API. PRINCIPLES.md #4: state the number.

WHAT IT INHERITS from summarize_meeting, for the same reasons set out there:
no vote tallies, no opinion, no first person, no claim beyond the record.

Usage:
    python summarize_committee.py -c "MPS High School Building Committee"
    python summarize_committee.py -c "..." --dry-run   # assemble, don't ask
    python summarize_committee.py -c "..." --check     # measure what exists
    python summarize_committee.py --list               # what is summarisable
"""

import argparse
import datetime
import glob
import hashlib
import io
import json
import os
import sys
import time

import summarize_meeting as sm
import utils

# One request per committee, so the cap is about what a model can hold rather
# than what an allowance can afford. 400k chars is ~100k tokens: comfortable
# for the Flash models actually reachable on the free tier, and far above the
# 84k the Building Committee needs. City Council (~500 meetings) will exceed
# it and needs a two-stage pass -- digest per period, then digest the digests.
# That path is NOT built: untested machinery that never runs is how this
# codebase accumulates passes nobody has measured. Filed in PENDING.md.
MAX_INPUT_CHARS = 400000

# Enough for an overview, a handful of threads and a period line each. Larger
# than the per-meeting budget because the output is the whole point here.
MAX_OUTPUT = 8000

# A SHARE, NOT A COUNT, and the number this script exists to keep down. 0.25
# is a judgement rather than a measurement: at 58 meetings an even spread is
# 1.7% each, so a quarter of all citations landing on one meeting is the
# failure the earlier attempts showed, not a committee that genuinely spent
# one meeting on the only thing that mattered.
CONCENTRATION_WARN = 0.25

# A roll-up over four meetings tells a reader nothing the four per-meeting
# summaries do not already say, and rule 2 ("spread the weight") has nothing
# to spread. Measured against the active list: 21 of 30 active bodies clear
# this, and the ones below it are bodies the archive has barely caught yet.
MIN_SUMMARIES = 5

# HOW STALE BEFORE IT IS WORTH A REQUEST. sources_sha changes the moment ANY
# of a body's summaries is written or rewritten, so on its own it would make
# the hourly job regenerate an overview for every body that gained a single
# meeting -- up to a dozen requests a day, forever, to move a sentence. That
# is the churn that would eat the allowance the overviews were given priority
# over. Jason, 2026-10-10: "we'll redo the committee level overviews when the
# summaries are more complete".
#
# So an existing overview is left alone until the body has gained this many
# summaries. A body with NO overview is never held back by it.
MIN_NEW_SUMMARIES = 5

# Bodies to write before the rest, in rank order -- same idiom as
# summary_priority.txt and ids_to_transcribe.txt. Everything not listed keeps
# the default order (best-covered first).
PRIORITY_FILE = "overview_priority.txt"

# NOT PUBLIC BODIES, though meeting_types.json gives them no "kind" to say so.
# The system prompt opens "You write the standing overview of a public body",
# which is simply false for these: Election is campaign and forum coverage
# across many bodies, Community Meeting is a venue label, and the WMCC is a
# community organisation whose videos are programming rather than governance.
# An overview of any of them would be a confident answer to a question nobody
# asked.
NOT_A_BODY = {"Election", "Community Meeting", "West Medford Community Center"}

# DID THE LAST CALL SPEND A REQUEST? The --active loop cannot infer it: an
# overview that existed but was REGENERATED (its sources changed) looks
# exactly like a cache hit from the outside, and counting it as free would let
# --limit 2 make an unbounded number of API calls. Same shape and same reason
# as summarize_meeting._CACHED, which was added after a limit was spent on
# meetings nothing was ever asked about.
_CACHED = False

SYSTEM = """You write the standing overview of a public body for a civic \
transcript archive in Medford, Massachusetts. Your input is the archive's own \
per-meeting summaries, in chronological order, covering every meeting of that \
body the archive holds.

You are describing a body's WORK OVER TIME, not recapping meetings. A reader \
arrives knowing nothing and wants: what is this body for, what has it decided, \
what is it working on now, and where do I go to check.

RULES, and the first is the one that matters most:

1. CITE BY LABEL. Two kinds exist and both are in the input: M07 is a whole \
meeting, M07#4 is one item within it. Cite the item when the claim is about \
that item, and the meeting when it is about the meeting as a whole. Use the \
labels verbatim in "cite" lists. Never write a timestamp, a date or a \
URL as a citation. A label you did not see in the input will be discarded, \
and any statement left with no citation is discarded with it.

2. SPREAD THE WEIGHT. You are describing years of work. A thread that cites \
one meeting when the input shows the subject recurring across many is wrong \
even if every word of it is accurate. Prefer the first and most recent \
meeting on a subject plus the ones where something changed.

3. NO VOTE TALLIES. Report an outcome only where the input states it plainly \
("approved", "the motion failed"). Never say who voted which way, and never \
give counts.

4. NO OPINION, NO FIRST PERSON, NO ADVICE. Not "the committee should", not \
"importantly", not "we". Say what the record shows.

5. NOTHING BEYOND THE INPUT. No background knowledge about Medford, the MSBA, \
school construction or anyone named. If the input does not say it, it does \
not appear. Do not estimate, round or total figures that are not given.

6. NAME PEOPLE ONLY AS THE INPUT NAMES THEM, and only for what they did in \
the body's business -- moved, presented, chaired. Never characterise a person.

Return ONLY JSON of this shape:

{
  "overview": "4-6 sentences. What the body is, what it is for, the span it \
has been meeting over, and where its work stands at the most recent meeting.",
  "threads": [
    {"name": "Short noun phrase for a line of work, e.g. Site selection",
     "status": "settled | ongoing | paused | unclear -- from the input only",
     "summary": "3-6 sentences tracing this thread across meetings, in order.",
     "cite": ["M03#2", "M11#1", "M40#5"]}
  ],
  "periods": [
    {"period": "the period label exactly as given in the input",
     "narrative": "1-2 sentences on what this period was about.",
     "cite": ["M07", "M09#2"]}
  ]
}

5 to 9 threads. ONE entry in "periods" for every period label in the input, \
in the same order, none skipped and none invented."""


def slug(committee):
    """The basename make_committee_pages already uses for this body's page."""
    return committee.replace(" ", "_")


def overview_path(committee):
    return os.path.join("committees", slug(committee) + ".overview.json")


def source_summaries(committee, video_data=None):
    """Every summarised meeting of this body, oldest first.

    SKIPPED AND DUPLICATE ENTRIES CANNOT REACH HERE, because a body whose
    meetings are each published twice (YouTube and Castus carry most of them)
    would weight those meetings double -- the exact bias this file exists to
    remove. Measured on the Building Committee: 58 summarised meetings, no
    pair of them duplicates of each other, because the duplicate copy is the
    one that goes unsummarised. That is luck, not a guarantee, so it is
    checked rather than assumed.
    """
    video_data = video_data or utils.get_video_data()
    out = []
    for yt_id, e in video_data.items():
        if e.get("meeting_type") != committee or e.get("skip"):
            continue
        base = (e.get("upload_date") or "") + "_" + yt_id
        path = os.path.join(base, base + ".summary.json")
        if not os.path.exists(path):
            continue
        try:
            d = json.load(io.open(path, encoding="utf-8"))
        except ValueError:
            print("  WARNING: unreadable summary, skipped: %s" % path)
            continue
        out.append({"yt_id": yt_id, "base": base,
                    "date": e.get("date") or e.get("upload_date") or "",
                    "title": e.get("title") or "", "summary": d})
    out.sort(key=lambda m: (m["date"], m["yt_id"]))

    chosen = {m["yt_id"] for m in out}
    for m in out:
        dup = (video_data.get(m["yt_id"]) or {}).get("duplicate_id")
        if dup in chosen:
            print("  WARNING: %s and %s are the same meeting and both carry a "
                  "summary; it will be weighted twice." % (m["yt_id"], dup))

    # THE UNFLAGGED PAIRS ARE THE ONES THAT BITE, and one did. Castus dates a
    # meeting the day the city posted it and YouTube the day it happened, so
    # CAS00002553 (10/05/26) and CP5ho6yZUqo (10.6) are one meeting with no
    # duplicate_id between them. Both got summarised on 2026-10-09 and the
    # overview counted 67 meetings for 66.
    #
    # WARNS, DOES NOT DROP. Dropping needs a test that cannot be wrong, and
    # date-plus-duration is not it: CAS00002546 and CAS00002547 are two
    # DIFFERENT advisory team meetings on the same day. Losing a real meeting
    # to a clever heuristic is worse than counting one twice, so this reports
    # and a person decides (PRINCIPLES #4).
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            da = (video_data.get(a["yt_id"]) or {}).get("duration") or 0
            db = (video_data.get(b["yt_id"]) or {}).get("duration") or 0
            if not da or not db:
                continue
            close_date = abs((_day(a["date"]) or 0) - (_day(b["date"]) or 0)) <= 2
            close_len = abs(da - db) <= 0.02 * max(da, db)
            if close_date and close_len and a["date"] != b["date"]:
                print("  POSSIBLE DUPLICATE: %s (%s, %ds) and %s (%s, %ds) "
                      "-- same length a day apart, and neither is flagged. If "
                      "they are one meeting it is weighted twice."
                      % (a["yt_id"], a["date"], da, b["yt_id"], b["date"], db))
    return out


def _day(date):
    """Date string to an ordinal, or None. Dates here are already validated."""
    try:
        return datetime.date(int(date[:4]), int(date[5:7]),
                             int(date[8:10])).toordinal()
    except (ValueError, TypeError, IndexError):
        return None


# A body's work divides by WHO WAS SITTING, where that is knowable. Medford
# elects its City Council and School Committee in November of odd years and
# the terms begin that January following, so 2024-2025 and 2026-2027 are real
# units: the membership, the chair and the priorities all reset at the
# boundary. Quarters cut across that and tell a reader nothing.
#
# Default by PREFIX because the prefixes already encode it -- "CC " is the
# council side and "MPS " the school side, and a standing committee of either
# is staffed by members serving those same two-year terms. meeting_types.json
# may override per body with "period_style": "quarter" | "term".
PERIOD_STYLES = ("term", "quarter")


def period_style(committee, config=None):
    """"term" or "quarter" for this body. Config wins over the prefix default."""
    cfg = config if config is not None else utils.meeting_type_config()
    want = ((cfg.get(committee) or {}).get("period_style") or "").strip().lower()
    if want in PERIOD_STYLES:
        return want
    return "term" if (committee or "").startswith(("CC ", "MPS ", "MSC ")) \
        else "quarter"


def term_of(year):
    """The two-year term containing `year`, as "2024-2025".

    Terms begin in January of EVEN years here, following a November election
    in the odd year before. So an odd year belongs to the term that started
    the year before it.
    """
    start = year if year % 2 == 0 else year - 1
    return "%d-%d" % (start, start + 1)


def period_of(date, style="quarter"):
    """The period label for a meeting date.

    Quarter is the coarsest label a reader still reads as a date: months make
    30 periods of a 2.5-year project and years make three. Term is coarser
    still and means something the calendar does not -- see PERIOD_STYLES.
    """
    try:
        y, m = int(date[:4]), int(date[5:7])
    except (ValueError, IndexError):
        return "undated"
    if style == "term":
        return "%s term" % term_of(y)
    return "%d Q%d" % (y, (m - 1) // 3 + 1)


def build_prompt(committee, meetings, style=None):
    """The prompt, and the label -> citation index that verifies the answer.

    Periods are headed in the prompt so the model sees the shape of the
    timeline rather than a flat list -- and because "one entry per period" is
    what structurally forces the overview to cover 2024 as well as last month.
    """
    index = {}
    style = style or period_style(committee)
    out = [
        "Body: %s" % committee,
        "Meetings held by the archive: %d, from %s to %s."
        % (len(meetings), meetings[0]["date"], meetings[-1]["date"]),
        "",
        "Below is every meeting, oldest first, grouped by period. Each item "
        "carries the label you must cite it by.",
        "",
    ]
    last_period = None
    for n, m in enumerate(meetings, 1):
        period = period_of(m["date"], style)
        if period != last_period:
            out.append("")
            out.append("=== PERIOD %s ===" % period)
            last_period = period
        tag = "M%02d" % n
        d = m["summary"]
        # THE MEETING ITSELF IS CITABLE, not only its items. The first run
        # cited periods as "M09" -- the whole meeting, which is the natural
        # unit for "what was this quarter about" -- and verification dropped
        # all 24 of them because only item labels were in the index. All ten
        # period narratives shipped with no citation at all. The model was
        # right and the vocabulary was too small.
        index[tag] = {"video_id": m["yt_id"], "t": None, "date": m["date"],
                      "base": m["base"], "meeting_title": m["title"],
                      "title": m["title"]}
        out.append("")
        out.append("%s  %s  %s" % (tag, m["date"], m["title"]))
        subject = (d.get("subject") or "").strip()
        if subject:
            out.append("  subject: %s" % subject)
        overview = (d.get("overview") or "").strip()
        if overview:
            out.append("  overview: %s" % overview)
        for i, it in enumerate(d.get("items") or [], 1):
            t = it.get("t")
            if t is None:
                continue                      # unlinkable, so uncitable
            label = "%s#%d" % (tag, i)
            index[label] = {"video_id": m["yt_id"], "t": int(t),
                            "date": m["date"], "base": m["base"],
                            "meeting_title": m["title"],
                            "title": (it.get("title") or "").strip()}
            body = (it.get("summary") or "").strip()
            out.append("  [%s] %s%s" % (label, index[label]["title"],
                                        " -- " + body if body else ""))
    out.append("")
    out.append("Periods, in order: %s"
               % ", ".join(sorted({period_of(m["date"], style)
                                   for m in meetings})))
    return "\n".join(out), index


def verify(answer, index):
    """Resolve every citation label; drop what does not resolve.

    A LABEL IS EITHER IN THE INDEX OR IT IS NOT -- no tolerance, no nearest
    match. That is the whole reason citations are labels: the per-meeting
    summaries had to check a model's seconds against the meeting duration and
    could still link to the wrong moment inside it, while an unknown label
    links nowhere and is simply discarded.
    """
    dropped = []

    def resolve(entry, where):
        cites, seen = [], set()
        for label in entry.get("cite") or []:
            label = str(label).strip()
            hit = index.get(label)
            if not hit:
                dropped.append((where, label))
                continue
            if label in seen:
                continue
            seen.add(label)
            cites.append(dict(hit, label=label))
        # t is None for a whole-meeting citation, which sorts before any
        # moment inside that meeting rather than raising on None < int.
        cites.sort(key=lambda c: (c["date"], -1 if c["t"] is None else c["t"]))
        return cites

    threads = []
    for th in answer.get("threads") or []:
        cites = resolve(th, "thread %r" % str(th.get("name"))[:40])
        if not cites:
            dropped.append(("thread %r" % str(th.get("name"))[:40],
                            "no citation survived; thread dropped"))
            continue
        threads.append({"name": (th.get("name") or "").strip(),
                        "status": (th.get("status") or "").strip(),
                        "summary": (th.get("summary") or "").strip(),
                        "citations": cites})

    periods = []
    for p in answer.get("periods") or []:
        label = (p.get("period") or "").strip()
        periods.append({"period": label,
                        "narrative": (p.get("narrative") or "").strip(),
                        "citations": resolve(p, "period %r" % label)})
    return threads, periods, dropped


def coverage(threads, periods, meetings, style="quarter"):
    """How evenly the overview draws on the body's meetings.

    THE NUMBER THIS SCRIPT IS JUDGED BY. meetings_cited over of_meetings is
    breadth; max_share is the concentration that made every earlier attempt
    unusable. Both are written into the sidecar so a later run can be compared
    against this one rather than re-argued.
    """
    per_meeting = {}
    for entry in list(threads) + list(periods):
        for c in entry["citations"]:
            per_meeting[c["video_id"]] = per_meeting.get(c["video_id"], 0) + 1
    total = sum(per_meeting.values())
    top = max(per_meeting.items(), key=lambda kv: kv[1]) if per_meeting else None
    return {"citations": total,
            "meetings_cited": len(per_meeting),
            "of_meetings": len(meetings),
            "max_share": round(top[1] / float(total), 3) if total else 0.0,
            "most_cited": top[0] if top else None,
            "periods_covered": len([p for p in periods if p["narrative"]]),
            "of_periods": len({period_of(m["date"], style)
                               for m in meetings})}


def report(cov, dropped):
    print("  %d citations over %d of %d meetings; %d of %d periods covered"
          % (cov["citations"], cov["meetings_cited"], cov["of_meetings"],
             cov["periods_covered"], cov["of_periods"]))
    print("  heaviest single meeting: %.1f%% of citations (%s)"
          % (100 * cov["max_share"], cov["most_cited"]))
    if cov["max_share"] > CONCENTRATION_WARN:
        print("  WARNING: that is above the %.0f%% concentration this is meant "
              "to avoid -- read it before publishing."
              % (100 * CONCENTRATION_WARN))
    if cov["periods_covered"] < cov["of_periods"]:
        print("  WARNING: %d periods have no narrative, so the overview is not "
              "covering the whole span."
              % (cov["of_periods"] - cov["periods_covered"]))
    for where, why in dropped:
        print("  DROPPED %-28s %s" % (where, why))


def sources_sha(meetings):
    """Cache key: the summaries this overview was built from.

    The transcript sha does the same job one level down. A new meeting, or a
    re-run summary of an old one, changes this and the overview is stale; a
    page rebuild or a metadata refresh does not.
    """
    h = hashlib.sha256()
    for m in meetings:
        h.update(m["yt_id"].encode("ascii", "replace"))
        h.update((m["summary"].get("transcript_sha") or "").encode("ascii",
                                                                   "replace"))
        h.update((m["summary"].get("generated_at") or "").encode("ascii",
                                                                 "replace"))
    return h.hexdigest()[:16]


def summarise_committee(committee, model=sm.DEFAULT_PROVIDER, dry_run=False,
                        force=False, check=False, video_data=None,
                        min_new=MIN_NEW_SUMMARIES):
    meetings = source_summaries(committee, video_data)
    if not meetings:
        print("%s: no summarised meetings" % committee)
        return None
    dest = overview_path(committee)
    sha = sources_sha(meetings)
    global _CACHED
    _CACHED = False

    if check:
        if not os.path.exists(dest):
            print("%s: no overview written yet" % committee)
            return None
        d = json.load(io.open(dest, encoding="utf-8"))
        print("%s: %d meetings, written %s by %s%s"
              % (committee, d.get("n_meetings"), d.get("generated_at"),
                 d.get("model"),
                 "" if d.get("sources_sha") == sha else "  -- STALE"))
        report(d.get("coverage") or {}, [])
        return d

    if os.path.exists(dest) and not force:
        try:
            old = json.load(io.open(dest, encoding="utf-8"))
            if old.get("sources_sha") == sha:
                print("%s: current (%d meetings)" % (committee, len(meetings)))
                _CACHED = True
                return old
            # SHA-CHANGED IS NOT THE SAME AS WORTH REDOING. Measured on the
            # 21:05 run of 2026-10-10: the Building Committee regenerated
            # because it had gained ONE summary, 62 -> 63, spending a request
            # to move a sentence. At a dozen new summaries a day across 20
            # bodies that is most of the allowance, forever, and the whole
            # point of putting overviews first was to spend it on bodies that
            # have none yet.
            gained = len(meetings) - (old.get("n_meetings") or 0)
            if gained < min_new:
                print("%s: current enough (%d meetings, %+d since the "
                      "overview; redone at %+d)"
                      % (committee, len(meetings), gained, min_new))
                _CACHED = True
                return old
        except ValueError:
            pass

    style = period_style(committee)
    user, index = build_prompt(committee, meetings, style)
    print("%s: %d meetings, %d citable items, %d %s periods, ~%dk chars"
          % (sm.printable(committee), len(meetings), len(index),
             len({period_of(m["date"], style) for m in meetings}), style,
             len(user) // 1000))
    if len(user) > MAX_INPUT_CHARS:
        print("  TOO BIG for one request (%dk chars, cap %dk). This body needs "
              "the two-stage pass that is not built yet; see PENDING.md."
              % (len(user) // 1000, MAX_INPUT_CHARS // 1000))
        return None
    if dry_run:
        print("  dry run; no API call")
        return {"prompt": user, "index": index}

    provider = model if model in sm.MODEL_LADDER else sm.provider_for(model)
    reply, usage, used = sm.ask(model, SYSTEM, user, sm.api_key(provider),
                                max_tokens=MAX_OUTPUT)
    answer = sm.parse_json(reply)
    threads, periods, dropped = verify(answer, index)
    cov = coverage(threads, periods, meetings, style)

    out = {"committee": committee,
           "provider": sm.provider_for(used),
           "model": used,
           "model_requested": (model if used != model else None),
           "generated_at": datetime.datetime.utcnow().strftime(
               "%Y-%m-%dT%H:%M:%SZ"),
           "sources_sha": sha,
           "n_meetings": len(meetings),
           "period_style": style,
           "span": [meetings[0]["date"], meetings[-1]["date"]],
           "overview": (answer.get("overview") or "").strip(),
           "threads": threads,
           "periods": periods,
           "dropped": len(dropped),
           "coverage": cov,
           "usage": usage}
    report(cov, dropped)
    utils.write_atomic(dest, json.dumps(out, indent=1, ensure_ascii=False))
    print("  %d threads, %d periods -> %s" % (len(threads), len(periods), dest))
    return out




def priority_bodies(path=PRIORITY_FILE):
    """Body names to write first, in file order. # comments ignored."""
    if not os.path.exists(path):
        return []
    out = []
    for line in io.open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line and line not in out:
            out.append(line)
    return out


def active_bodies(video_data=None, days=365, min_summaries=MIN_SUMMARIES):
    """Public bodies worth an overview, best-covered first.

    ACTIVE IS COMPUTED, NOT FLAGGED -- the same definition and cutoff
    make_committee_pages uses for its "Active bodies" section, so the two
    pages never disagree about which bodies are current.
    """
    video_data = video_data or utils.get_video_data()
    cfg = utils.meeting_type_config()
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    last = {}
    for e in video_data.values():
        c = e.get("meeting_type")
        if not c or e.get("skip"):
            continue
        d = e.get("date") or e.get("upload_date") or ""
        if d > last.get(c, ""):
            last[c] = d
    out = []
    for c, s, n in summarisable(video_data):
        if c in NOT_A_BODY or s < min_summaries:
            continue
        if (cfg.get(c) or {}).get("kind", "committee") != "committee":
            continue
        if last.get(c, "") < cutoff:
            continue
        out.append((c, s, n, last.get(c, "")))
    # PRIORITY FIRST, in file order; the rest keep best-covered-first. A
    # stable sort on the rank alone preserves that for everything unlisted.
    rank = {name: i for i, name in enumerate(priority_bodies())}
    out.sort(key=lambda r: rank.get(r[0], len(rank)))
    return out


def summarisable(video_data=None):
    """(committee, n summarised, n meetings) for every body, best covered first."""
    video_data = video_data or utils.get_video_data()
    counts = {}
    for yt_id, e in video_data.items():
        c = e.get("meeting_type")
        if not c or e.get("skip"):
            continue
        base = (e.get("upload_date") or "") + "_" + yt_id
        have = os.path.exists(os.path.join(base, base + ".summary.json"))
        n, s = counts.get(c, (0, 0))
        counts[c] = (n + 1, s + (1 if have else 0))
    rows = [(c, s, n) for c, (n, s) in counts.items()]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--committee",
                    help="meeting_type name, e.g. "
                         "'MPS High School Building Committee'")
    ap.add_argument("--model", default=sm.DEFAULT_PROVIDER,
                    help="exact model id, or a provider name to let the "
                         "ladder choose. Default %s" % sm.DEFAULT_PROVIDER)
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble and size the prompt; make no API call")
    ap.add_argument("--show-prompt", action="store_true",
                    help="with --dry-run, print the assembled prompt")
    ap.add_argument("--check", action="store_true",
                    help="measure the overview already on disk; no API call")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--min-new", type=int, default=MIN_NEW_SUMMARIES,
                    dest="min_new",
                    help="how many new summaries a body must gain before an "
                         "EXISTING overview is redone. 0 redoes on any "
                         "change. Default %d" % MIN_NEW_SUMMARIES)
    ap.add_argument("--list", action="store_true",
                    help="summary coverage per body, best covered first")
    ap.add_argument("--active", action="store_true",
                    help="write an overview for every ACTIVE public body with "
                         "%d+ summarised meetings, best covered first"
                         % MIN_SUMMARIES)
    ap.add_argument("--limit", type=int, default=0,
                    help="with --active, stop after N bodies that needed a "
                         "request (cached ones do not count)")
    args = ap.parse_args()

    video_data = utils.get_video_data()
    if args.list:
        print("%-45s %9s %9s" % ("body", "summaries", "meetings"))
        for c, s, n in summarisable(video_data):
            if not s:
                continue
            print("%-45s %9d %9d" % (sm.printable(c)[:45], s, n))
        return 0
    if args.active:
        rows = active_bodies(video_data)
        print("%d active bodies with %d+ summaries" % (len(rows), MIN_SUMMARIES))
        made = failed = 0
        for c, s_, n, last in rows:
            if args.limit and made >= args.limit:
                print("stopping at --limit %d; re-run to continue (each "
                      "overview is cached on its sources)" % args.limit)
                break
            print("--- %s (%d of %d meetings summarised, last %s)"
                  % (sm.printable(c), s_, n, last))
            try:
                got = summarise_committee(c, args.model, args.dry_run,
                                          args.force, args.check, video_data,
                                          args.min_new)
                # CACHED OVERVIEWS ARE FREE, so they must not count against
                # --limit -- the same arithmetic bug summarize_meeting had,
                # where a limit was spent on meetings nothing was asked about.
                # _CACHED rather than "did the file exist", because a
                # REGENERATED overview also already existed and did cost a
                # request.
                if got is None:
                    failed += 1
                elif not _CACHED:
                    made += 1
            except sm.DailyQuotaExhausted as e:
                print("STOPPING: %s" % e)
                print("The allowance refills continuously, so re-running "
                      "later today will continue; overviews already written "
                      "are skipped on their sources_sha.")
                break
            except Exception as e:
                failed += 1
                print("  FAILED: %s" % str(e)[:160])
        print("%d %s, %d failed"
              % (made, "would be written" if (args.dry_run or args.check)
                 else "written", failed))
        # REBUILD THE PAGES, or the overview is invisible. Nothing else in
        # this path renders them: summarize_meeting rebuilds its own page when
        # it writes a sidecar, and the equivalent here is the committee pages,
        # which are otherwise regenerated only when a TRANSCRIPTION finishes.
        # Without this the hourly job would accumulate correct overviews that
        # no reader can see -- the failure this codebase keeps repeating.
        #
        # Once per batch, not once per overview: make() regenerates all 90
        # pages and the hub every time it runs.
        if made and not (args.dry_run or args.check):
            try:
                import make_committee_pages
                make_committee_pages.make()
                print("committee pages rebuilt")
            except Exception as e:
                # never lose an overview that cost real quota to a render error
                print("WARNING: overviews written but pages NOT rebuilt: %s"
                      % str(e)[:160])
        return 0

    if not args.committee:
        ap.error("give -c <committee>, --active or --list")

    known = {e.get("meeting_type") for e in video_data.values()}
    if args.committee not in known:
        print("No body named %r. Try --list." % args.committee)
        return 1
    out = summarise_committee(args.committee, args.model, args.dry_run,
                              args.force, args.check, video_data,
                              args.min_new)
    if args.dry_run and args.show_prompt and out:
        print()
        print(sm.printable(out["prompt"]))
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
