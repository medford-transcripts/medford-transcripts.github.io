"""
Compare generated summaries of one meeting, across models, against the human
recap of the same meeting.

WHY A SCRIPT. Reading four JSON files side by side is tedious and the eye
slides past the thing that matters: whether a specific, checkable claim is
right. The 2026-09-14 School Committee meeting has a recap written by a sitting
member (reference/recaps/), which gives a handful of facts that can be
mechanically verified:

  - the after-school programme grew from 407 to 568 and its waitlist fell from
    212 to 68. The recap states these as "40% increase" and "68% decrease",
    which those raw numbers reproduce exactly -- so a model that gives the raw
    figures is demonstrably reading the transcript rather than paraphrasing.
  - the CTE honors pilot was presented by Fallon.
  - the student author's name. The recap says Xandria; the transcript's ASR
    heard Andrea. A summary that says Andrea is faithfully reporting a bad
    transcript, which is correct behaviour and worth seeing.

Usage:
    python compare_summaries.py [--dir _summary_test]
"""

import argparse
import glob
import io
import json
import os
import re
import sys

# The Windows console is cp1252; summary text contains arrows, curly quotes and
# the like. Print through a sanitiser rather than crashing on one character.
def out(msg=""):
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    sys.stdout.write(msg.encode(enc, "replace").decode(enc))
    sys.stdout.write(chr(10))


# (label, regex, what it tells you)
CHECKS = [
    ("after-school 407->568", r"\b407\b.{0,40}\b568\b|\b568\b.{0,40}\b407\b",
     "raw figures that match the recap's stated percentages"),
    ("waitlist 212->68", r"\b212\b.{0,40}\b68\b",
     "same, for the waitlist"),
    ("Fallon (CTE pilot)", r"\bFallon\b", "presenter attribution"),
    ("student name", r"\b(Xandria|Andrea)\b", "Xandria is right; Andrea is the ASR error"),
    # Deliberately narrow. A bare \d+-\d+ matches "5-13" (a date) and
    # "2026-27" (a school year); only a number pair ATTACHED to a voting
    # verb is evidence of a tally.
    ("vote tally?", r"(?:vote[ds]?|passed|approved|carried)\s+(?:by\s+)?\d+\s*[-to]{1,3}\s*\d+",
     "should be '-' for every model: tallies are forbidden")
]


def words(d):
    n = len((d.get("overview") or "").split())
    for it in d.get("items") or []:
        n += len((it.get("title") or "").split()) + len((it.get("summary") or "").split())
    return n


def blob(d):
    parts = [d.get("overview") or ""]
    for it in d.get("items") or []:
        parts += [it.get("title") or "", it.get("summary") or ""]
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="_summary_test")
    args = ap.parse_args()

    rows = []
    for p in sorted(glob.glob(os.path.join(args.dir, "*.json"))):
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except ValueError:
            continue
        rows.append((os.path.basename(p)[:-5], d))
    if not rows:
        raise SystemExit("no summaries in %s" % args.dir)

    out("%-14s %6s %5s %7s %8s  %s" % ("model", "items", "words", "in", "out", "provider"))
    for name, d in rows:
        u = d.get("usage") or {}
        out("%-14s %6d %5d %7s %8s  %s"
              % (name, len(d.get("items") or []), words(d),
                 u.get("input_tokens"), u.get("output_tokens"),
                 d.get("provider") or "?"))

    out("\nCHECKABLE CLAIMS (from the member's recap of this same meeting)")
    out("%-14s %s" % ("model", "  ".join("%-22s" % c[0] for c in CHECKS)))
    for name, d in rows:
        t = blob(d)
        cells = []
        for label, rx, _ in CHECKS:
            m = re.search(rx, t, re.I)
            hit = m.group(0)[:20] if m else "-"
            cells.append("%-22s" % hit)
        out("%-14s %s" % (name, "  ".join(cells)))
    out()
    for label, _, why in CHECKS:
        out("   %-22s %s" % (label, why))

    out("\nOVERVIEW, each model:")
    for name, d in rows:
        out("\n  [%s]" % name)
        out("   " + (d.get("overview") or "").strip()[:400])


if __name__ == "__main__":
    main()
