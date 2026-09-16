"""
Surgical repair of broken <link rel="canonical"> tags in ALREADY-GENERATED HTML.

Why this exists instead of just re-running srt2html.py: a full regeneration
re-translates every page into 10 languages. Most older pages have no local
translation cache, so a full rebuild would take weeks and burn a large
translation bill. This script rewrites ONLY the canonical line, in place,
touching nothing else. See plan.txt phase 0.3.

Two bug classes are repaired (plan.txt A1):

  1. BACKSLASH  -- srt2html.py built the URL from an os.path.join() result, so
     every transcript page says
         https://medford-transcripts.github.io/2025-01-03_MCM00001695\\...html
     A backslash is not a path separator in a URL. Google resolves it to one
     flat segment that 404s, and drops the page from the index.

  2. ROOT       -- election pages, about.html and candidates_2025.html declare
     the site homepage as their canonical, i.e. "I am a duplicate of the
     homepage, do not index me."

Everything else is left alone. In particular this script does NOT add missing
canonical tags -- that is Phase 2 work, not a surgical fix.

Operates on BYTES, never decoding the file, so non-ASCII transcript content in
ar/km/ru/zh-cn/... cannot be corrupted by an encoding round-trip.

Usage:
    python fix_canonicals.py                # dry run, report only
    python fix_canonicals.py --apply        # rewrite in place
    python fix_canonicals.py --limit 200    # sample, for a quick look
"""

import argparse
import os
import re
import sys

from site_url import site_url, SITE_ROOT

CANONICAL_RE = re.compile(rb'(<link\s+rel="canonical"\s+href=")([^"]*)(")')

ROOT_BYTES = SITE_ROOT.encode("ascii")

# directories that are not part of the published site
SKIP_DIRS = {
    ".git", "__pycache__", "archive", "voices_folder", "clips", "headshots",
    "medford_tmp", "scratch", "node_modules", "jotaemei_videos",
    "models--Systran--faster-whisper-large-v2",
    "models--Systran--faster-whisper-large-v3",
}

# header.html is a TEMPLATE FRAGMENT prepended to build index.html. Its root
# canonical is correct and must not be rewritten.
SKIP_FILES = {"header.html"}

# the site root legitimately canonicalizes to "/"
ROOT_INDEX = "index.html"


def iter_html(root="."):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".html"):
                continue
            if name in SKIP_FILES:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            yield full, rel


def decide(rel, current):
    """Return the corrected canonical bytes, or None to leave the file alone."""
    if rel.replace("\\", "/") == ROOT_INDEX:
        return None  # the homepage really is the root

    if b"\\" in current:
        reason = "backslash"
    elif current.rstrip(b"/") == ROOT_BYTES.rstrip(b"/"):
        reason = "root"
    else:
        return None

    correct = site_url(rel).encode("ascii")
    if correct == current:
        return None
    return correct, reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="rewrite files in place (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after examining N html files")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    counts = {"backslash": 0, "root": 0}
    examined = changed = no_tag = unreadable = 0
    samples = []

    for full, rel in iter_html(args.root):
        examined += 1
        if args.limit and examined > args.limit:
            examined -= 1
            break

        try:
            with open(full, "rb") as fp:
                data = fp.read()
        except OSError as e:
            unreadable += 1
            print("UNREADABLE", rel, e)
            continue

        m = CANONICAL_RE.search(data)
        if not m:
            no_tag += 1
            continue

        verdict = decide(rel, m.group(2))
        if verdict is None:
            continue
        correct, reason = verdict

        counts[reason] += 1
        changed += 1
        if len(samples) < 5:
            samples.append((rel, m.group(2).decode("ascii", "replace"),
                            correct.decode("ascii")))

        if args.apply:
            patched = data[:m.start(2)] + correct + data[m.end(2):]
            tmp = full + ".canonfix.tmp"
            with open(tmp, "wb") as fp:
                fp.write(patched)
            os.replace(tmp, full)

    print("examined     :", examined)
    print("no canonical :", no_tag, "(left alone; Phase 2 adds these)")
    print("unreadable   :", unreadable)
    print("to fix       :", changed)
    print("  backslash  :", counts["backslash"])
    print("  root       :", counts["root"])
    if samples:
        print("\nsamples:")
        for rel, before, after in samples:
            print("  ", rel)
            print("     before:", before)
            print("     after :", after)
    if args.apply:
        print("\nWROTE %d files." % changed)
    else:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
