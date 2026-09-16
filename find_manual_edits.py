"""
Find transcripts containing MANUAL corrections, so re-transcription cannot
silently destroy them.

WHY THIS MATTERS: 364 transcripts (16%) have no model.pkl -- they predate the
pipeline saving one, or were lost. Regenerating those means RE-TRANSCRIBING
from audio, which produces a brand new .srt. Any hand corrections in the
existing .srt would be gone. Those corrections are the most valuable text in
the archive: they are ground truth, and the eventual eval set (plan.txt 6.1)
and any fine-tuning depend on them.

HOW IT WORKS: fix_common_errors copies the .srt to .srt.orig exactly ONCE, the
first time it runs, then edits the .srt in place forever after. So:

    apply(current rules, .srt.orig)  ==  .srt      -> fully explained by the
                                                      automated rules; no
                                                      manual edits
    apply(current rules, .srt.orig)  !=  .srt      -> something else changed
                                                      it: almost certainly a
                                                      hand correction

Caveat, stated honestly: a rule that was REMOVED or CHANGED since a file was
last processed also lands in the second bucket, so it over-reports rather than
under-reports. That is the safe direction -- a false positive costs a glance,
a false negative costs the correction. Files in the first bucket are
definitively safe to regenerate.

Corrections made BEFORE the first fix_common_errors run are baked into .orig
and appear in both, so they are preserved either way and are not at risk.

Usage:
    python find_manual_edits.py                 # summary
    python find_manual_edits.py --show 20       # sample the diffs
    python find_manual_edits.py --no-model      # only the at-risk 364
    python find_manual_edits.py --json out.json # machine-readable list
"""

import argparse
import ast
import difflib
import glob
import io
import json
import os
import sys


def load_rules(path="fix_common_errors.py"):
    """Pull replace_dict out of fix_common_errors without importing it.

    The dict is a local inside the function, so it cannot simply be imported;
    parsing the source avoids modifying working code just to read a constant.
    """
    tree = ast.parse(io.open(path, encoding="utf-8").read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "replace_dict":
                    return ast.literal_eval(node.value)
    raise SystemExit("could not find replace_dict in " + path)


def apply_rules(text, rules):
    for k, v in rules.items():
        if str(k) in text:
            text = text.replace(str(k), v)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0,
                    help="print a unified diff for the first N edited files")
    ap.add_argument("--no-model", action="store_true",
                    help="restrict to transcripts with no model.pkl (the at-risk set)")
    ap.add_argument("--json", help="write the edited-file list here")
    args = ap.parse_args()

    rules = load_rules()
    print("loaded %d replacement rules\n" % len(rules))

    dirs = sorted(d for d in glob.glob("20??-??-??_*") if os.path.isdir(d))

    clean = edited = no_orig = unreadable = 0
    edited_list = []
    shown = 0

    for d in dirs:
        base = os.path.basename(d)
        srt = os.path.join(d, base + ".srt")
        orig = srt + ".orig"
        if not os.path.exists(srt):
            continue
        if args.no_model and os.path.exists(os.path.join(d, "model.pkl")):
            continue
        if not os.path.exists(orig):
            no_orig += 1
            continue

        try:
            cur = io.open(srt, encoding="utf-8", errors="replace").read()
            og = io.open(orig, encoding="utf-8", errors="replace").read()
        except OSError:
            unreadable += 1
            continue

        expected = apply_rules(og, rules)
        if expected == cur:
            clean += 1
            continue

        edited += 1
        exp_lines = expected.splitlines()
        cur_lines = cur.splitlines()
        sm = difflib.SequenceMatcher(None, exp_lines, cur_lines)
        changed = sum(max(i2 - i1, j2 - j1)
                      for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
        edited_list.append({"dir": d, "changed_lines": changed,
                            "total_lines": len(cur_lines),
                            "has_model": os.path.exists(os.path.join(d, "model.pkl"))})

        if shown < args.show:
            shown += 1
            print("=" * 70)
            print(d, "--", changed, "changed lines")
            diff = difflib.unified_diff(exp_lines, cur_lines,
                                        "rules-applied", "actual", lineterm="", n=0)
            for i, line in enumerate(diff):
                if i > 14:
                    print("   ...")
                    break
                print("   " + line)

    edited_list.sort(key=lambda r: -r["changed_lines"])

    print("\n" + "=" * 70)
    print("clean (rules fully explain the file) :", clean)
    print("EDITED (manual corrections present)  :", edited)
    print("no .srt.orig to compare against      :", no_orig)
    print("unreadable                           :", unreadable)

    if edited_list:
        at_risk = [r for r in edited_list if not r["has_model"]]
        print("\nof the edited files, %d have NO model.pkl -- these are the ones"
              % len(at_risk))
        print("that would lose corrections if re-transcribed:")
        for r in at_risk[:15]:
            print("   %-32s %5d/%-5d lines changed"
                  % (r["dir"], r["changed_lines"], r["total_lines"]))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump(edited_list, fp, indent=2)
        print("\nwrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
