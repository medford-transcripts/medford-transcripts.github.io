"""Identify speakers from what the transcript SAYS, not from how they sound.

WHY. Within one meeting the diarizer already separates confirmed speakers at
98-100% purity, so the corpus-wide label contamination came from cross-meeting
embedding matching, not diarization. And two failures no diarizer can fix are
fixable here: a 0.3-second "Present." carries almost no speaker information, and
492 of the 1,229 named speakers in this corpus appear in exactly ONE meeting, so
they have no cross-meeting voice match by construction. Their own words are the
only route to a name. See plan.txt 12.12 for the measurements behind all of this.

THE ONE RULE THAT MAKES THIS WORK: match against a CLOSED candidate set. Open
vocabulary name extraction from ASR text does not work -- measured at 95.7%
disagreement, inventing 29,342 "distinct speakers" in a city whose meetings have
1,229 named speakers in total. Accuracy as a function of candidate-set size, on
2,260 ground-truth cases:

        2 candidates   81.1% correct   0.0% wrong
       30 candidates   80.9% correct   1.2% wrong
    1,229 candidates   64.8% correct  29.6% wrong

Correctness barely moves; the error rate explodes. Keep the set small.

AND EDIT DISTANCE BEATS PHONETICS, which was a surprise. The mutilation is
TRUNCATION, not sound-alike substitution ("Jocelyn Mc" for Jocelyn McCarthy,
"Mullay" for Mullane), and cutting a surname short changes its consonant
skeleton, so soundex breaks exactly where it is needed: "Mc" codes M200 against
McCarthy's M263. partial_ratio scores that pair at 100. Soundex is kept only as
a tie-breaker.

    python identify_from_text.py --self-test   # pattern assertions, no corpus
    python identify_from_text.py --evaluate    # score against known labels
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import sys

from rapidfuzz import fuzz, process

import utils

# ---------------------------------------------------------------------------
# patterns
#
# EVERY PATTERN IS UNIT-TESTED IN self_test() AND THAT GATE RUNS BEFORE ANY
# CORPUS PASS. Four of five measurement attempts on 2026-09-29 failed silently
# and looked credible: a per-line search that missed introductions spanning
# blocks, a required trigger phrase that missed the dominant bare form, an
# open-vocabulary match that was 95.7% wrong, and a literal BACKSPACE byte
# (0x08) written into a regex by a mangled escape -- invisible to grep, an
# editor and a diff, found only with `cat -A`, after three runs reported
# honest-looking zeros. Assertions on literal strings catch all of that in
# under a second.

# Continuation words allow INTERNAL CAPITALS, which the first draft did not:
# [a-z'\-] cannot match the "V" after the hyphen, so "Marice Edouard-Vincent"
# truncated to "Marice Edouard-" -- the same truncation this module exists to
# repair, introduced by its own pattern. Also needed for McCarthy and O'Brien.
# The FIRST word stays simple; loosening it invites acronyms and sentence starts.
NAME = r"([A-Z][a-z]+(?:\s+[A-Z][A-Za-z'\-]+){1,2})"

# The trigger must be case-insensitive (an introduction starts a sentence) while
# the NAME must not (re.I on the whole pattern lets NAME match ordinary
# lowercase words, which is how the open-vocabulary attempt invented thousands
# of speakers). Scoped inline flag does exactly that.
SELF_INTRO = re.compile(r"(?i:my name is|my name's|i'm|i am|this is)" + r"\s+" + NAME)

# A name on a line by itself, or with an honorific -- the roll call and the
# chair calling on someone.
NAME_ONLY = re.compile(r"^(?:And\s+)?" + NAME + r"\s*[.?,]?$")

# A BARE SURNAME IS ONLY SAFE BEHIND AN HONORIFIC. NAME requires two or more
# words on purpose: allowing one would make NAME_ONLY match any capitalised word
# alone on a line ("Yes.", "Okay."). But "Councilor Caraviello" is the normal
# form of a call-on, so the honorific does the disambiguating and one word is
# fine here. Caught by self_test() -- HONORIFIC originally reused NAME and
# therefore never matched the commonest phrasing in the corpus.
SURNAME = r"([A-Z][a-z]+(?:\s+[A-Z][A-Za-z'\-]+){0,2})"
HONORIFIC = re.compile(r"^(?:councilor|councillor|member|mr\.?|mrs\.?|ms\.?|dr\.?|chair|"
                       r"president|superintendent|director|chief)\s+" + SURNAME +
                       r"\s*[?:.]?$", re.I)
ASSENT = re.compile(r"^(here|yes|present|aye|no|i'm here|yep|absent)\b", re.I)

SPK_LINE = re.compile(r"^\[([^\]]+)\]:\s*(.*)$")

SOUNDEX_MAP = {}
for _chars, _code in (("BFPV", "1"), ("CGJKQSXZ", "2"), ("DT", "3"),
                      ("L", "4"), ("MN", "5"), ("R", "6")):
    for _c in _chars:
        SOUNDEX_MAP[_c] = _code


def soundex(word):
    w = re.sub(r"[^A-Za-z]", "", word or "").upper()
    if not w:
        return ""
    out, last = w[0], SOUNDEX_MAP.get(w[0], "")
    for ch in w[1:]:
        code = SOUNDEX_MAP.get(ch, "")
        if code and code != last:
            out += code
        if ch not in "HW":
            last = code
    return (out + "000")[:4]


# ---------------------------------------------------------------------------
# confidence tiers, mirroring the provenance scheme already in the repo
#
# Measured wrong-answer rates on 2,260 ground-truth cases at a realistic
# candidate-set size. A cue-derived name must OUTRANK an embedding match, which
# is the ordering whose absence let one spurious voice match spread to 800
# clusters.
TIER_EXACT = ("backfill_high_confidence", 100)     # 0.5% wrong
TIER_FUZZY = ("embedding_match", 80)               # 2.9% wrong, overwritable


def is_named(value):
    s = str(value or "")
    return bool(s) and " " in s and not s.startswith("SPEAKER_") \
        and "_SPEAKER_" not in s and s != "Unidentified"


def turns(srt_text):
    """[(speaker_key, [line, ...])] with consecutive blocks from one speaker joined.

    JOINING MATTERS: an introduction is split across SRT blocks ("My name is
    Jane Smith." / "I live at 12 Elm Street."), so a per-line search found
    name-and-address together 42 times across 2,300 meetings instead of 364.
    """
    seq = []
    for block in re.split(r"\n\s*\n", srt_text):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        m = SPK_LINE.match(lines[-1])
        if m:
            seq.append((m.group(1), m.group(2).strip()))
    out = []
    for spk, text in seq:
        if out and out[-1][0] == spk:
            out[-1][1].append(text)
        else:
            out.append((spk, [text]))
    return out, seq


def cues_in(srt_text):
    """Yield (speaker_key, stated_name, cue) for every identity cue found."""
    turn_list, seq = turns(srt_text)

    # 1. self-introduction, in the OPENING of a turn only. People introduce
    #    themselves when they start speaking; searching the whole turn matches
    #    them naming somebody else later.
    for spk, parts in turn_list:
        m = SELF_INTRO.search(" ".join(parts[:2]))
        if m:
            yield spk, m.group(1).strip(), "self_introduction"

    # 2. a name called out, then a different speaker answers. This is the roll
    #    call and the chair calling on a member.
    for i, (spk, text) in enumerate(seq):
        m = NAME_ONLY.match(text) or HONORIFIC.match(text)
        if not m:
            continue
        for spk2, text2 in seq[i + 1:i + 2]:
            if spk2 == spk:
                continue
            cue = "roll_call" if ASSENT.match(text2) else "called_on"
            yield spk2, m.group(1).strip(), cue


def match(stated, candidates):
    """(name, tier, score, method) or None. Closed set only -- never open."""
    if not stated or not candidates:
        return None
    for c in candidates:
        if c.lower() == stated.lower():
            return c, TIER_EXACT[0], 100, "exact"
    r = process.extractOne(stated, candidates, scorer=fuzz.partial_ratio,
                           score_cutoff=TIER_FUZZY[1])
    if r:
        return r[0], TIER_FUZZY[0], int(r[1]), "partial_ratio"
    # last resort: phonetic surname, and only when it is UNAMBIGUOUS. Soundex
    # alone was 6.9% wrong against 2.9% for partial_ratio, so it never overrides.
    key = soundex(stated.split()[-1])
    hits = [c for c in candidates if soundex(c.split()[-1]) == key]
    if len(hits) == 1:
        return hits[0], TIER_FUZZY[0], 0, "soundex"
    return None


def self_test():
    """Assertions on literal strings. Runs before any corpus pass."""
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (label, got, want))

    # self-introduction: trigger is mid-turn, not at position zero
    check("intro after thanks",
          (SELF_INTRO.search("Thank you, Mr. President. My name is Jane Smith.") or [None])
          and SELF_INTRO.search("Thank you, Mr. President. My name is Jane Smith.").group(1),
          "Jane Smith")
    check("intro lowercase trigger",
          SELF_INTRO.search("yes hi, my name is Robert Van Dyke").group(1), "Robert Van Dyke")
    check("intro I am",
          SELF_INTRO.search("I am Marice Edouard-Vincent, superintendent.").group(1),
          "Marice Edouard-Vincent")
    # must NOT fire on ordinary speech
    check("no intro in ordinary speech",
          SELF_INTRO.search("I am very concerned about the 40 Mystic Avenue project"), None)

    # roll call / called on
    check("name only", NAME_ONLY.match("Michael Marks.").group(1), "Michael Marks")
    check("honorific", HONORIFIC.match("Councilor Caraviello?").group(1), "Caraviello")
    check("not a name line", NAME_ONLY.match("I support the motion."), None)
    check("assent", bool(ASSENT.match("Present.")), True)

    # soundex: wins the textbook case, loses on truncation -- documented, not a bug
    check("soundex Smyth/Smith", soundex("Smyth") == soundex("Smith"), True)
    check("soundex truncation fails", soundex("Mc") == soundex("McCarthy"), False)

    # closed-set matching
    cands = ["Jocelyn McCarthy", "Michael Marks", "Zac Bears"]
    check("exact wins", match("Michael Marks", cands)[0], "Michael Marks")
    check("truncation via partial", match("Jocelyn Mc", cands)[0], "Jocelyn McCarthy")
    check("garbled declines", match("Yutori Arashi", cands), None)
    check("empty declines", match("", cands), None)

    # THE BACKSPACE GUARD: a control character in a pattern is invisible and
    # silently matches nothing. Check the patterns are printable.
    for nm, pat in (("SELF_INTRO", SELF_INTRO), ("NAME_ONLY", NAME_ONLY),
                    ("HONORIFIC", HONORIFIC), ("ASSENT", ASSENT)):
        bad = [c for c in pat.pattern if ord(c) < 32]
        if bad:
            fails.append("%s contains control character(s) %r" % (nm, bad))

    for f in fails:
        print("  FAIL %s" % f)
    print("self-test: %d checks, %d failed" % (14 + 4, len(fails)))
    return 1 if fails else 0


def candidates_for(meeting_dir, ids, roster):
    """The closed set: names already known in this meeting, plus the roster.

    Deliberately small. Once the registry of 12.3 exists this becomes "people
    whose term covers this meeting's date", which is smaller still and is the
    single biggest lever on the error rate.
    """
    here = {str(v) for v in ids.values() if is_named(v)}
    return sorted(here | set(roster))


def evaluate(limit=0):
    """Score cues against clusters a human already named -- free ground truth."""
    vd = utils.get_video_data()
    roster = []
    try:
        roster = [str(n) for n in json.load(io.open("councilors.json", encoding="utf-8"))]
    except Exception:
        pass

    per_cue = collections.defaultdict(collections.Counter)
    n_meetings = 0
    for p in sorted(glob.glob("*/20??-??-??_*.srt")):
        d = os.path.dirname(p)
        yt = d.split("_", 1)[1]
        e = vd.get(yt) or {}
        if e.get("skip"):
            continue
        try:
            ids = json.load(io.open(os.path.join(d, "speaker_ids.json"), encoding="utf-8"))
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        n_meetings += 1
        cands = candidates_for(d, ids, roster)
        for spk, stated, cue in cues_in(txt):
            truth = str(ids.get(spk) or "")
            if not is_named(truth):
                per_cue[cue]["unnamed_cluster"] += 1
                continue
            got = match(stated, cands)
            if got is None:
                per_cue[cue]["declined"] += 1
            elif got[0].lower() == truth.lower():
                per_cue[cue]["correct"] += 1
                per_cue[cue]["correct_" + got[1]] += 1
            else:
                per_cue[cue]["wrong"] += 1
                per_cue[cue]["wrong_" + got[1]] += 1
        if limit and n_meetings >= limit:
            break

    print("meetings scanned: %s" % format(n_meetings, ","))
    print()
    print("%-18s %8s %8s %8s %9s %10s" % ("cue", "correct", "wrong", "declined",
                                          "accuracy", "unnamed"))
    for cue in sorted(per_cue):
        c = per_cue[cue]
        judged = c["correct"] + c["wrong"] + c["declined"]
        acc = 100.0 * c["correct"] / judged if judged else 0.0
        err = 100.0 * c["wrong"] / judged if judged else 0.0
        print("%-18s %8d %8d %8d %8.1f%% %10d" % (cue, c["correct"], c["wrong"],
                                                  c["declined"], acc, c["unnamed_cluster"]))
        print("%-18s   high-confidence tier: %d right / %d wrong"
              % ("", c["correct_backfill_high_confidence"], c["wrong_backfill_high_confidence"]))
        print("%-18s   fuzzy tier          : %d right / %d wrong  (err %.1f%%)"
              % ("", c["correct_embedding_match"], c["wrong_embedding_match"], err))
    print()
    print("'unnamed' counts cues landing on clusters with NO name yet -- the")
    print("identifications this would ADD. Nothing is written by --evaluate.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rc = self_test()
    if rc:
        print("REFUSING to continue: patterns failed their own tests.")
        return rc
    if args.self_test and not args.evaluate:
        return 0
    if args.evaluate:
        return evaluate(args.limit)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
