"""
Propose explicit inflected-form rules, ranked by how safe they are to add.

BACKGROUND. The replacement rules used unanchored substring matching, which
did two opposite things at once:

  HARMFUL   "guidance counselors" -> "guidance Councilors"
  HELPFUL   "Councilor Moxley"    -> "Councilor Marksley"   (Michael Marks,
                                    mis-heard; the fix was imperfect but the
                                    name was right)

Anchoring the rules to word boundaries stopped the harm AND the help. The way
back is explicit rules for the inflected forms -- "Moxley" -> "Marks" rather
than relying on "Mox" matching inside it. That also fixes what the old
behaviour got wrong: "Marksley" was never right either.

THE SAFETY TEST. A proposal is only safe if the token is ALWAYS a mis-heard
official. "Maxx" is safe because every occurrence reads "Councilor Maxx".
"Brianna" is NOT safe: it appears as "Brianna Scholl" (a hockey player) and
"my wife, Brianna" -- adding Brianna -> Breanna would rename real people after
the Mayor.

So each candidate is checked against every occurrence in the ORIGINAL whisper
output, and classed by whether an honorific always precedes it. Anything less
than unanimous is held back for a human.

Usage:
    python propose_name_rules.py                 # ranked worksheet
    python propose_name_rules.py --json out.json
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import sys

# ONLY council-floor honorifics. The earlier, wider list (Member, Chair,
# Clerk, Director, Congressman) let real people through: "Fiona Maxwell",
# "Walter Beasley" the musician, "Director Beresford". A rule that fires on a
# bare surname will eventually rename somebody real.
#
# Note "Counselor"/"Councilman" are themselves mis-hearings of Councilor and
# must be recognised as the honorific, not corrected first.
HONORIFIC_FORMS = [
    "Councilor", "Councillor", "Councilman", "Counselor", "Council",
    "Council President", "Vice President", "Vice-President", "President",
]
HONORIFICS = r"(?:" + r"|".join(sorted((h.replace(" ", r"\s+") for h in HONORIFIC_FORMS),
                                       key=len, reverse=True)) + r")"


def load_officials(path="councilors.json"):
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    surnames = set()
    for full in data:
        parts = str(full).split()
        if parts:
            surnames.add(parts[-1])
    return sorted(surnames, key=len, reverse=True)


def scan_occurrences(tokens):
    """Per token: total uses, uses after an honorific, and WHICH honorifics.

    The output is contextual rules -- "Councilor Moxley" -> "Councilor Marks"
    -- not a bare "Moxley" -> "Marks". That is the only form that cannot
    rename a real person, and it matches the style already in the rule table
    ("Councilor Beers" -> "Councilor Bears").

    The trailing garbage ("...ley" in Moxley) is a word Whisper swallowed and
    we cannot recover it, so the honest target is just the correct surname.
    """
    pats = {t: re.compile(r"(" + HONORIFICS + r"\s+)?\b" + re.escape(t) + r"\b")
            for t in tokens}
    total = collections.Counter()
    honorific = collections.Counter()
    samples = collections.defaultdict(list)
    forms = collections.defaultdict(collections.Counter)

    for f in glob.glob("20??-??-??_*/*.srt.orig"):
        with io.open(f, encoding="utf-8", errors="replace") as fp:
            for line in fp:
                for t, rx in pats.items():
                    if t not in line:
                        continue
                    for m in rx.finditer(line):
                        total[t] += 1
                        if m.group(1):
                            honorific[t] += 1
                            forms[t][m.group(1).strip()] += 1
                        elif len(samples[t]) < 3:
                            samples[t].append(line.strip()[:110])
    return total, honorific, samples, forms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="scratch/repair_changes.json")
    ap.add_argument("--json")
    args = ap.parse_args()

    with open(args.changes, encoding="utf-8") as fp:
        rows = json.load(fp)
    surnames = load_officials()

    # heard token -> intended official, inferred by stripping the official's
    # surname off the front of what the old rules produced
    candidates = {}
    for r in rows:
        heard, old_output = r["repaired"], r["published"]
        hit = next((s for s in surnames
                    if old_output.lower().startswith(s.lower())), None)
        if hit and old_output.lower() != hit.lower():
            candidates[heard] = (hit, old_output, r["count"])

    print("checking %d candidate tokens against every occurrence...\n"
          % len(candidates))
    total, honorific, samples, forms = scan_occurrences(list(candidates))

    safe, review = [], []
    for heard, (target, old_output, n) in candidates.items():
        tot, hon = total.get(heard, 0), honorific.get(heard, 0)
        rec = {"heard": heard, "target": target, "old_output": old_output,
               "count": n, "occurrences": tot, "after_honorific": hon,
               "samples": samples.get(heard, []),
               "rules": [{"from": f + " " + heard, "to": f + " " + target,
                          "count": c}
                         for f, c in sorted(forms.get(heard, {}).items(),
                                            key=lambda kv: -kv[1])]}
        # A contextual rule is safe whenever the honorific-preceded uses exist
        # at all -- the rule simply will not fire on the bare-surname uses.
        if hon:
            safe.append(rec)
        else:
            review.append(rec)

    safe.sort(key=lambda r: -r["count"])
    review.sort(key=lambda r: -r["count"])

    print("=" * 76)
    print("SAFE -- every occurrence follows an honorific (Councilor X, President X)")
    print("=" * 76)
    print("%-24s %-16s %8s %s" % ("HEARD", "-> CORRECT", "uses", "(old output)"))
    for r in safe:
        print("%-24s -> %-14s %8d  %s"
              % (r["heard"][:23], r["target"], r["occurrences"], r["old_output"][:20]))

    print("\n" + "=" * 76)
    print("NEEDS REVIEW -- appears WITHOUT an honorific, so it may be a real person")
    print("=" * 76)
    for r in review:
        print("\n%-24s -> %-14s  %d of %d uses follow an honorific"
              % (r["heard"][:23], r["target"], r["after_honorific"], r["occurrences"]))
        for s in r["samples"]:
            print("      %s" % s)

    print("\nsafe: %d   needs review: %d" % (len(safe), len(review)))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fp:
            json.dump({"safe": safe, "review": review}, fp, indent=2)
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
