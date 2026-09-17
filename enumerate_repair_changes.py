"""
Enumerate every distinct substitution the corruption repair would make.

WHY THIS IS A GATE, not a formality. The repair is NOT uniformly correct, and
the two directions look identical to any rule:

    Mox  inside "Moxley"  -> "Marksley"   HARMFUL: Moxley is a real, different
                                          person, and we misnamed them
    Sang inside "Sangin"  -> "Tsengin"    HELPFUL: "Sangin" is itself a
                                          mis-hearing of "Tseng and", so the
                                          old behaviour got the right councilor

Whether the longer word is a legitimate different word or another
mis-transcription is knowledge, not something word boundaries can decide.
Blanket-applying the repair would trade one set of misattributed names for
another. So: enumerate the substitutions, have a human vet them, apply only
what is approved.

A third bucket matters too: cases where NEITHER version is right ("Sangin" and
"Tsengin" are both wrong; the answer is "Tseng and"). Those want a NEW rule,
and this report is where they surface.

Output is a vetting worksheet: every change type, how often it occurs, and a
real sentence showing the context.

    python enumerate_repair_changes.py
    python enumerate_repair_changes.py --json changes.json
"""

import argparse
import collections
import glob
import importlib.util
import io
import json
import os
import re
import sys

import fix_common_errors as fce


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--limit", type=int, default=0, help="stop after N files")
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location("fme", "find_manual_edits.py")
    fme = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fme)
    rules = fme.load_rules()
    patterns = fce.compile_rules(rules)

    # one alternation to skip lines no rule could possibly touch -- without
    # this the run is ~330 regex passes over every line of 2,200 files
    prefilter = re.compile("|".join(sorted((re.escape(k) for k in rules),
                                           key=len, reverse=True)))

    protected = set()
    if os.path.exists("manual_corrections.json"):
        with open("manual_corrections.json", encoding="utf-8") as fp:
            protected = {v["dir"] for v in json.load(fp).get("ids", {}).values()}

    counts = collections.Counter()
    examples = {}
    files_touched = 0
    examined = 0

    dirs = sorted(d for d in glob.glob("20??-??-??_*") if os.path.isdir(d))
    for d in dirs:
        if d in protected:
            continue
        base = os.path.basename(d)
        srt = os.path.join(d, base + ".srt")
        orig = srt + ".orig"
        if not (os.path.exists(srt) and os.path.exists(orig)):
            continue
        examined += 1
        if args.limit and examined > args.limit:
            break

        touched = False
        with io.open(orig, encoding="utf-8", errors="replace") as fp:
            for line in fp:
                if not prefilter.search(line):
                    continue
                was = fme.apply_rules(line, rules)       # what got published
                should = fce.apply_rules(line, patterns)  # what repair writes
                if was == should:
                    continue
                touched = True
                w, s = was.split(), should.split()
                if len(w) != len(s):
                    continue
                for a, b in zip(w, s):
                    if a == b:
                        continue
                    key = (a.strip(".,?!:;"), b.strip(".,?!:;"))
                    counts[key] += 1
                    if key not in examples:
                        examples[key] = was.strip()[:150]
        if touched:
            files_touched += 1
        if examined % 300 == 0:
            print("  ...%d files, %d change types so far"
                  % (examined, len(counts)), flush=True)

    print("\nfiles examined      :", examined)
    print("files repair touches:", files_touched)
    print("distinct changes    :", len(counts))
    print("\n" + "=" * 74)
    print("VETTING WORKSHEET -- published -> what the repair would write")
    print("=" * 74)
    for (was, should), n in counts.most_common():
        print("\n%6d  %-26s -> %s" % (n, was, should))
        print("        e.g. %s" % examples[(was, should)])

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump([{"published": a, "repaired": b, "count": n,
                        "example": examples[(a, b)]}
                       for (a, b), n in counts.most_common()], fp, indent=2)
        print("\nwrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
