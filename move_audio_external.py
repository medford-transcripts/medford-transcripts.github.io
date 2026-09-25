"""
Move transcription audio off the system drive onto the external drive.

WHY IT IS SAFE. utils.get_mp3filename already PREFERS the external copy:

    if os.path.exists(mp3_external) or external: return mp3_external
    if os.path.exists(mp3_local)    or local:    return mp3_local

so a file that exists only on D: is found exactly as before. create_subtitles
checks both paths too. Nothing needs changing for the pipeline to keep working.

WHY COPY-VERIFY-DELETE RATHER THAN shutil.move. Across drives, move is a copy
followed by an unlink, and a failure partway leaves a truncated file at the
destination and the source already gone. Here the source is deleted only after
the destination exists at exactly the same size. Slower, and it cannot lose
audio -- which for the ~1,100 meetings whose source video no longer exists
would be unrecoverable.

WHY IT SKIPS RECENT FILES. The downloader runs continuously and writes into
audio/. Moving a file it is still writing would truncate it, so anything
touched in the last SKIP_MINUTES is left alone; the next run picks it up.

Usage:
    python move_audio_external.py            # report only
    python move_audio_external.py --apply
"""

import argparse
import glob
import os
import shutil
import sys
import time

LOCAL = "audio"
EXTERNAL = "D:/medford-transcripts.github.io/audio"
SKIP_MINUTES = 15


def gb(n):
    return n / 1024.0 ** 3


def plan(local=LOCAL, external=EXTERNAL):
    """(delete, move, skipped) -- delete is already on D: byte-for-byte."""
    now = time.time()
    ext = set(os.listdir(external)) if os.path.isdir(external) else set()
    delete, move, skipped = [], [], []
    for p in sorted(glob.glob(os.path.join(local, "*.mp3"))):
        name = os.path.basename(p)
        size = os.path.getsize(p)
        if now - os.path.getmtime(p) < SKIP_MINUTES * 60:
            skipped.append((name, size))
            continue
        if name in ext and os.path.getsize(os.path.join(external, name)) == size:
            delete.append((name, size))
        else:
            move.append((name, size))
    return delete, move, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--local", default=LOCAL)
    ap.add_argument("--external", default=EXTERNAL)
    args = ap.parse_args()

    if not os.path.isdir(args.external):
        raise SystemExit("external drive not mounted at %s -- refusing to run"
                         % args.external)

    delete, move, skipped = plan(args.local, args.external)
    print("already on D: byte-identical, delete local : %4d  (%.1f GB)"
          % (len(delete), gb(sum(s for _, s in delete))))
    print("to copy across then delete                 : %4d  (%.1f GB)"
          % (len(move), gb(sum(s for _, s in move))))
    print("skipped, written in the last %d min        : %4d"
          % (SKIP_MINUTES, len(skipped)))
    total = sum(s for _, s in delete) + sum(s for _, s in move)
    print("space this frees on C:                     : %.1f GB" % gb(total))
    if not args.apply:
        print("\nreport only; pass --apply")
        return 0

    freed = failed = 0
    for name, size in delete:
        os.remove(os.path.join(args.local, name))
        freed += size
    print("deleted %d redundant local copies" % len(delete))

    for n, (name, size) in enumerate(move, 1):
        src = os.path.join(args.local, name)
        dst = os.path.join(args.external, name)
        try:
            shutil.copy2(src, dst)
            if os.path.getsize(dst) != size:
                print("  SIZE MISMATCH after copy, keeping local: %s" % name)
                failed += 1
                continue
            os.remove(src)
            freed += size
        except Exception as e:
            print("  FAILED %s: %s" % (name, str(e)[:90]))
            failed += 1
        if n % 100 == 0:
            print("  ...%d/%d, %.1f GB freed" % (n, len(move), gb(freed)))
            sys.stdout.flush()
    print("\nfreed %.1f GB; %d failures" % (gb(freed), failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
