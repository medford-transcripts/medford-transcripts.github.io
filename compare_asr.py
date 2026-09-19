"""
Compare YouTube's auto-captions against WhisperX on the same meeting audio.

WHAT THIS CAN AND CANNOT TELL YOU. There is no verbatim ground truth for this
meeting, so this CANNOT produce a word error rate for either system. What it
produces is:

  1. DISAGREEMENT RATE -- the share of words where the two systems differ.
     Every disagreement means at least one is wrong, so this is a LOWER BOUND
     on the combined error rate and an upper bound on neither. Where both are
     wrong the same way (a name neither has heard), it counts as agreement.

  2. PROPER-NOUN ACCURACY -- a real, checkable error rate on the subclass that
     matters most for a civic archive. We independently know how Medford's
     officials spell their names (councilors.json), so for this subclass the
     ground truth exists without anyone transcribing anything. "Did it write
     Scarpelli or Scarbelli" is decidable; "was there an um here" is not.

FAIRNESS. WhisperX is read from .srt.orig, BEFORE fix_common_errors runs. The
comparison is raw model against raw model. Scoring the post-processed WhisperX
against raw YouTube would credit WhisperX with a rule table that could equally
be applied to YouTube's output -- the post-processing is a property of this
pipeline, not of the model.

THE OVERLAP. YouTube's captions here survive only for part of the meeting (the
document's owner edited the beginning by hand and left the rest raw), so both
sides are restricted to the time span the raw captions actually cover.

Usage:
    python compare_asr.py reference/2024-10-15_kP4iRYobyr0.human.txt \
        --srt D:/.../retranscribe_baseline/2024-10-15_kP4iRYobyr0/...srt.orig
"""

import argparse
import collections
import difflib
import io
import json
import os
import re
import sys

import srt_lines

RAW_TS = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")
WORD = re.compile(r"[a-z']+")


def youtube_captions(path):
    """[(seconds, text)] from the raw auto-caption tail of the document.

    YouTube's copy-paste layout is a bare timestamp line above each caption.
    A timestamp is MM:SS early in a video and H:MM:SS later, so both are
    accepted; guessing one format would silently drop three quarters of a
    four-hour meeting.
    """
    out = []
    cur = None
    for line in io.open(path, encoding="utf-8", errors="replace"):
        m = RAW_TS.match(line)
        if m:
            a, b, c = m.groups()
            cur = (int(a) * 3600 + int(b) * 60 + int(c)) if c else (int(a) * 60 + int(b))
            continue
        if cur is not None and line.strip():
            out.append((cur, line.strip()))
            cur = None
    return out


def whisperx_blocks(path):
    text = io.open(path, encoding="utf-8", errors="replace").read()
    return srt_lines.parse_srt(text)


def words_between(items, lo, hi, get_t, get_text):
    ws = []
    for it in items:
        t = get_t(it)
        if lo <= t <= hi:
            ws.extend(WORD.findall(get_text(it).lower()))
    return ws


def strip_speaker(s):
    return re.sub(r"^\[[^\]]*\]:\s*", "", s or "")


def name_variants(path="councilors.json"):
    """Surnames we independently know the spelling of, from the roster."""
    try:
        with io.open(path, encoding="utf-8") as fp:
            roster = json.load(fp)
    except (OSError, ValueError):
        return []
    out = set()
    for full in roster:
        parts = [p for p in re.split(r"[^A-Za-z']+", full) if len(p) > 3]
        if parts:
            out.add(parts[-1].lower())
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("--srt", required=True, help="WhisperX .srt.orig (pre-fix_common_errors)")
    ap.add_argument("--names", default="councilors.json")
    args = ap.parse_args()

    yt = youtube_captions(args.reference)
    if not yt:
        print("no raw YouTube captions found in %s" % args.reference)
        return 1
    blocks = whisperx_blocks(args.srt)

    lo = min(t for t, _ in yt)
    hi = max(t for t, _ in yt)
    print("raw YouTube caption lines : %d" % len(yt))
    print("overlap window            : %d:%02d:%02d -> %d:%02d:%02d (%.1f h)"
          % (lo // 3600, lo % 3600 // 60, lo % 60,
             hi // 3600, hi % 3600 // 60, hi % 60, (hi - lo) / 3600.0))

    yw = words_between(yt, lo, hi, lambda i: i[0], lambda i: i[1])
    ww = words_between(blocks, lo, hi, lambda b: b["start"],
                       lambda b: strip_speaker(b["text"]))
    print("words in window -- YouTube: %d   WhisperX: %d   (%+.1f%%)"
          % (len(yw), len(ww), 100.0 * (len(ww) - len(yw)) / max(len(yw), 1)))
    print()

    sm = difflib.SequenceMatcher(None, yw, ww, autojunk=False)
    same = sum(b.size for b in sm.get_matching_blocks())
    total = max(len(yw), len(ww))
    print("WORD-LEVEL AGREEMENT between the two systems")
    print("  words identical in sequence : %d" % same)
    print("  DISAGREEMENT RATE           : %.1f%%" % (100.0 * (total - same) / total))
    print("  (a lower bound on combined error: where both err alike, it counts as agreement)")
    print()

    names = name_variants(args.names)
    if not names:
        print("no roster names available; skipping proper-noun check")
        return 0

    ytext = " ".join(yw)
    wtext = " ".join(ww)
    print("PROPER-NOUN ACCURACY -- names whose spelling we know independently")
    print("  %-16s %9s %9s" % ("surname", "YouTube", "WhisperX"))
    ty = tw = 0
    for n in names:
        cy = len(re.findall(r"\b%s\b" % re.escape(n), ytext))
        cw = len(re.findall(r"\b%s\b" % re.escape(n), wtext))
        if cy or cw:
            print("  %-16s %9d %9d" % (n, cy, cw))
            ty += cy
            tw += cw
    print("  %-16s %9d %9d" % ("TOTAL correct", ty, tw))
    print()
    print("  Counts are correct RENDERINGS, not opportunities -- neither system")
    print("  tells us how many times a name was actually said. The comparison is")
    print("  between the two columns, on identical audio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
