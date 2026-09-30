"""Generate verify.html -- the page asking readers to check specific things.

WHY THIS EXISTS. verify.html was written by hand, with its counts computed in a
throwaway script. It claimed "697 clusters open" for days after ~88 of them had
been resolved, because nothing regenerated it. A public page that states a
number nobody recomputes will be wrong shortly after it is published, and this
one asks people to spend their time on the basis of those numbers.

The prose lives in verify_template.html and is meant to be edited by hand. This
module only fills the {{PLACEHOLDERS}}, so the wording stays reviewable as HTML
and the figures stay derived.

DELIBERATELY NOT GENERATED: the "Meeting dates" section. Those two cases are an
investigation written out in prose -- which councillors were in the room, how
long the recording is, what the upload date implies -- and there is no honest
way to derive that from the corpus. It is hand-maintained, and saying so here is
better than generating a number that looks derived and is not.

    python make_verify.py            # write verify.html
    python make_verify.py --dry-run  # report the figures, write nothing
"""

import argparse
import collections
import datetime
import glob
import io
import json
import os
import re
import sys

import utils

# chr(10) rather than a backslash-n literal: every attempt to write one
# through this session's tooling collapsed it into a real newline mid-string.
NL = chr(10)

TEMPLATE = "verify_template.html"
OUTPUT = "verify.html"
SITE = "https://medford-transcripts.github.io/"

# Labels whose voiceprint is demonstrably unstable, with the bodies where the
# person genuinely belongs. A cluster carrying one of these names in ANY OTHER
# body is "open" -- someone else's voice wearing this name.
#
# The legitimate-body lists are editorial and must stay that way: they encode
# who holds which office, which no measurement can tell us. The consistency
# figure beside each one IS measured, and is refreshed on every run.
SUSPECT = collections.OrderedDict((
    ("Adam Hurtubise", {
        "note": "the city clerk, but labelled in %(meetings)d meetings "
                "including boards he has no role in",
        "bodies": ("CC City Council", "CC City Council Meeting of the Whole"),
    }),
    ("Marie Izzo", {
        "note": "also reads the roll",
        "bodies": ("CC City Council", "CC City Council Meeting of the Whole"),
    }),
    ("Adam Knight", {
        "note": "occasionally reads the roll",
        "bodies": ("CC City Council", "CC City Council Meeting of the Whole"),
    }),
))

GOV = re.compile(r"^(CC |MPS )")
NAME_LINE = re.compile(r"^(?:And\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){1,2})\s*[.?,]?$")
ASSENT = re.compile(r"^(here|yes|present|aye|no|i'm here|yep|absent|"
                    r"[A-Z][a-z]+ (?:is )?absent)\b", re.I)
SPK_LINE = re.compile(r"^\[([^\]]+)\]:\s*(.*)$")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def page_url(meeting_dir):
    base = os.path.basename(meeting_dir)
    return SITE + utils.web_path(os.path.join(base, base + ".html"))


def meeting_dirs():
    """{yt_id: dir} for every meeting directory that has a transcript page."""
    out = {}
    for d in glob.glob("20??-??-??_*"):
        if not os.path.isdir(d):
            continue
        yt = d.split("_", 1)[1]
        if os.path.exists(os.path.join(d, os.path.basename(d) + ".html")):
            out.setdefault(yt, d)
    return out


# ---------------------------------------------------------------------------
# who is speaking

def open_clusters(vd, dirs):
    """[(body, yt, key, name, lines)] for suspect labels outside their bodies."""
    rows = []
    per_name_meetings = collections.Counter()
    for j in sorted(glob.glob("*/speaker_ids.json")):
        d = os.path.dirname(j)
        yt = d.split("_", 1)[1]
        e = vd.get(yt) or {}
        if e.get("skip"):
            continue
        try:
            ids = json.load(io.open(j, encoding="utf-8"))
        except Exception:
            continue
        body = str(e.get("meeting_type") or "untyped")
        srt = os.path.join(d, os.path.basename(d) + ".srt")
        text = None
        for key, name in ids.items():
            if name not in SUSPECT:
                continue
            per_name_meetings[name] += 1
            if body in SUSPECT[name]["bodies"]:
                continue
            if text is None:
                try:
                    text = io.open(srt, encoding="utf-8", errors="replace").read()
                except Exception:
                    text = ""
            rows.append((body, yt, key, name, text.count(key)))
    return rows, per_name_meetings


