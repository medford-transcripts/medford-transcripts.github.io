"""Insert the licence footer into transcript pages generated before it existed.

WHY NOT JUST RERUN srt2html. A full pass redoes the nine-language translation
for every page; it was killed for memory twice on this machine while the
transcription loop had the RAM. The footer is a fixed block written immediately
before </body>, so inserting it directly produces exactly the bytes the
generator now emits -- the same reasoning used to repoint the committee links.

Idempotent: a page that already carries rel="license" is skipped, so this can
be run repeatedly and resumed after a kill. --limit bounds one invocation so a
loop of short processes keeps peak memory flat.
"""

import argparse
import glob
import io
import os

import utils


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after inserting into this many pages")
    args = ap.parse_args()

    foot = utils.site_footer("../")
    pages = sorted(glob.glob(os.path.join("20*_*", "*.html")))
    added = skipped = broken = 0
    for p in pages:
        if args.limit and added >= args.limit:
            break
        try:
            s = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            broken += 1
            continue
        if 'rel="license"' in s:
            skipped += 1
            continue
        i = s.rfind("  </body>")
        if i < 0:
            broken += 1          # not a page this script understands
            continue
        try:
            io.open(p, "w", encoding="utf-8", newline="").write(
                s[:i] + foot + s[i:])
        except OSError:
            broken += 1
            continue
        added += 1
    remaining = len(pages) - skipped - added - broken
    print("added %d | already had %d | unreadable/odd %d | not yet visited %d"
          % (added, skipped, broken, max(0, remaining)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
