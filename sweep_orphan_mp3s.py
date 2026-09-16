"""
One-time sweep of mp3s stranded in the repo root by the A14 bug.

create_subtitles.download_audio() downloaded audio successfully but never moved
it into audio/, because `if len(mp3path) == 1` tested the length of a FILENAME.
The files piled up in the repo root under yt-dlp's own naming, e.g.

    City Council 06-23-26 [-MlgNixuHJY].mp3

and, since the pipeline looked for audio/<upload_date>_<yt_id>.mp3 and never
found them, the same videos were re-downloaded on every pass. See plan.txt A14.

The code bug is fixed; this recovers the files already on disk so those videos
do not get downloaded a third time.

Usage:
    python sweep_orphan_mp3s.py            # dry run
    python sweep_orphan_mp3s.py --apply
"""

import argparse
import glob
import os
import re
import shutil
import sys

import utils

# yt-dlp substitutes look-alike unicode for characters illegal in filenames
# (e.g. U+29F8 for "/"), which the Windows console's cp1252 cannot encode.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# yt-dlp writes "<title> [<id>].mp3"; ids are 11 chars of [A-Za-z0-9_-]
ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]\.mp3$")

# duplicates are parked here (gitignored), never deleted
PARK_DIR = os.path.join("scratch", "orphan_mp3_duplicates")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be moved (use --apply) ===\n")

    video_data = utils.get_video_data()

    orphans = sorted(glob.glob("*.mp3"))
    moved = skipped = unknown = collision = 0

    for src in orphans:
        m = ID_RE.search(src)
        if not m:
            print("NO ID IN NAME  ", src)
            unknown += 1
            continue

        yt_id = m.group(1)
        if yt_id not in video_data:
            print("NOT IN video_data", yt_id, src)
            unknown += 1
            continue

        dest = utils.get_mp3filename(yt_id, video_data=video_data, local=True)

        # A good copy is already in audio/ -- this orphan is the duplicate half
        # of a double download. Never clobber the good copy; park the duplicate
        # in scratch/ (gitignored) rather than deleting it, so the operator can
        # confirm before anything is destroyed.
        if os.path.exists(dest):
            parked = os.path.join(PARK_DIR, os.path.basename(src))
            print("DUPLICATE      ", src)
            print("                 (good copy already at " + dest + ") -> " + PARK_DIR)
            collision += 1
            if args.apply:
                os.makedirs(PARK_DIR, exist_ok=True)
                shutil.move(src, parked)
            continue

        ext_dest = utils.get_mp3filename(yt_id, video_data=video_data, external=True)
        try:
            if os.path.exists(ext_dest):
                print("ON EXT DRIVE   ", src, "(already cached at", ext_dest + ")")
                skipped += 1
                continue
        except OSError:
            pass  # drive unplugged; treat as not cached

        print("MOVE           ", src, "->", dest)
        if args.apply:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
        moved += 1

    print("\norphans found :", len(orphans))
    print("moved         :", moved)
    print("already cached:", skipped)
    print("duplicates    :", collision, "(parked in " + PARK_DIR + ")")
    print("unrecognized  :", unknown)
    if not args.apply:
        print("\nDry run. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
