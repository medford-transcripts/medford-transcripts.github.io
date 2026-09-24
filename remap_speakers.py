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
import glob
import io
import json
import os
import re
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


# --------------------------------------------------------------------------
# THE MIGRATION PROCEDURE
#
# Regenerating a transcript -- re-transcribing it, or moving it onto a new
# pipeline -- destroys three things that nothing else records:
#
#   1. NAMES. The new run re-derives them and drops any that existed only as
#      manual work. 2024-10-15_kP4iRYobyr0 went from 45 named labels to 37.
#
#   2. THE MEANING OF EVERY LABEL. SPEAKER_07 meant Zac Bears before that run
#      and Adam Hurtubise after, on the same audio at 98% overlap. Numbering is
#      mostly stable and occasionally is not, which is the worst case: too
#      reliable to distrust, not reliable enough to depend on.
#
#   3. ANYTHING KEYED TO <yt_id>_SPEAKER_nn ELSEWHERE. Measured 2026-09-23:
#      465 meetings have labels cited by other meetings' speaker_ids.json,
#      2,074 citations in total, up to 40 for a single meeting; and 364
#      meetings have voiceprints in voices_folder. A citation does not break
#      loudly when its target is regenerated -- it silently resolves to a
#      different person.
#
# None of that is recoverable after the fact, because the comparison needs the
# PRE state and the regeneration overwrites it in place. So the procedure is
# snapshot-first, and the snapshot is not optional.
#
#     snap = snapshot(yt_id)          # before touching anything
#     ...regenerate...
#     report = finish(yt_id, snap, apply=True)
#
# or migrate(yt_id, regenerate=fn) to run all three in order.

import shutil
import time

BACKUP_ROOT = "migration_backup"
CLUSTER_REF = re.compile(r"^([A-Za-z0-9_-]{6,})_SPEAKER_(\d+)$")


def _dir_of(yt_id):
    hits = [d for d in glob.glob("20??-??-??_" + yt_id) if os.path.isdir(d)]
    if not hits:
        raise SystemExit("no transcript directory for " + yt_id)
    return hits[0]


def referrers(yt_id):
    """[(dir, label, citation, resolves_to)] -- other meetings citing our labels.

    These are the invisible casualties of a regeneration. The citing file is
    not touched and reports no error; the name it resolves to just changes.
    """
    out = []
    mine = os.path.join(_dir_of(yt_id), "speaker_ids.json")
    names = json.load(io.open(mine, encoding="utf-8")) if os.path.exists(mine) else {}
    for p in glob.glob("20??-??-??_*/speaker_ids.json"):
        if os.path.abspath(p) == os.path.abspath(mine):
            continue
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except ValueError:
            continue
        for label, val in d.items():
            if not isinstance(val, str):
                continue
            m = CLUSTER_REF.match(val)
            if m and m.group(1) == yt_id:
                out.append((os.path.dirname(p), label, val,
                            names.get("SPEAKER_" + m.group(2))))
    return out


def voiceprints(yt_id):
    return sorted(glob.glob(os.path.join("voices_folder", yt_id + "_SPEAKER_*")))


def hazards(yt_id):
    """What regenerating this meeting would invalidate. Check BEFORE starting."""
    refs = referrers(yt_id)
    vps = voiceprints(yt_id)
    manual = False
    try:
        with io.open("manual_corrections.json", encoding="utf-8") as fp:
            manual = yt_id in json.load(fp).get("ids", {})
    except (OSError, ValueError):
        pass
    return {"referrers": refs, "voiceprints": vps, "manually_corrected": manual,
            "citing_meetings": len({r[0] for r in refs})}


