"""
Audit meeting dates against what is said aloud in the transcript.

WHO THIS IS FOR: the 673 videos whose TITLE carries no parseable date. Their
stored date falls back to the upload date, which for the MCM archive's bulk
ingests is wrong by years -- "Medford 5G Meeting 03-31-21" was stored as
2024-09-16 because that is when it was pulled from archive.org. For those, the
transcript is the only independent evidence available.

Videos whose title DOES carry a date are left alone: title_date is reliable
(measured: of 19 formally ambiguous mm-dd/dd-mm titles checked against a spoken
date, zero were dd-mm -- Medford writes mm-dd-yy consistently).

WHY THIS IS A REPORT AND NOT A FIX. Measured on 233 real meetings, only 23%
state a date in a detectable pattern, and 25% of those disagree with the stored
date -- almost always because the chair is referring to a DIFFERENT meeting.
The first version of this made it obvious: disagreements clustered at exactly
-7, -14 and -21 days, i.e. "motion to approve the minutes of the September 11th
meeting". Requiring a weekday or an explicit today/tonight helps, but
announcements share that phrasing ("our next meeting is Wednesday, March 13").
At that error rate, applying these automatically would introduce more errors
than it fixes. A human reads the list.

Usage:
    python audit_dates.py                  # meetings with no title date
    python audit_dates.py --all-types      # include podcasts, campaign videos
    python audit_dates.py --window 600     # seconds of transcript to search
"""

import argparse
import collections
import datetime
import glob
import io
import os
import re
import sys

import srt_lines
import utils

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}
DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"

# A meeting announces its own date with a weekday ("Today is Monday, September
# 14, 2026") or an explicit today/tonight. A reference to some other meeting
# rarely carries the weekday -- that is the whole discriminator.
SPOKEN = re.compile(
    r"(?:(?:" + DAYS + r")\s*,?\s*|(?:today|tonight)(?:'s)?(?:\s+\w+){0,3}?\s+(?:is\s+)?)"
    r"(" + "|".join(MONTHS) + r")\w*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?",
    re.I)

MEETING_PREFIXES = ("CC ", "MPS ")


def spoken_date(path, window, year_hint):
    """(iso_date, phrase) for the first date announced as today's, or (None, None)."""
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None, None
    for block in srt_lines.parse_srt(text):
        if block["start"] is None or block["start"] > window:
            continue
        m = SPOKEN.search(block["text"] or "")
        if not m:
            continue
        year = int(m.group(3)) if m.group(3) else year_hint
        if not year:
            continue
        try:
            return datetime.date(year, MONTHS[m.group(1).lower()],
                                 int(m.group(2))).isoformat(), m.group(0)[:48]
        except ValueError:
            continue
    return None, None


def transcript_for(yt_id, entry):
    base = (entry.get("upload_date") or "") + "_" + yt_id
    path = os.path.join(base, base + ".srt")
    return path if os.path.exists(path) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=420.0,
                    help="seconds of transcript to search (default 420)")
    ap.add_argument("--all-types", action="store_true",
                    help="include podcasts and campaign videos, not just meetings")
    ap.add_argument("--tolerance", type=int, default=1,
                    help="days of disagreement to ignore (default 1)")
    args = ap.parse_args()

    video_data = utils.get_video_data()
    checked = found = agree = 0
    flags = []

    for yt_id, entry in sorted(video_data.items(), key=lambda kv: kv[1].get("date") or ""):
        if entry.get("skip") or entry.get("date_manual"):
            continue
        # only where the title cannot answer: that is the population whose
        # stored date is an upload date rather than a meeting date
        if utils.title_date(entry.get("title"), not_after=entry.get("upload_date")):
            continue
        meeting_type = entry.get("meeting_type") or ""
        if not args.all_types and not meeting_type.startswith(MEETING_PREFIXES):
            continue
        path = transcript_for(yt_id, entry)
        if not path:
            continue

        checked += 1
        stored = entry.get("date")
        hint = int(stored[:4]) if stored else None
        said, phrase = spoken_date(path, args.window, hint)
        if not said:
            continue
        found += 1
        if said == stored:
            agree += 1
            continue
        try:
            delta = (datetime.date.fromisoformat(said)
                     - datetime.date.fromisoformat(stored)).days
        except (TypeError, ValueError):
            delta = None
        if delta is not None and abs(delta) <= args.tolerance:
            agree += 1
            continue
        flags.append((yt_id, stored, said, delta, meeting_type,
                      (entry.get("title") or "")[:46], phrase))

    print("meetings with no date in the title : %d" % checked)
    print("  a date is announced aloud        : %d (%.0f%%)"
          % (found, 100.0 * found / max(checked, 1)))
    print("  matches the stored date          : %d" % agree)
    print("  FOR REVIEW                       : %d" % len(flags))
    if flags:
        print()
        print("  %-12s %-10s %-10s %6s  %s" % ("id", "stored", "spoken", "delta", "title / phrase"))
        for yt_id, stored, said, delta, mt, title, phrase in flags:
            print("  %-12s %-10s %-10s %+6s  %s" % (yt_id, stored, said,
                                                    delta if delta is not None else "?", title))
            print("  %-12s %-10s %-10s %6s    said: %s   [%s]" % ("", "", "", "", phrase, mt[:26]))
        print()
        print("A weekly multiple (-7, -14, -21) usually means the chair was")
        print("approving the previous meeting's minutes, not stating today's date.")
        print("To accept one:  set date and date_manual:true in video_data.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
