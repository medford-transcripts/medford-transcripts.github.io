"""Fill in the `subject` line on summaries written before the field existed.

WHY NOT JUST RE-SUMMARISE THEM. 248 summaries predate the subject field. Asking
for them again from the transcripts costs 248 requests and ~9.4M input tokens --
about four days of the free-tier allowance, taken from a backlog that already
needs ~34 days. But a subject does not need the transcript: the summary already
contains the overview and the agenda-item titles, and ALL 248 of those together
come to ~37k tokens, which is the size of ONE transcript.

So this is one request, not 248.

ONE REQUEST, NOT A BATCH OF FIVE. An earlier version chunked this at 50 to stay
inside MAX_OUTPUT, which was wrong: that cap binds the Anthropic and OpenAI
paths, while _gemini_call raises the Gemini budget to 32,000 regardless, and 248
subjects is ~6.2k of output. REQUESTS are the scarce resource here -- roughly 20
per model family per day -- so five requests where one will do spends 7% of a
day's capacity to buy nothing. Chunking also costs its five requests every time,
where one request plus a retry costs two in the worst case.

WHAT REPLACES CHUNKING IS PER-ID VALIDATION. Every id sent must come back with a
parseable entry. Missing, malformed or truncated ones are re-asked in a single
follow-up, so a partial answer is still fully usable and we only pay for the
actual gaps.

PROVENANCE IS RECORDED, because a subject derived from a summary is NOT the same
judgement as one derived from a transcript. The summarising model saw what was
contested, how long each item ran, and how much public comment there was; a model
reading only the summary inherits that summary's emphasis and cannot recover
anything it dropped. So these are written with subject_source="summary", against
"transcript" for ones the main prompt produces, and each upgrades for free the
next time its transcript_sha changes. Same two-tier shape as the speaker
provenance and as title_source in scrape_staff.

THE QUOTA REFILLS CONTINUOUSLY, so this is safe to attempt before each hourly
summarize run: it is a no-op when nothing lacks a subject, and it exits 0 without
writing anything when there is no allowance left.

    python backfill_subjects.py            # dry run: show what it would write
    python backfill_subjects.py --apply    # write into the summary sidecars
"""

import argparse
import glob
import io
import json
import os
import re
import sys

import summarize_meeting as S
import utils

SOURCE = "summary"

SYSTEM = """You name the single matter a Medford, Massachusetts public meeting \
will be remembered for.

You are given a JSON array of meetings. Each has an id, the body that met, a \
one-or-two sentence overview, and the titles of its agenda items. For each one, \
return a subject line.

RULES, which matter more than coverage:
- At most about eight words. A noun phrase, not a sentence: no verb, no \
trailing full stop, no date, and do not name the body -- the page already says \
which committee met and when.
- TITLE CASE: "Salem Street Corridor Rezoning", not "Salem street corridor \
rezoning". Keep acronyms exactly as written -- ICE, CDBG, MCAS, ADA, MSBA, CPA \
-- and keep short joining words lowercase ("Rules of Order"). This must match \
the wording the transcript-derived subjects use, or the site shows two styles \
side by side depending on which path produced the line.
- RETURN AN EMPTY STRING when no single matter dominates. A regular council \
meeting that moved licences, a resolution, a wage agreement and an ordinance has \
no one subject, and guessing at one tells a reader the meeting was about \
something it was not. An empty string is a correct and expected answer.
- Never use a procedural heading: not "Consent Agenda", "Approval of Minutes", \
"Executive Session", "Reports of Committees" or "Public Participation". If that \
is all the meeting did, return an empty string.
- Judge each meeting only on its own overview and items. Do not aim for any \
particular proportion of empty answers, and do not let the meetings you have \
already handled influence this one.

Return ONLY valid JSON, no prose around it. One entry per input id, in the same \
order, every id present:
{"subjects": [{"id": "<the id>", "subject": "<<=8 words, or empty string>"}]}"""


def pending(video_data):
    """[(yt_id, path, payload)] for summaries with no subject field yet."""
    out = []
    for path in sorted(glob.glob(os.path.join("20*_*", "*.summary.json"))):
        try:
            with io.open(path, encoding="utf-8") as fp:
                d = json.load(fp)
        except Exception as e:
            print("  unreadable %s (%s)" % (path, e))
            continue
        if (d.get("subject") or "").strip():
            continue
        if "subject" in d and d.get("subject_source") == SOURCE:
            continue              # already attempted and legitimately declined
        yt = d.get("video_id")
        if not yt:
            continue
        e = video_data.get(yt) or {}
        out.append((yt, path, {
            "id": yt,
            "body": utils.body_label(e.get("meeting_type")) or "unknown body",
            "overview": (d.get("overview") or "")[:600],
            "items": [(i.get("title") or "")[:90]
                      for i in (d.get("items") or [])][:20],
        }))
    return out


# One complete {"id": .., "subject": ..} object, in either key order.
PAIR = re.compile(
    r'\{\s*"id"\s*:\s*"([^"]+)"\s*,\s*"subject"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
    r'|\{\s*"subject"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"id"\s*:\s*"([^"]+)"\s*\}')


