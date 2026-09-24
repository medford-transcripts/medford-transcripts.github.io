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


def remap_names(old, new, min_overlap=0.5, apply=False):
    """Carry speaker names from a pre-retranscription state onto the new one.

    `old` and `new` are each a transcript directory (or an .srt path); each
    must have a speaker_ids.json beside it. Returns:

        {"recovered": [(new_label, old_label, name, overlap, seconds)],
         "ambiguous": [...same shape, below min_overlap, NOT applied...],
         "changed":   [(label, old_name, new_name, overlap)],
         "old_labels","old_named","new_labels","new_named","applied"}

    Call this whenever a transcript is regenerated -- a re-transcription, or
    migrating a meeting onto a new pipeline. Diarization is not deterministic,
    so the new run re-derives names from scratch and silently drops any that
    only ever existed as manual work. `changed` is the other half of the
    warning: a label can keep its number and mean a different person, which is
    what makes voiceprints and cross-video cluster references keyed to
    <yt_id>_SPEAKER_nn unsafe to carry across a regeneration.

    Only UNNAMED labels are filled. A name the new run derived is never
    overwritten -- this recovers lost work, it does not relitigate a fresh
    decision.
    """
    old_s, new_s = spans(srt_of(old)), spans(srt_of(new))
    old_n, new_n = names_of(old), names_of(new)

    dur = {k: sum(e - s for s, e in v) for k, v in new_s.items()}
    out = {"recovered": [], "ambiguous": [], "changed": [],
           "old_labels": len(old_s), "new_labels": len(new_s),
           "old_named": sum(1 for v in old_n.values() if is_named(v)),
           "new_named": sum(1 for v in new_n.values() if is_named(v)),
           "applied": 0}

    for nk in sorted(new_s, key=lambda k: -dur.get(k, 0)):
        scores = [(overlap(new_s[nk], old_s[ok]), ok) for ok in old_s]
        scores.sort(reverse=True)
        best, ok = scores[0] if scores else (0.0, None)
        frac = best / dur[nk] if dur.get(nk) else 0.0
        oldname, newname = old_n.get(ok), new_n.get(nk)

        if is_named(newname):
            if ok and is_named(oldname) and oldname != newname:
                out["changed"].append((nk, oldname, newname, frac))
            continue
        if not (ok and is_named(oldname)):
            continue
        (out["ambiguous"] if frac < min_overlap else out["recovered"]).append(
            (nk, ok, oldname, frac, dur[nk]))

    if apply and out["recovered"]:
        d = new if os.path.isdir(new) else os.path.dirname(new)
        p = os.path.join(d, "speaker_ids.json")
        ids = json.load(io.open(p, encoding="utf-8"))
        for nk, ok, nm, frac, _ in out["recovered"]:
            ids[nk] = nm
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
            json.dump(ids, fp, indent=4)
        os.replace(tmp, p)
        out["applied"] = len(out["recovered"])
    return out


def report(r):
    """Print a remap_names() result."""
    print("old: %d labels, %d named" % (r["old_labels"], r["old_named"]))
    print("new: %d labels, %d named" % (r["new_labels"], r["new_named"]))
    print()
    print("RECOVERABLE names : %d" % len(r["recovered"]))
    for nk, ok, nm, frac, d in r["recovered"]:
        print("   %-12s <- %-12s %-24s overlap %3.0f%%  %5.0fs of speech"
              % (nk, ok, nm, 100 * frac, d))
    if r["ambiguous"]:
        print("\ntoo ambiguous to carry over (reported, not applied):")
        for nk, ok, nm, frac, d in r["ambiguous"]:
            print("   %-12s ~ %-12s %-24s overlap %3.0f%%  %5.0fs"
                  % (nk, ok, nm, 100 * frac, d))
    if r["changed"]:
        print("\nLABEL MEANING CHANGED between runs (both named these, differently):")
        for nk, on, nn, frac in r["changed"]:
            print("   %-12s old %-22s new %-22s overlap %3.0f%%" % (nk, on, nn, 100 * frac))
        print("   ^ a voiceprint or cluster reference keyed to the OLD numbering")
        print("     cannot be reused after a regeneration.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="pre-regeneration dir or .srt")
    ap.add_argument("--new", required=True, help="current dir")
    ap.add_argument("--min-overlap", type=float, default=0.5,
                    help="fraction of the NEW label's speech the old one must "
                         "account for (default 0.5)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    r = remap_names(args.old, args.new, args.min_overlap, args.apply)
    report(r)
    if args.apply:
        print("\napplied %d names" % r["applied"])
    else:
        print("\ndry run; pass --apply to write speaker_ids.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
