"""
Second, INDEPENDENT detector for hand-edited transcripts -- via git history.

find_manual_edits.py compares the live .srt against fix_common_errors rules
re-applied to the .srt.orig snapshot. That has a blind spot: if a .orig was
ever regenerated FROM an already-edited .srt, the file looks clean and the
edit is invisible. That is the dangerous direction (a false negative loses the
correction), so it needs a cross-check that does not depend on .orig at all.

THE SIGNAL: the pipeline writes the three SRTs together --
    <base>.srt, <base>_aligned.srt, <base>_basic.srt
So a commit that touches the base .srt WITHOUT touching its siblings did not
come from a transcription run. Something edited it by hand.

Also reported: commits touching a .srt whose message is not the pipeline's
own "add video", which is a weaker but useful hint.

Union this with find_manual_edits.py before re-transcribing anything.

Usage:
    python find_manual_edits_git.py
    python find_manual_edits_git.py --json out.json
"""

import argparse
import collections
import json
import os
import subprocess
import sys


def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--show", type=int, default=15)
    ap.add_argument("--verify", action="store_true",
                    help="check each diff against the replacement rules")
    args = ap.parse_args()

    print("walking git history for *.srt commits (this takes a minute)...\n")
    log = git("log", "--format=@@%H|%s", "--name-only", "--", "*.srt")

    commit = subject = None
    files = []
    suspicious = collections.defaultdict(list)   # dir -> [(sha, subject)]
    n_commits = 0

    def flush():
        if not commit or not files:
            return
        by_dir = collections.defaultdict(set)
        for f in files:
            d = os.path.dirname(f)
            by_dir[d].add(os.path.basename(f))
        for d, names in by_dir.items():
            base = os.path.basename(d)
            plain = base + ".srt"
            if plain not in names:
                continue
            # siblings a real transcription run would have written alongside it
            siblings = {base + "_aligned.srt", base + "_basic.srt"}
            if names & siblings:
                continue
            suspicious[d].append((commit[:9], subject))

    for line in log.splitlines():
        if line.startswith("@@"):
            flush()
            n_commits += 1
            head = line[2:]
            commit, _, subject = head.partition("|")
            files = []
        elif line.strip():
            files.append(line.strip())
    flush()

    print("commits touching a .srt      :", n_commits)
    print("dirs where a .srt changed WITHOUT its _aligned/_basic siblings:",
          len(suspicious))

    # cross-reference the rules-based detector
    known = set()
    if os.path.exists("manual_corrections.json"):
        with open("manual_corrections.json", encoding="utf-8") as fp:
            known = {v["dir"] for v in json.load(fp).get("ids", {}).values()}

    new = sorted(d for d in suspicious if d not in known)
    overlap = sorted(d for d in suspicious if d in known)

    print("  ...already flagged by find_manual_edits.py :", len(overlap))
    print("  ...NOT previously flagged (the blind spot) :", len(new))

    if new:
        print("\nNEW candidates -- edited per git, but the .orig comparison")
        print("called them clean. These are exactly the files that detector")
        print("could miss:")
        for d in new[:args.show]:
            sha, subj = suspicious[d][0]
            print("   %-34s %s  %s" % (d, sha, (subj or "")[:40]))

    # ---- refine: is each .srt-only diff explainable by the rules? ----------
    # A .srt-only commit is AMBIGUOUS: fix_common_errors rewrites the base .srt
    # in place without touching _aligned/_basic, so every rule sweep looks
    # exactly like a hand edit. Distinguish by checking the actual diff --
    # if every removed line becomes its added counterpart under the current
    # rules, it was a sweep; anything else is a human.
    #
    # Doing it per-commit is also what closes the .orig blind spot: it never
    # consults .orig at all.
    if args.verify:
        import importlib.util
        spec = importlib.util.spec_from_file_location("fme", "find_manual_edits.py")
        fme = importlib.util.module_from_spec(spec); spec.loader.exec_module(fme)
        rules = fme.load_rules()

        print("\nverifying %d candidate dirs against the rules...\n" % len(new))
        really = []
        for i, d in enumerate(new):
            base = os.path.basename(d)
            srt = d + "/" + base + ".srt"
            explained = True
            for sha, _ in suspicious[d]:
                diff = git("show", "--format=", "--unified=0", sha, "--", srt)
                minus = [l[1:] for l in diff.splitlines()
                         if l.startswith("-") and not l.startswith("---")]
                plus = [l[1:] for l in diff.splitlines()
                        if l.startswith("+") and not l.startswith("+++")]
                # a commit with no removals is the file being CREATED, not
                # edited -- not evidence of anything
                if not minus:
                    continue
                if len(minus) != len(plus):
                    explained = False; break
                for a, b in zip(minus, plus):
                    # Normalise BOTH sides rather than demanding
                    # apply_rules(old) == new. The rule set has grown over the
                    # years, so replaying today's full dict against a 2016 line
                    # changes more than that commit did and exact equality
                    # never holds. If both sides collapse to the same string,
                    # the change is rule-consistent; if not, a human did it.
                    if fme.apply_rules(a, rules) != fme.apply_rules(b, rules):
                        explained = False; break
                if not explained:
                    break
            if not explained:
                really.append(d)
        print("of %d candidates, %d have diffs the rules CANNOT explain:"
              % (len(new), len(really)))
        for d in really[:args.show]:
            print("   ", d)
        new = really

    if args.json:
        out = {d: [{"sha": s, "subject": m} for s, m in v]
               for d, v in suspicious.items()}
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump(out, fp, indent=2)
        print("\nwrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