def parse_subjects(reply):
    """{id: raw subject}, TOLERATING A TRUNCATED REPLY.

    Asked about all 248 at once, the model answered with 2,547 output tokens
    and stopped mid-JSON at char 7,396 -- nowhere near Gemini's 32,000-token
    budget. It simply does not emit 248 structured entries in one go. Requiring
    the whole document to parse threw away ~150 good answers along with the
    broken tail, and the request had already been paid for.

    So complete pairs are lifted out individually and the unterminated tail is
    discarded. Whatever is missing is then re-asked by the caller, which is
    cheaper than pre-splitting the job into chunks that each cost a request.
    """
    try:
        data = json.loads(reply)
        rows = data.get("subjects") if isinstance(data, dict) else data
        if isinstance(rows, list):
            got = {}
            for row in rows:
                if isinstance(row, dict) and row.get("id"):
                    got[str(row["id"])] = row.get("subject") or ""
            return got, False
    except Exception:
        pass
    got = {}
    for m in PAIR.finditer(reply):
        yt, subj = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        try:
            subj = json.loads('"%s"' % subj)
        except Exception:
            pass
        got[yt] = subj
    return got, True


def ask_subjects(payloads, model):
    """{id: raw subject} from one request. Raises on a hard failure."""
    user = json.dumps(payloads, ensure_ascii=False)
    print("  asking about %d meetings (%.0fk chars, ~%.0fk tokens)"
          % (len(payloads), len(user) / 1000.0, len(user) / 4000.0))
    key = S.api_key(S.provider_for(model) if model != "gemini" else "gemini")
    reply, usage, used = S.ask(model, SYSTEM, user, key)
    got, salvaged = parse_subjects(reply)
    print("  %s answered; in/out tokens %s/%s -> %d entries%s"
          % (used, usage.get("input_tokens"), usage.get("output_tokens"),
             len(got), " (salvaged from a truncated reply)" if salvaged else ""))
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--model", default=S.DEFAULT_PROVIDER)
    ap.add_argument("--limit", type=int, default=0,
                    help="only consider the first N (for a cheap trial)")
    args = ap.parse_args()

    if S.self_test_subject():
        print("REFUSING to continue: the subject rules failed their own tests.")
        return 1

    vd = utils.get_video_data()
    todo = pending(vd)
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        print("nothing to backfill: every summary already carries a subject.")
        return 0
    print("summaries missing a subject: %d" % len(todo))

    payloads = [p for _, _, p in todo]
    try:
        got = ask_subjects(payloads, args.model)
    except S.DailyQuotaExhausted as e:
        # EXIT 0, NOT 1. This runs before each hourly summarize pass and the
        # allowance refills continuously; "no quota right now" is a normal
        # outcome, not a failure to alert on.
        print("no allowance right now (%s) -- nothing written, try next hour." % e)
        return 0
    except Exception as e:
        print("request failed: %s" % e)
        return 1

    # PER-ID VALIDATION IS WHAT MAKES THE BIG ASK SAFE. The reply truncates, so
    # the gaps are re-asked -- and the gap-fill can truncate too, which is why
    # this loops. It stops when a round makes no progress, so a model that has
    # stopped answering costs one wasted request, not an unbounded run.
    for round_no in range(1, 6):
        missing = [p for p in payloads if p["id"] not in got]
        if not missing:
            break
        print("  round %d: %d still unanswered" % (round_no, len(missing)))
        before = len(got)
        try:
            got.update(ask_subjects(missing, args.model))
        except S.DailyQuotaExhausted as e:
            print("  allowance ran out mid-run (%s); keeping what we have" % e)
            break
        except Exception as e:
            print("  round %d failed (%s); keeping what we have" % (round_no, e))
            break
        if len(got) <= before:
            print("  no progress this round; stopping")
            break

    rows, kept, declined = [], 0, 0
    for yt, path, payload in todo:
        if yt not in got:
            continue
        raw = got[yt]
        e = vd.get(yt) or {}
        subject = S.clean_subject(raw, e.get("meeting_type"), e.get("title"))
        if subject:
            kept += 1
        else:
            declined += 1
        rows.append((yt, path, raw, subject, e))

    print()
    print("  answered   %d of %d" % (len(rows), len(todo)))
    print("  a subject  %d" % kept)
    print("  declined   %d  (empty, or rejected by clean_subject)" % declined)
    rejected = [(y, r) for y, _, r, s, _ in rows if r.strip() and not s]
    if rejected:
        print("  of the declined, %d were REJECTED after the model offered one:"
              % len(rejected))
        for y, r in rejected[:12]:
            print("     %-13s %s" % (y, r[:60]))

    print()
    print("  %-13s %-34s %s" % ("id", "subject", "display title"))
    for yt, path, raw, subject, e in rows:
        if not subject:
            continue
        print("  %-13s %-34s %s"
              % (yt, subject[:34],
                 utils.display_title(yt, e, subject=subject)[:72]))

    if not args.apply:
        print()
        print("DRY RUN -- nothing written. Review the subjects above, then --apply.")
        return 0

    wrote = 0
    for yt, path, raw, subject, e in rows:
        try:
            with io.open(path, encoding="utf-8") as fp:
                d = json.load(fp)
        except Exception as err:
            print("  skip %s (%s)" % (path, err))
            continue
        d["subject"] = subject
        d["subject_source"] = SOURCE
        tmp = path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
            json.dump(d, fp, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
        wrote += 1
    print()
    print("wrote %d summaries (subject_source=%s)" % (wrote, SOURCE))
    print("Pages are NOT rebuilt here -- rendering is a separate pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
