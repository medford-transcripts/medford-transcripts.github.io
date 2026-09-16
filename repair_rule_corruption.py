"""
Repair transcripts corrupted by the OLD unanchored fix_common_errors matching.

fix_common_errors used str.replace(), an unanchored substring match, so rules
meant to fix councilor names fired inside unrelated words -- including
residents' surnames:

    counselors -> Councilors   (3141)     Moxley  -> Marksley   (112)
    Nights     -> Knights      (98)       Maxwell -> Markswell  (36)
    McKernan   -> Lungo-Koehnan (23)      Beasley -> Bearsley   (15)
    Roussell   -> Ruseau       (23)       Carvell -> Caraviellol (10)

935 of 2,273 transcripts are affected. The generator is fixed (rules are now
word-boundary anchored), but published files are still wrong.

THE REPAIR IS EXACT, not a guess. For a transcript with no manual edits, the
current .srt is by definition old_rules(.srt.orig) -- that is what
find_manual_edits.py means by "clean". So writing new_rules(.srt.orig) changes
precisely the corrupted spans and nothing else.

SAFETY: every file is verified to actually satisfy current == old_rules(.orig)
before being touched. Anything that does not is SKIPPED and reported, never
overwritten -- that would mean it holds an edit this tool does not understand.

The 70 corrupted files that ALSO carry hand corrections are deliberately out of
scope here: rebuilding them from .orig would discard those edits. They need a
merge and are listed for a separate pass.

Usage:
    python repair_rule_corruption.py            # dry run
    python repair_rule_corruption.py --apply
    python repair_rule_corruption.py --show 3   # sample the diffs
"""

import argparse
import difflib
import glob
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=2)
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    fme = load_helper()
    rules = fme.load_rules()
    patterns = fce.compile_rules(rules)

    protected = set()
    if os.path.exists("manual_corrections.json"):
        with open("manual_corrections.json", encoding="utf-8") as fp:
            protected = {v["dir"] for v in json.load(fp).get("ids", {}).values()}

    dirs = sorted(d for d in glob.glob("20??-??-??_*") if os.path.isdir(d))

    repaired = clean = skipped_protected = skipped_mismatch = no_orig = 0
    shown = 0
    mismatches = []

    for d in dirs:
        base = os.path.basename(d)
        srt = os.path.join(d, base + ".srt")
        orig = srt + ".orig"
        if not os.path.exists(srt):
            continue
        if not os.path.exists(orig):
            no_orig += 1
            continue
        if d in protected:
            skipped_protected += 1
            continue

        og = io.open(orig, encoding="utf-8", errors="replace").read()
        cur = io.open(srt, encoding="utf-8", errors="replace").read()

        new = fce.apply_rules(og, patterns)
        if new == cur:
            clean += 1
            continue

        # SAFETY: the file must be exactly what the old rules produced.
        # If not, it holds something this tool does not understand -- skip it.
        if fme.apply_rules(og, rules) != cur:
            skipped_mismatch += 1
            mismatches.append(d)
            continue

        repaired += 1
        if shown < args.show:
            shown += 1
            print("=" * 68)
            print(d)
            diff = difflib.unified_diff(cur.splitlines(), new.splitlines(),
                                        "published", "repaired", lineterm="", n=0)
            for i, line in enumerate(diff):
                if line.startswith(("---", "+++", "@@")):
                    continue
                print("   " + line[:104])
                if i > 8:
                    print("   ...")
                    break

        if args.apply:
            tmp = srt + ".repair.tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
                fp.write(new)
            os.replace(tmp, srt)

    print()
    print("already correct            :", clean)
    print("REPAIRED                   :", repaired)
    print("skipped, hand-corrected    :", skipped_protected, "(need a merge, separate pass)")
    print("skipped, unexpected content:", skipped_mismatch)
    print("no .srt.orig               :", no_orig)
    if mismatches:
        print("\nunexpected content in (first 10):")
        for d in mismatches[:10]:
            print("   ", d)
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
