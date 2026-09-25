"""One-time migration: renumber CAS ids into upload-date order.

WHY. The id number is a public, permanent name -- it is the directory on disk
and the URL on the site. Every other source numbers by upload date ascending:
download_mcm asks archive.org for "publicdate asc", and the podcast ids follow
episode order, so MCM00000001 and XXXXXX00001 are the OLDEST items and the
numbers read as a timeline. Castus was enumerated in raw API order, which is
newest-first, so the first import ran the convention backwards -- measured
across the corpus, MCM is 100% date-ascending, the podcast ids 100%, and CAS
98% DESCENDING. CAS00000001 was 2026-09-21, the newest item in the catalogue.

download_castus.enumeration_order() fixes this for everything minted from now
on. This fixes the 2,534 already minted, and it is worth doing NOW because the
cost only grows: at the time of writing exactly two Castus meetings have been
transcribed and published, so two URLs move. In six months it would be
hundreds.

WHAT IT TOUCHES, all of it mechanical and local -- verified before writing:
  - castus_index.json   the castus_id -> number mapping (tracked in git)
  - video_data.json     2,534 keys, AND 1,110 duplicate_id values on OTHER
                        entries that point at a CAS id. Miss those and every
                        one becomes a dangling reference.
  - 13 directories, 2 of which have content
  - 225 audio files (13 local, 212 on the external drive)
  - nothing else: no speaker_ids.json anywhere cites a CAS id, and the only
    file whose CONTENT embeds one is the per-directory index.html redirect,
    which is regenerated.

WHY TWO-PHASE RENAMES. The old and new id spaces overlap almost completely
(both are CAS00000001..CAS00002534), so a direct rename would collide with a
name that is still in use. Everything moves to a temporary name first, then to
its final one.

Usage:
    python renumber_castus.py              # report only
    python renumber_castus.py --apply
"""

import argparse
import glob
import io
import json
import os
import sys

import utils
import download_castus

TMP = "__RENUM__"
AUDIO_DIRS = ["audio", "D:/medford-transcripts.github.io/audio"]


def pipeline_processes():
    """PIDs of running create_subtitles.py loops. None means 'could not tell'.

    THIS IS THE ONE THING THAT CAN CORRUPT THE MIGRATION. create_subtitles
    saves its WHOLE in-memory video_data without re-reading first (srt2html
    re-reads, create_subtitles does not -- see its save_video_data calls), and
    those loops run for weeks. Renumber while one is alive and its next save
    writes the old 2,534 CAS keys back alongside the new ones: ~5,000 entries,
    every duplicate_id reference dangling, and the same meetings queued twice.

    None and [] are deliberately different. "I could not check" must never
    read as "nothing is running" -- that conflation is the failure mode this
    codebase keeps hitting.
    """
    try:
        import psutil
    except ImportError:
        return None
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            args = p.info.get("cmdline") or []
            name = (p.info.get("name") or "").lower()
        except Exception:
            continue
        # must be a python process ACTUALLY running the script -- a shell whose
        # command line merely mentions the filename does not count
        if not name.startswith("python"):
            continue
        if any(a.replace("\\", "/").endswith("create_subtitles.py") for a in args):
            out.append(p.info["pid"])
    return out


def plan():
    """(mapping old->new, rows) with rows sorted the way a fresh import would."""
    index = download_castus.load_index()
    vd = utils.get_video_data()

    rows = []
    for cid, n in index.items():
        old = download_castus.PREFIX + str(n).zfill(8)
        up = (vd.get(old) or {}).get("upload_date") or ""
        rows.append((up, cid, old))

    # Exactly the key enumeration_order() uses, so the result is what a
    # from-scratch import of the same catalogue would produce.
    rows.sort(key=lambda r: (r[0] or "9999", r[1]))

    mapping = {}
    for i, (_up, _cid, old) in enumerate(rows, 1):
        mapping[old] = download_castus.PREFIX + str(i).zfill(8)
    return mapping, rows


def _moves(mapping):
    """Every filesystem path that has to move, as (src, dst) pairs.

    Scans each location ONCE and looks the id up, rather than globbing per id:
    the per-id form issued 2,534 globs against the external drive and took
    minutes.
    """
    out = []
    for d in glob.glob("20??-??-??_" + download_castus.PREFIX + "*"):
        base = os.path.basename(d)
        up, _, old = base.partition("_")
        new = mapping.get(old)
        if new and new != old:
            out.append((d, up + "_" + new))
    for adir in AUDIO_DIRS:
        if not os.path.isdir(adir):
            continue
        for p in glob.glob(os.path.join(adir, "*_" + download_castus.PREFIX + "*")):
            name = os.path.basename(p)
            old = name.partition("_")[2].split(".")[0]
            new = mapping.get(old)
            if new and new != old:
                out.append((p, os.path.join(adir, name.replace(old, new, 1))))
    return out


def _inner(dirname, old, new):
    """Files INSIDE a renamed directory whose own name carries the id."""
    out = []
    for p in glob.glob(os.path.join(dirname, "*" + old + "*")):
        out.append((p, os.path.join(dirname, os.path.basename(p).replace(old, new))))
    return out


