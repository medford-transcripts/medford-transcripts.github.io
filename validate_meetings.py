"""
Validate a meeting's TYPE against who actually spoke at it.

THE IDEA (owner's): the transcript knows things the title does not. City
Councilors and School Committee members are disjoint rosters, nearly every
meeting opens with a roll call, and speaker_ids.json already records who
spoke. So attendance is an independent check on a classification that is
otherwise derived from keyword-matching a human-typed title.

MEASURED on 1,620 classified meetings with speaker ids:

    quorum  majority   flagged        agreement   disagreements
      2       67%      1021 (63%)       99.2%          8
      3       70%       963 (59%)       99.8%          2
      4       75%       847 (52%)       99.9%          1

Those figures predate the body_of fix below, which stopped extending a
position past its last recorded year. After it, the default setting reaches
965 (60%) at 99.9% with ONE disagreement -- slightly more coverage and
strictly better precision, because stale members no longer pad a quorum.

The default is 3 officials and a 70% majority. Below a quorum the signal is noise -- a single School Committee
member sitting on the Charter Study Committee or the Community Development
Board is not evidence that the meeting was mis-typed, and at quorum 2 that is
exactly what produced most of the false flags.

It found a real one: MCM00001762, titled "Medford School Committee of the
Whole" with five School Committee members speaking, was typed "CC City
Council Meeting of the Whole" -- "committee of the whole" is a keyword for
both types and the City Council entry is checked first. Meetings from the
Medford Public Schools channel avoid this because get_meeting_type has a
channel-specific branch; this one came from the MCM archive and fell through
to the generic loop.

DELIBERATELY A REPORT, NOT AN AUTO-CORRECTION. At 99.8% the method is right
far more often than not, but the residual disagreements are genuinely
ambiguous joint or cross-body meetings, and a wrong meeting_type silently
moves a meeting to the wrong committee page and detaches its agenda. The
output is a short list for a human.

Usage:
    python validate_meetings.py                 # report disagreements
    python validate_meetings.py --quorum 4      # stricter
    python validate_meetings.py --all           # include agreements
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import sys

import utils

ROSTER_FILE = "councilors.json"
CC_POS = re.compile(r"city_council|councilor|council_", re.I)
SC_POS = re.compile(r"school_committee|school_", re.I)


def load_roster(path=ROSTER_FILE):
    try:
        with io.open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {}


def body_of(roster, name, year):
    """'cc' | 'sc' | None for a person in a given year.

    ONLY WITHIN THE RECORDED SPAN. councilors.json stores per-year snapshots
    with no term start/end, and an earlier version fell back to the nearest
    EARLIER year -- which extended a position forward for ever, counting a
    councilor who served 2015-2017 as sitting in 2026. Measured: 22 of the 39
    office-holders have a last recorded year before 2026, and those last years
    cluster on odd years, i.e. Medford's municipal election cycle. So the
    roster does know when people left; it just encodes it as absence.

    Treating absence as "not in office" is the conservative reading. It costs
    coverage on years nobody has filled in, and it never invents a term.
    Candidates are skipped: standing for a seat is not holding one.

    A real term range (see plan 12.3) would be better than inferring one from
    which years happen to be present.
    """
    years = roster.get(name)
    if not isinstance(years, dict):
        return None
    held = {}
    for y, info in years.items():
        if not (y.isdigit() and isinstance(info, dict)):
            continue          # 'website', 'facebook', ... are plain strings
        for pos in (info.get("position") or []):
            if "candidate" in pos:
                continue
            if SC_POS.search(pos):
                held[y] = "sc"
            elif CC_POS.search(pos):
                held.setdefault(y, "cc")
    if not held:
        return None
    year = str(year)
    if year in held:
        return held[year]
    lo, hi = min(held), max(held)
    if lo <= year <= hi:
        # inside a recorded span with a gap: carry the nearest earlier year
        return held[max(y for y in held if y <= year)]
    return None               # outside the span: we do not know


def attendance(roster, speaker_ids, year):
    """Counter of {'cc': n, 'sc': n} over the identified officials who spoke."""
    votes = collections.Counter()
    for _raw, name in (speaker_ids or {}).items():
        # unnamed labels and cross-video cluster keys are not people yet
        if not name or name.startswith("SPEAKER_") or "_SPEAKER_" in name:
            continue
        body = body_of(roster, name, year)
        if body:
            votes[body] += 1
    return votes


def check(quorum=3, majority=0.70, show_all=False):
    roster = load_roster()
    video_data = utils.get_video_data()
    rows, flagged, agree, disagree = 0, 0, 0, []

    for path in sorted(glob.glob("20??-??-??_*/speaker_ids.json")):
        yt_id = os.path.dirname(path).split("_", 1)[1]
        entry = video_data.get(yt_id)
        if not entry or entry.get("skip"):
            continue
        meeting_type = entry.get("meeting_type") or ""
        if not (meeting_type.startswith("CC ") or meeting_type.startswith("MPS ")):
            continue
        rows += 1
        try:
            with io.open(path, encoding="utf-8") as fp:
                speaker_ids = json.load(fp)
        except (OSError, ValueError):
            continue

        votes = attendance(roster, speaker_ids, (entry.get("date") or "2020")[:4])
        total = sum(votes.values())
        if total < quorum:
            continue
        body, count = votes.most_common(1)[0]
        if count / float(total) < majority:
            continue

        flagged += 1
        expected = "cc" if meeting_type.startswith("CC ") else "sc"
        if body == expected:
            agree += 1
            if show_all:
                print("  ok       %-12s %-34s %s" % (yt_id, meeting_type[:34], dict(votes)))
        else:
            disagree.append((yt_id, meeting_type, dict(votes), entry.get("title") or ""))

    print("classified meetings with speaker ids : %d" % rows)
    print("  attendance gave a quorum           : %d (%.0f%%)"
          % (flagged, 100.0 * flagged / max(rows, 1)))
    print("  agrees with meeting_type           : %d (%.1f%%)"
          % (agree, 100.0 * agree / max(flagged, 1)))
    print("  DISAGREES                          : %d" % len(disagree))
    for yt_id, meeting_type, votes, title in disagree:
        print()
        print("  %s" % yt_id)
        print("    typed    : %s" % meeting_type)
        print("    attendance: %s" % votes)
        print("    title    : %s" % title[:70])
    return disagree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quorum", type=int, default=3,
                    help="minimum identified officials before judging (default 3)")
    ap.add_argument("--majority", type=float, default=0.70,
                    help="fraction from one body required (default 0.70)")
    ap.add_argument("--all", action="store_true", help="also list agreements")
    args = ap.parse_args()
    check(quorum=args.quorum, majority=args.majority, show_all=args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
