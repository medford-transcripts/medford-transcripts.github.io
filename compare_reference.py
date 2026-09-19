"""
Compare a human transcript against the pipeline's, and score speaker attribution.

WHAT THIS IS FOR. Nothing in this project measures whether the archive names
the right speaker. Three changes on 2026-09-19 touched attribution -- the
resolved-name paragraph grouping, the bare-surname rule conversion, the
provenance guards -- and each was verified by hand on a sample because there
was no metric. reference/ holds human transcripts; this scores against them.

WHAT THE REFERENCE IS AND IS NOT. The 2024-10-15 document is YouTube's
auto-captions edited by a human, with FILLER WORDS REMOVED and headings added.
So:
  - it is NOT verbatim, which rules out word error rate. Scoring the pipeline
    against a reference that deleted "um" would punish it for accuracy.
  - its SPEAKER LABELS are human-assigned by someone who listened, which is
    the scarce and usable signal.
  - it is anchored on a DIFFERENT model (YouTube's, not Whisper's), so where
    the two disagree at least one is wrong and a human already adjudicated --
    the pipeline reads "please call the roll" where the reference kept
    YouTube's "please call the role".
  - it carries its own proper-noun errors: the labels say "Lemming" and
    "Castanetti" where the document's own city-staff header says "Leming" and
    "Castagnetti". A reference is evidence, not an oracle.

ALIGNMENT. The reference has no per-turn timestamps, so the two documents are
aligned by their text: 4-grams unique in BOTH become anchors, and the longest
increasing subsequence of those gives a monotone chain. Turns that the chain
does not pin down closely are reported as unmatched rather than guessed at --
a wrongly aligned turn would score a CORRECT attribution as an error, which
is the one failure mode that makes a metric worse than no metric.

Usage:
    python compare_reference.py reference/2024-10-15_kP4iRYobyr0.human.txt
"""

import argparse
import collections
import difflib
import io
import os
import re
import sys

import srt_lines
import utils

TURN = re.compile(r"^\s*\[([^\]\n]{1,40})\]\s*(.*)$")
WORD = re.compile(r"[a-z']+")
SHORT = 8          # words; below this a turn is an interjection, not a speech
STOP = set("the a an and or of to in is it that this for on with as at be by "
           "we you i they he she him her them our your my me us do does did "
           "so if then than but not no yes have has had will would can could "
           "am are was were been being there here what which who".split())


RAW_TS = re.compile(r"^\s*\d{1,2}:\d\d(:\d\d)?\s*$")
NOT_A_SPEAKER = {"music", "applause", "laughter", "inaudible", "crosstalk"}


def read_reference(path):
    """[(speaker, text)] from the HUMAN-EDITED prefix of the document.

    The owner confirmed the editing stops partway and "the end of this file
    might be raw YouTube (uncorrected)". It does, at line 297: after that the
    document is unedited auto-captions in YouTube's own layout -- a bare
    H:MM:SS line above each caption, lowercase, with its errors intact
    ("councelor", "Mr cler"). Those carry NO speaker labels, so the [Music]
    and [Applause] tags down there are YouTube's sound tags, not turns.

    Scoring past the cutoff would be scoring against another ASR's raw output
    while calling it human ground truth. So: stop at the first raw timestamp
    line, and drop sound tags.
    """
    turns = []
    for line in io.open(path, encoding="utf-8", errors="replace"):
        if RAW_TS.match(line):
            break
        m = TURN.match(line)
        if m and m.group(2).strip():
            who = m.group(1).strip()
            if who.lower().strip(" .:") in NOT_A_SPEAKER:
                continue
            turns.append((who, m.group(2).strip()))
    return turns


QUALIFIER = re.compile(r"\s+(?:on|at|in|via|from|over)\s+.*$", re.I)