def apply_moves(mapping, verbose=True):
    moves = _moves(mapping)
    # phase 1: everything to a temporary name, so no rename can collide with a
    # path that another rename has not vacated yet
    for src, dst in moves:
        os.rename(src, src + TMP)
    for src, dst in moves:
        os.rename(src + TMP, dst)
    if verbose:
        print("moved %d paths" % len(moves))

    # The directories now carry their NEW id while the files inside still carry
    # the old one, so walk the directories that exist and invert the mapping.
    renamed_dirs = 0
    inv = dict((v, k) for k, v in mapping.items())
    for d in glob.glob("20??-??-??_" + download_castus.PREFIX + "*"):
        new = os.path.basename(d).partition("_")[2]
        old = inv.get(new)
        if not old or old == new:
            continue
        pairs = _inner(d, old, new)
        for src, dst in pairs:
            os.rename(src, src + TMP)
        for src, dst in pairs:
            os.rename(src + TMP, dst)
        if pairs:
            renamed_dirs += 1
    if verbose:
        print("renamed inner files in %d directories" % renamed_dirs)
    return len(moves)


def apply_data(mapping, verbose=True):
    vd = utils.get_video_data()

    remapped, refs = 0, 0
    new_vd = {}
    for y, e in vd.items():
        key = mapping.get(y, y)
        if key != y:
            remapped += 1
        dup = e.get("duplicate_id")
        if dup and dup in mapping and mapping[dup] != dup:
            e["duplicate_id"] = mapping[dup]
            refs += 1
        new_vd[key] = e
    if len(new_vd) != len(vd):
        raise SystemExit("refusing to save: %d entries became %d -- id collision"
                         % (len(vd), len(new_vd)))
    utils.save_video_data(new_vd)

    index = download_castus.load_index()
    for cid in list(index):
        old = download_castus.PREFIX + str(index[cid]).zfill(8)
        index[cid] = int(mapping.get(old, old)[len(download_castus.PREFIX):])
    download_castus.save_index(index)

    if verbose:
        print("video_data: %d keys remapped, %d duplicate_id references rewritten"
              % (remapped, refs))
        print("castus_index.json rewritten (%d items)" % len(index))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="run --apply even though the pipeline looks alive (don't)")
    args = ap.parse_args()

    mapping, rows = plan()
    changed = {o: n for o, n in mapping.items() if o != n}
    print("castus items            : %d" % len(mapping))
    print("ids that change         : %d" % len(changed))
    print("filesystem paths to move: %d" % len(_moves(mapping)))

    vd = utils.get_video_data()
    refs = sum(1 for e in vd.values()
               if (e.get("duplicate_id") or "") in changed)
    print("duplicate_id references : %d" % refs)

    print("\noldest 3 (should become CAS00000001..3):")
    for up, cid, old in rows[:3]:
        print("   %s  %-13s -> %-13s %r" % (up, old, mapping[old],
                                            (vd.get(old) or {}).get("title", "")[:40]))
    print("newest 3:")
    for up, cid, old in rows[-3:]:
        print("   %s  %-13s -> %-13s %r" % (up, old, mapping[old],
                                            (vd.get(old) or {}).get("title", "")[:40]))

    print("\ntranscribed directories that move:")
    for d in sorted(glob.glob("20??-??-??_CAS*")):
        if not os.listdir(d):
            continue
        old = os.path.basename(d).split("_", 1)[1]
        print("   %s -> %s  (%d files)"
              % (d, os.path.basename(d).replace(old, mapping.get(old, old)), len(os.listdir(d))))

    procs = pipeline_processes()
    if procs is None:
        print("\nPIPELINE: could not check (psutil not installed).")
    elif procs:
        print("\nPIPELINE: RUNNING -- pids %s"
              % ", ".join(str(p) for p in procs))
    else:
        print("\nPIPELINE: stopped. Safe to --apply.")

    if not args.apply:
        print("\nreport only; pass --apply")
        return 0

    if procs and not args.force:
        print("\nREFUSING TO RUN. create_subtitles.py is alive (pids %s) and saves"
              % ", ".join(str(p) for p in procs))
        print("its whole in-memory video_data without re-reading, so its next save")
        print("would restore every old CAS key beside the new ones. Stop both loops")
        print("(download + transcribe), then re-run. The .bat wrappers relaunch on")
        print("current code, so restarting afterwards picks this up automatically.")
        return 2
    if procs is None and not args.force:
        print("\nREFUSING TO RUN: cannot verify the pipeline is stopped "
              "(pip install psutil), and 'unknown' is not 'safe'. Use --force "
              "only if you have confirmed by hand that it is down.")
        return 2

    apply_moves(mapping)
    apply_data(mapping)
    print("\nDone. Regenerate the moved pages:")
    print("  python srt2html.py -i <new id> -f")
    return 0


if __name__ == "__main__":
    sys.exit(main())