def snapshot(yt_id, root=BACKUP_ROOT):
    """Copy everything a regeneration destroys, plus the hazard report.

    The .srt comes along because remap_names needs it: matching old labels to
    new ones is done on shared audio time, so the OLD timings are as necessary
    as the old names.
    """
    src = _dir_of(yt_id)
    dest = os.path.join(root, os.path.basename(src))
    os.makedirs(dest, exist_ok=True)
    base = os.path.basename(src)
    saved = []
    for name in (base + ".srt", "speaker_ids.json", "speaker_provenance.json"):
        p = os.path.join(src, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dest, name))
            saved.append(name)
    h = hazards(yt_id)
    manifest = {"yt_id": yt_id, "source": src, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "saved": saved, "hazards": h}
    with io.open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8", newline="") as fp:
        json.dump(manifest, fp, indent=2)
    print("snapshot %s -> %s  (%s)" % (yt_id, dest, ", ".join(saved) or "nothing!"))
    if h["referrers"]:
        print("  WARNING: %d citations from %d other meetings point at this one's labels"
              % (len(h["referrers"]), h["citing_meetings"]))
    if h["voiceprints"]:
        print("  WARNING: %d voiceprint files keyed to the current labels" % len(h["voiceprints"]))
    if h["manually_corrected"]:
        print("  WARNING: this transcript carries manual corrections")
    return dest


def finish(yt_id, snap, apply=False, quarantine=True, min_overlap=0.5):
    """After regeneration: recover names, quarantine stale voiceprints, report.

    The check that matters is `broken`: for every citation from another
    meeting, what its label meant BEFORE (recorded in the snapshot manifest)
    against what it means NOW. That is the corruption a regeneration causes
    silently, and the only moment it is detectable is here.
    """
    cur = _dir_of(yt_id)
    r = remap_names(snap, cur, min_overlap=min_overlap, apply=apply)

    before = {}
    mpath = os.path.join(snap, "manifest.json")
    if os.path.exists(mpath):
        for d, label, val, was in json.load(io.open(mpath, encoding="utf-8"))["hazards"]["referrers"]:
            before[(d, label, val)] = was
    now = {(d, label, val): res for d, label, val, res in referrers(yt_id)}
    broken = [(k, was, now.get(k)) for k, was in before.items() if now.get(k) != was]

    r["broken_references"] = broken
    r["quarantined"] = []
    if quarantine:
        vps = voiceprints(yt_id)
        if vps:
            dest = os.path.join(snap, "stale_voiceprints")
            if apply:
                os.makedirs(dest, exist_ok=True)
                for p in vps:
                    shutil.move(p, os.path.join(dest, os.path.basename(p)))
            r["quarantined"] = vps

    report(r)
    if r["quarantined"]:
        print("\n%s %d voiceprints keyed to the OLD labels"
              % ("quarantined" if apply else "WOULD quarantine", len(r["quarantined"])))
        print("   they cannot be reused: the labels they name may now mean someone else")
    if broken:
        print("\nCITATIONS FROM OTHER MEETINGS THAT NOW RESOLVE DIFFERENTLY:")
        for (d, label, val), was, isnow in broken:
            print("   %-28s %-12s %-26s %s -> %s" % (d, label, val, was, isnow))
        print("   ^ these need a human; nothing in the citing files changed.")
    elif before:
        print("\n%d citations from other meetings still resolve to the same people" % len(before))
    return r


def migrate(yt_id, regenerate=None, root=BACKUP_ROOT, apply=False, min_overlap=0.5):
    """snapshot -> regenerate -> finish, in the only order that is safe.

    `regenerate` is called with the yt_id between the two halves; pass None to
    snapshot only (when the regeneration is done by the pipeline elsewhere,
    which is the usual case -- transcription takes hours and is not this
    function's job).
    """
    snap = snapshot(yt_id, root)
    if regenerate is None:
        print("no regenerate callable given; snapshot only.")
        print("run finish('%s', '%s', apply=True) afterwards." % (yt_id, snap))
        return {"snapshot": snap}
    regenerate(yt_id)
    out = finish(yt_id, snap, apply=apply, min_overlap=min_overlap)
    out["snapshot"] = snap
    return out


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