def consistency_rows(per_name_meetings):
    """The suspect-label table, with MEASURED consistency."""
    try:
        import track_speakers as TS
        cons = TS.speaker_self_consistency()
    except Exception as exc:
        sys.stderr.write("WARNING: consistency unavailable (%s)\n" % str(exc)[:80])
        cons = {}
    out = []
    for name, cfg in SUSPECT.items():
        pair = cons.get(name) or [None, None]
        score = pair[1]
        cls = "mono bad" if (score is not None and score < 0.50) else "mono"
        shown = "%.2f" % score if score is not None else "&mdash;"
        note = cfg["note"] % {"meetings": per_name_meetings.get(name, 0)}
        out.append('      <tr><td>%s</td><td class="%s">%s</td><td>%s</td></tr>'
                   % (esc(name), cls, shown, esc(note)))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# roll calls

def rollcall_stats(vd, dirs):
    """(called, answered, [(date, title, called, pct, url)]) for 0%-answer meetings."""
    known = set()
    try:
        for n in json.load(io.open("councilors.json", encoding="utf-8")):
            known.add(str(n).lower())
            known.add(str(n).split()[-1].lower())
    except Exception:
        pass

    called = answered = 0
    worst = []
    for p in sorted(glob.glob("*/20??-??-??_*.srt")):
        d = os.path.dirname(p)
        yt = d.split("_", 1)[1]
        e = vd.get(yt) or {}
        if e.get("skip") or not GOV.match(str(e.get("meeting_type") or "")):
            continue
        try:
            ids = json.load(io.open(os.path.join(d, "speaker_ids.json"), encoding="utf-8"))
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        local = set(known)
        for v in ids.values():
            if utils_is_name(v):
                local.add(str(v).lower())
                local.add(str(v).split()[-1].lower())

        seq = []
        for b in re.split(r"\n\s*\n", txt):
            lines = [l for l in b.strip().split("\n") if l.strip()]
            if lines:
                m = SPK_LINE.match(lines[-1])
                if m:
                    seq.append((m.group(1), m.group(2).strip()))

        # A ROLL CALL IS A RUN, NOT SCATTERED NAMES. One speaker reads names
        # consecutively and each may be followed by an assent. Counting every
        # name-shaped line in the meeting instead inflated "called" from 19,872
        # to 30,959 and collapsed the capture rate from 90% to 24%, because
        # ordinary speech is full of names nobody answers to. The run must also
        # name people this corpus KNOWS -- that filter is what keeps a
        # commencement ceremony reading 157 graduates out of the numbers.
        i = mc = ma = 0
        while i < len(seq):
            spk, t = seq[i]
            if not NAME_LINE.match(t):
                i += 1
                continue
            j, names, resp, hits = i, 0, 0, 0
            while j < len(seq):
                s2, t2 = seq[j]
                m2 = NAME_LINE.match(t2)
                if s2 == spk and m2:
                    names += 1
                    if m2.group(1).split()[-1].lower() in local:
                        hits += 1
                    j += 1
                    if j < len(seq) and ASSENT.match(seq[j][1]):
                        resp += 1
                        j += 1
                else:
                    break
            if names >= 3 and hits >= max(2, names // 2):
                mc += names
                ma += resp
                i = j
            else:
                i += 1
        if mc:
            called += mc
            answered += ma
            # THRESHOLD OF 5, NOT 10. Medford's City Council and School Committee
            # have SEVEN members and subcommittees three to five, so one roll call
            # is 3-7 names. Requiring >=10 required TWO OR MORE roll calls in a
            # single meeting before it could be reported as broken, which made
            # "no meetings where every name went unanswered" nearly vacuous: a
            # meeting whose only roll call failed entirely could not qualify. The
            # eight meetings originally listed all had 10-41 names, i.e. they were
            # multi-vote meetings; single-roll-call failures were never visible.
            # EVERY meeting with a roll call, ranked later by VOTES MISSING.
            # Ranking by percentage is the wrong instrument: a 42% meeting with 78
            # names loses 45 votes, a 0% meeting with 5 names loses 5. The first is
            # where an hour of someone's attention buys the most record back.
            if mc >= 5:
                worst.append((mc - ma, mc, ma, str(utils.meeting_date(e)),
                              str(e.get("meeting_type") or "untyped"), page_url(d)))
    worst.sort(reverse=True)
    return called, answered, worst


def utils_is_name(v):
    s = str(v or "")
    return bool(s) and " " in s and not s.startswith("SPEAKER_") and "_SPEAKER_" not in s


# ---------------------------------------------------------------------------
# duplicates

def duplicate_pairs(vd, dirs, tol=0.25):
    """Same date + body, two copies of comparable length -- a likely real dup."""
    groups = collections.defaultdict(list)
    for yt, e in vd.items():
        if e.get("skip") or e.get("duplicate_id"):
            continue
        dur = e.get("duration")
        if not dur or yt not in dirs:
            continue
        groups[(str(utils.meeting_date(e)), str(e.get("meeting_type") or "untyped"))].append(
            (float(dur), yt))
    pairs = []
    for (date, body), items in groups.items():
        if len(items) < 2:
            continue
        items.sort(reverse=True)
        a, b = items[0], items[1]
        if a[0] <= 0:
            continue
        if (a[0] - b[0]) / a[0] <= tol:
            pairs.append((date, body, a, b))
    pairs.sort(reverse=True)
    return pairs


# ---------------------------------------------------------------------------

def build():
    vd = utils.get_video_data()
    dirs = meeting_dirs()

    rows, per_name = open_clusters(vd, dirs)
    by_body = collections.Counter(r[0] for r in rows)
    total_open = len(rows)

    # two largest-text clusters per body: most words, so easiest to place
    per_body_best = collections.defaultdict(list)
    for body, yt, key, name, lines in rows:
        per_body_best[body].append((lines, yt, key, name))
    meeting_rows = []
    for body, _n in by_body.most_common():
        for lines, yt, key, name in sorted(per_body_best[body], reverse=True)[:2]:
            d = dirs.get(yt)
            if not d:
                continue
            e = vd.get(yt) or {}
            meeting_rows.append(
                '  <tr><td>%s</td><td>%s</td><td>%s</td><td class="mono">%d</td>'
                '<td><a href="%s">open transcript</a></td></tr>'
                % (esc(str(utils.meeting_date(e))), esc(body), esc(name), lines, page_url(d)))

    called, answered, worst = rollcall_stats(vd, dirs)
    missing = called - answered
    pairs = duplicate_pairs(vd, dirs)

    missing_total = sum(w[0] for w in worst)
    losing = [w for w in worst if w[0] > 0]

    fill = {
        # Roll calls, ranked by VOTES MISSING. A dozen links, because the ask is
        # "watch one roll call", not "read a report".
        "ROLLCALL_COUNT": "%d meetings losing votes" % len(losing),
        "ROLLCALL_LINKS": NL.join(
            '  <tr><td class="mono">%s</td><td>%s</td>'
            '<td class="mono bad">%d</td><td class="mono">%d of %d</td>'
            '<td><a href="%s">open transcript</a></td></tr>'
            % (esc(date), esc(body), miss, ma, mc, url)
            for miss, mc, ma, date, body, url in losing[:12])
            or '  <tr><td colspan="5" class="note">none right now</td></tr>',
        "ROLLCALL_STATS_LINE":
            "Across the archive %s names were called in a roll call and %s had an "
            "answer captured, leaving %s with no response recorded. %d meetings "
            "are missing at least one."
            % (format(called, ","), format(answered, ","),
               format(called - answered, ","), len(losing)),

        "OPEN_COUNT": "%d clusters open" % total_open,
        "OPEN_MEETINGS": NL.join(meeting_rows[:12])
            or '  <tr><td colspan="5" class="note">none right now</td></tr>',
        "OPEN_BY_BODY_LINE":
            "%d clusters across %d bodies. Worst affected: %s."
            % (total_open, len(by_body),
               "; ".join("%s (%d)" % (esc(b), n) for b, n in by_body.most_common(4))),

        "DUP_COUNT": "%d to spot-check" % len(pairs),
        "DUP_ROWS": NL.join(
            '  <tr><td class="mono">%s</td><td>%s</td><td>'
            '<a href="%s">%d&thinsp;s</a> &middot; <a href="%s">%d&thinsp;s</a></td></tr>'
            % (esc(date), esc(body), page_url(dirs[a[1]]), int(a[0]),
               page_url(dirs[b[1]]), int(b[0]))
            for date, body, a, b in pairs[:12])
            or '  <tr><td colspan="3" class="note">none right now</td></tr>',

        "GENERATED": datetime.datetime.now().strftime("%d %B %Y").lstrip("0"),
    }
    return fill, dict(total_open=total_open, bodies=len(by_body), called=called,
                      answered=answered, worst=len(losing), pairs=len(pairs),
                      missing=missing_total)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fill, summary = build()
    print("open clusters      : %(total_open)d across %(bodies)d bodies" % summary)
    print("roll call          : %(called)d called, %(answered)d answered" % summary)
    print("  meetings losing votes: %(worst)d  (%(missing)d votes unrecorded)" % summary)
    print("duplicate pairs    : %(pairs)d" % summary)

    tpl = io.open(TEMPLATE, encoding="utf-8").read()
    out = tpl
    for k, v in fill.items():
        out = out.replace("{{%s}}" % k, v)
    left = re.findall(r"\{\{(\w+)\}\}", out)
    if left:
        # A placeholder with no value would publish a literal "{{FOO}}" to
        # readers, so refuse rather than ship it.
        print("UNFILLED PLACEHOLDERS: %s -- refusing to write" % sorted(set(left)))
        return 1
    if args.dry_run:
        print("\nDRY RUN -- %s not written (%d bytes would be)" % (OUTPUT, len(out)))
        return 0
    utils.write_atomic(OUTPUT, out)
    print("\nwrote %s (%d bytes)" % (OUTPUT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