def surname(name):
    """Last alphabetic token, lowercased -- the comparable part of a label.

    The reference writes "Bears", "City Clerk Hurtubise" and "Hurtubise" for
    the same two people; the pipeline writes "Zac Bears" and "Adam Hurtubise".

    It also annotates where the person was -- "Castanetti on the podium",
    "Berkson on zoom" -- so the trailing qualifier is stripped first. Without
    that, the surname is "podium" and two correct attributions score as
    errors.
    """
    parts = [p for p in re.split(r"[^A-Za-z]+", QUALIFIER.sub("", name or "")) if p]
    return parts[-1].lower() if parts else ""


def same_person(a, b, threshold=0.82):
    """Surname match, tolerant of the reference's own spelling errors."""
    sa, sb = surname(a), surname(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    return difflib.SequenceMatcher(None, sa, sb).ratio() >= threshold


def stream(words):
    """Positions of every 4-gram that occurs exactly once in `words`."""
    seen = {}
    for i in range(len(words) - 3):
        g = (words[i], words[i + 1], words[i + 2], words[i + 3])
        seen[g] = i if g not in seen else -1
    return {g: i for g, i in seen.items() if i >= 0}


def anchors(ref_words, srt_words):
    """Monotone (ref_index, srt_index) chain tying the two transcripts together.

    Patience alignment: take the 4-grams that are UNIQUE in both documents --
    those cannot be matched ambiguously -- then keep the longest increasing
    subsequence of their pairings. This survives the reference's deleted
    filler words and its different ASR wording, because it needs only that
    SOME distinctive phrases survived intact; the earlier first-few-words
    matcher needed every turn to start recognisably, and 111 of 131 did not.
    """
    a, b = stream(ref_words), stream(srt_words)
    common = sorted((a[g], b[g]) for g in a if g in b)
    if not common:
        return []
    # longest increasing subsequence on the srt index
    import bisect
    tails, back, idx = [], [None] * len(common), []
    for n, (_, y) in enumerate(common):
        k = bisect.bisect_left(tails, y)
        if k == len(tails):
            tails.append(y)
            idx.append(n)
        else:
            tails[k] = y
            idx[k] = n
        back[n] = idx[k - 1] if k else None
    chain, n = [], idx[-1]
    while n is not None:
        chain.append(common[n])
        n = back[n]
    chain.reverse()
    return chain


def turn_anchors(chain, lo, hi):
    """Every anchor's SRT index for a reference turn spanning ref words [lo, hi).

    Uses only anchors that fall INSIDE the turn, and takes the anchor's own
    matched position -- no interpolation. Interpolating by word offset was
    wrong by a whole turn in both directions, because the reference is not a
    parallel text: it covers about 8% of the meeting's words (much of it is
    narration, "Councilor Scarpelli asked that...", rather than quotation), so
    equal word offsets in the two documents mean completely different places.

    All the turn's anchors are returned, not just the first, because the
    caller scores a turn by its MAJORITY speaker. Taking the first anchor made
    a 4-word slip look like a 135-word error: Scarpelli's long speech was
    attributed correctly throughout, but his courtesy opener ("Thank you for
    the question") had been absorbed into the previous speaker's turn, and
    that opener is where the first anchor lands.

    A turn too short to contain a unique 4-gram ("Present.") yields no anchor
    and is reported unmatched. That is the right answer: the roll call is
    where attribution matters most and is exactly where a guess would be
    least defensible.
    """
    import bisect
    xs = [c[0] for c in chain]
    k = bisect.bisect_left(xs, lo)
    out = []
    while k < len(chain) and chain[k][0] < hi:
        out.append(chain[k][1])
        k += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    yt_id = os.path.basename(args.reference).split("_")[1].split(".")[0]
    video_data = utils.get_video_data()
    entry = video_data.get(yt_id)
    if not entry:
        print("no video_data entry for %s" % yt_id)
        return 1
    base = (entry.get("upload_date") or "") + "_" + yt_id
    srt_path = os.path.join(base, base + ".srt")
    if not os.path.exists(srt_path):
        print("no transcript at %s" % srt_path)
        return 1

    blocks = srt_lines.parse_srt(io.open(srt_path, encoding="utf-8", errors="replace").read())
    names = {}
    ids_path = os.path.join(base, "speaker_ids.json")
    if os.path.exists(ids_path):
        import json
        names = json.load(io.open(ids_path, encoding="utf-8"))

    # flat word stream with the speaker for each word
    srt_words, srt_speaker = [], []
    for b in blocks:
        who = names.get(b["speaker"], b["speaker"])
        for w in WORD.findall((b["text"] or "").lower()):
            srt_words.append(w)
            srt_speaker.append(who)

    turns = read_reference(args.reference)

    # reference word stream, remembering which turn each word came from
    ref_words, ref_turn = [], []
    for n, (_, text) in enumerate(turns):
        for w in WORD.findall(text.lower()):
            ref_words.append(w)
            ref_turn.append(n)

    chain = anchors(ref_words, srt_words)

    print("reference turns   : %d  (%d words)" % (len(turns), len(ref_words)))
    print("pipeline blocks   : %d  (%d words)" % (len(blocks), len(srt_words)))
    print("pipeline speakers : %d labels, %d named"
          % (len(names), sum(1 for n in names.values()
                             if n and not n.startswith("SPEAKER_") and "_SPEAKER_" not in n)))
    print("alignment anchors : %d unique 4-grams in both" % len(chain))
    print()

    # [start, end) reference word span of each turn
    span = {}
    for i, n in enumerate(ref_turn):
        if n not in span:
            span[n] = [i, i + 1]
        else:
            span[n][1] = i + 1

    agree = disagree = unmatched = unnamed = 0
    mismatches, spelling = [], []
    by_len = {True: [0, 0], False: [0, 0]}   # short? -> [agree, disagree]
    for n, (ref_name, text) in enumerate(turns):
        if n not in span:
            unmatched += 1
            continue
        hits = [a for a in turn_anchors(chain, span[n][0], span[n][1])
                if 0 <= a < len(srt_speaker)]
        if not hits:
            unmatched += 1
            continue
        tally = collections.Counter(srt_speaker[a] for a in hits)
        got, _ = tally.most_common(1)[0]
        if not got or got.startswith("SPEAKER_") or "_SPEAKER_" in got:
            unnamed += 1
            continue
        nwords = span[n][1] - span[n][0]
        if same_person(ref_name, got):
            agree += 1
            by_len[nwords < SHORT][0] += 1
            if surname(ref_name) != surname(got):
                spelling.append((ref_name, got, text[:58]))
        else:
            disagree += 1
            by_len[nwords < SHORT][1] += 1
            mismatches.append((nwords, ref_name, got, text[:58]))

    scored = agree + disagree
    print("turns located in the transcript : %d" % (len(turns) - unmatched))
    print("  could not be located          : %d" % unmatched)
    print("  pipeline speaker still unnamed: %d" % unnamed)
    print()
    print("SPEAKER ATTRIBUTION over %d scored turns" % scored)
    print("  agrees with the human    : %d (%.1f%%)" % (agree, 100.0 * agree / max(scored, 1)))
    print("  disagrees                : %d" % disagree)
    print()
    print("  BY TURN LENGTH -- short turns are where diarization fails:")
    for short in (True, False):
        a, d = by_len[short]
        if a + d:
            print("    %-18s %3d turns, %5.1f%% agree"
                  % ("under %d words" % SHORT if short else "%d words or more" % SHORT,
                     a + d, 100.0 * a / (a + d)))

    if spelling:
        print()
        print("  SAME PERSON, NAME SPELLED DIFFERENTLY (check which is right):")
        for ref_name, got, text in spelling:
            print("    human %-22s archive %-22s %s" % (ref_name, got, text))

    if mismatches:
        print()
        print("  disagreements, shortest first (short = likely absorbed interjection):")
        for nwords, ref_name, got, text in sorted(mismatches)[:args.show]:
            print("    %3dw  human %-20s pipeline %-20s %s" % (nwords, ref_name, got, text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
