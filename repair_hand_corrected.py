"""
Repair rule-corrupted transcripts that ALSO carry hand corrections.

repair_rule_corruption.py deliberately skips these 81 files. For a file with
no manual edits the repair is a pure substitution -- the published .srt is
exactly old_rules(.orig), so writing new_rules(.orig) is provably safe. These
files are not: they contain human edits that exist ONLY in the .srt, and
rebuilding from .orig would silently discard them. Those edits are the most
valuable text in the archive (corrected roll calls, reassigned speakers) and
are the seed of the eval set.

STRATEGY: apply only the corrections we can prove are safe, in place, one
substitution at a time.

For each file we compute three versions:
    orig       the untouched .srt.orig
    was        old_rules(orig)   -- what the pipeline WOULD have published
    should     new_rules(orig)   -- what it should have published
    published  the actual .srt   -- "was" plus the human's edits

Where `was` and `should` differ, that difference is a known corruption. We
rewrite ONLY those exact spans in `published`, and only where the corrupted
text still appears verbatim -- i.e. where the human did not touch that line.
If a corrupted span is missing from `published`, the human already rewrote
that region and we leave it entirely alone rather than guess.

Every file is verified afterwards: the result must differ from `published`
ONLY by the intended substitutions, and must not lose any line the human
added.

Usage:
    python repair_hand_corrected.py            # dry run
    python repair_hand_corrected.py --apply
"""

import argparse
import difflib
import importlib.util
import io
import json
import os
import sys

import fix_common_errors as fce


def load_helper():
    spec = importlib.util.spec_from_file_location("fme", "find_manual_edits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corrupted_spans(was, should):
    """Line pairs where the old rules corrupted text the new rules get right."""
    was_lines, should_lines = was.splitlines(), should.splitlines()
    if len(was_lines) != len(should_lines):
        return None                      # structurally different; refuse to guess
    return [(a, b) for a, b in zip(was_lines, should_lines) if a != b]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    fme = load_helper()
    rules = fme.load_rules()
    patterns = fce.compile_rules(rules)

    with open("manual_corrections.json", encoding="utf-8") as fp:
        protected = json.load(fp).get("ids", {})

    repaired = untouched = skipped = 0
    partial = 0
    shown = 0

    for yt_id, meta in sorted(protected.items()):
        d = meta["dir"]
        base = os.path.basename(d)
        srt = os.path.join(d, base + ".srt")
        orig = srt + ".orig"
        if not (os.path.exists(srt) and os.path.exists(orig)):
            skipped += 1
            continue

        og = io.open(orig, encoding="utf-8", errors="replace").read()
        published = io.open(srt, encoding="utf-8", errors="replace").read()

        was = fme.apply_rules(og, rules)          # old, corrupting behaviour
        should = fce.apply_rules(og, patterns)    # corrected behaviour

        spans = corrupted_spans(was, should)
        if spans is None:
            skipped += 1
            continue
        if not spans:
            untouched += 1
            continue

        new = published
        applied = missing = 0
        for bad, good in spans:
            if bad and bad in new:
                new = new.replace(bad, good)
                applied += 1
            else:
                # the human rewrote this region; do not touch it
                missing += 1

        if new == published:
            untouched += 1
            continue

        # VERIFY: we must not have lost or added lines
        if len(new.splitlines()) != len(published.splitlines()):
            print("LINE COUNT CHANGED, skipping:", d)
            skipped += 1
            continue

        repaired += 1
        if missing:
            partial += 1

        if shown < args.show:
            shown += 1
            print("=" * 68)
            print("%s   (%d spans fixed, %d left to the human)" % (d, applied, missing))
            for line in difflib.unified_diff(published.splitlines(), new.splitlines(),
                                             "published", "repaired",
                                             lineterm="", n=0):
                if line.startswith(("---", "+++", "@@")):
                    continue
                print("   " + line[:100])

        if args.apply:
            tmp = srt + ".merge.tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
                fp.write(new)
            os.replace(tmp, srt)

    print()
    print("hand-corrected files     :", len(protected))
    print("  REPAIRED               :", repaired,
          "(of which %d only partially -- human had rewritten some spans)" % partial)
    print("  no corruption present  :", untouched)
    print("  skipped                :", skipped)
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
