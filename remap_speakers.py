"""
Carry speaker NAMES across a re-transcription, by matching old labels to new
ones on shared audio time.

WHY THIS IS NEEDED. Diarization is not deterministic. Re-transcribing
2024-10-15_kP4iRYobyr0 on 2026-09-20 produced 47 labels where there had been
46, and SPEAKER_07 changed from Zac Bears to Adam Hurtubise. Anything keyed to
the old numbering -- voices_folder/<yt_id>_SPEAKER_nn.pkl, a cross-video
cluster reference in another meeting's speaker_ids.json -- silently means
something else afterwards. The naming also regressed: 45 of 46 labels were
named before, 37 of 47 after, because the fresh run re-derived names without
the accumulated manual work.

WHY TIME AND NOT EMBEDDINGS. Both runs describe the SAME audio, so the honest
question is "who was speaking between 1204.3 and 1211.8 seconds", and both
files answer it directly. Matching by voice embedding would re-run the
comparison that produced the disagreement in the first place, and would be
limited by embedding quality; overlap is measured, not inferred. Embedding
similarity is a reasonable cross-check, never the primary key.

WHAT IT WILL NOT DO. It only fills labels the new run left UNNAMED. A name the
new run derived is left alone: this is for recovering work that was lost, not
for overriding a fresh decision with a stale one. Every proposed change is
printed with the fraction of the new label's speech the old label accounts
for, and anything below --min-overlap is reported and skipped rather than
guessed at.

Usage:
    python remap_speakers.py --old <dir-or-srt> --new <dir> [--apply]
"""

import argparse
import collections
import io
import json
import os
import sys

import srt_lines


def spans(srt_path):
    """{label: [(start, end), ...]} from an SRT carrying [SPEAKER_nn] labels."""
    text = io.open(srt_path, encoding="utf-8", errors="replace").read()
    out = collections.defaultdict(list)
    for b in srt_lines.parse_srt(text):
        spk = b.get("speaker")
        if spk and b.get("end") is not None and b.get("start") is not None:
            out[spk].append((float(b["start"]), float(b["end"])))
    return out


def overlap(a, b):
    """Seconds of audio covered by both interval lists."""
    total = 0.0
    j = 0
    b = sorted(b)
    for s, e in sorted(a):
        while j < len(b) and b[j][1] < s:
            j += 1
        k = j
        while k < len(b) and b[k][0] < e:
            total += max(0.0, min(e, b[k][1]) - max(s, b[k][0]))
            k += 1
    return total


def srt_of(path):
    if os.path.isfile(path):
        return path
    base = os.path.basename(path.rstrip("/\\"))
    cand = os.path.join(path, base + ".srt")
    if os.path.exists(cand):
        return cand
    raise SystemExit("no .srt found at %s" % path)


def names_of(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    p = os.path.join(d, "speaker_ids.json")
    if not os.path.exists(p):
        return {}
    return json.load(io.open(p, encoding="utf-8"))


def is_named(v):
    return bool(v) and not v.startswith("SPEAKER_") and "_SPEAKER_" not in v \
        and v != "Unidentified"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="pre-retranscribe dir or .srt")
    ap.add_argument("--new", required=True, help="current dir")
    ap.add_argument("--min-overlap", type=float, default=0.5,
                    help="fraction of the NEW label's speech the old one must "
                         "account for (default 0.5)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    old_s, new_s = spans(srt_of(args.old)), spans(srt_of(args.new))
    old_n, new_n = names_of(args.old), names_of(args.new)
    print("old: %d labels, %d named" % (len(old_s), sum(1 for v in old_n.values() if is_named(v))))
    print("new: %d labels, %d named" % (len(new_s), sum(1 for v in new_n.values() if is_named(v))))
    print()

    dur = {k: sum(e - s for s, e in v) for k, v in new_s.items()}
    proposals, weak, kept, relabelled = [], [], 0, []
    for nk in sorted(new_s, key=lambda k: -dur.get(k, 0)):
        scores = [(overlap(new_s[nk], old_s[ok]), ok) for ok in old_s]
        scores.sort(reverse=True)
        best, ok = scores[0] if scores else (0.0, None)
        frac = best / dur[nk] if dur.get(nk) else 0.0
        oldname = old_n.get(ok)
        newname = new_n.get(nk)

        if is_named(newname):
            kept += 1
            if ok and is_named(oldname) and oldname != newname:
                relabelled.append((nk, ok, oldname, newname, frac))
            continue
        if not (ok and is_named(oldname)):
            continue
        if frac < args.min_overlap:
            weak.append((nk, ok, oldname, frac, dur[nk]))
            continue
        proposals.append((nk, ok, oldname, frac, dur[nk]))

    print("new labels already named (left alone) : %d" % kept)
    print("RECOVERABLE names                     : %d" % len(proposals))
    for nk, ok, nm, frac, d in proposals:
        print("   %-12s <- %-12s %-24s overlap %3.0f%%  %5.0fs of speech"
              % (nk, ok, nm, 100 * frac, d))
    if weak:
        print("\ntoo ambiguous to carry over (reported, not applied):")
        for nk, ok, nm, frac, d in weak:
            print("   %-12s ~ %-12s %-24s overlap %3.0f%%  %5.0fs"
                  % (nk, ok, nm, 100 * frac, d))
    if relabelled:
        print("\nLABEL MEANING CHANGED between runs (both runs named these, differently):")
        for nk, ok, on, nn, frac in relabelled:
            print("   %-12s old %-22s new %-22s overlap %3.0f%%" % (nk, on, nn, 100 * frac))
        print("   ^ this is why a voiceprint or cluster reference keyed to the")
        print("     OLD numbering cannot be reused after a re-transcription.")

    if not args.apply:
        print("\ndry run; pass --apply to write speaker_ids.json")
        return 0
    if not proposals:
        print("\nnothing to apply")
        return 0
    d = args.new if os.path.isdir(args.new) else os.path.dirname(args.new)
    p = os.path.join(d, "speaker_ids.json")
    ids = json.load(io.open(p, encoding="utf-8"))
    for nk, ok, nm, frac, _ in proposals:
        ids[nk] = nm
    tmp = p + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
        json.dump(ids, fp, indent=4)
    os.replace(tmp, p)
    print("\napplied %d names to %s" % (len(proposals), p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
