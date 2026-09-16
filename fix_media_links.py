"""
Surgical repair of dead youtu.be timestamp links on already-generated pages.

srt2html.finish_speaker() hardcoded https://youtu.be/<id> for the non-English
branch, so every translated page of every non-YouTube meeting linked each
timestamp to a YouTube URL that does not exist. The English pages were always
correct because they reuse the caller's platform-aware htmltext.

Affected: MCM archive.org items (MCM000*) and podcast/RSS items (XXXXXX*).

    before:  https://youtu.be/MCM00001481&t=0.451s
    after:   https://archive.org/details/behavioral-health-commission-05-04-22&start=0.451

    before:  https://youtu.be/XXXXXX0001&t=12.5s
    after:   <spotify url>?t=12.5

The generator is fixed (see srt2html.timestamp_url), but pages already written
would otherwise keep the dead links until every one is regenerated -- which
would mean re-translating the whole site. This rewrites just the href, in
place, on bytes, so non-ASCII transcript content cannot be corrupted.

Usage:
    python fix_media_links.py            # dry run
    python fix_media_links.py --apply
"""

import argparse
import json
import os
import re
import sys

# youtu.be links written for ids that are NOT YouTube ids
LINK_RE = re.compile(rb'https://youtu\.be/((?:MCM000|XXXXXX)\d+)&t=([0-9.]+)s')

SKIP_DIRS = {
    ".git", "__pycache__", "archive", "voices_folder", "clips", "headshots",
    "medford_tmp", "scratch", "node_modules", "jotaemei_videos",
    "models--Systran--faster-whisper-large-v2",
    "models--Systran--faster-whisper-large-v3",
}


def build_replacement(video_data, yt_id_b, start_b):
    """Correct URL bytes for this id/timestamp, or None if unknown."""
    yt_id = yt_id_b.decode("ascii")
    entry = video_data.get(yt_id)
    if not entry:
        return None
    url = entry.get("url")
    if not url:
        return None

    start = start_b.decode("ascii")
    if yt_id.startswith("XXXXXX"):
        new = url + "?t=" + start
    else:
        new = url + "&start=" + start
    try:
        return new.encode("ascii")
    except UnicodeEncodeError:
        return new.encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    with open("video_data.json", "r", encoding="utf-8") as fp:
        video_data = json.load(fp)

    files_changed = links_changed = 0
    examined = 0
    unresolved = {}
    samples = []

    for dirpath, dirnames, filenames in os.walk(args.root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".html"):
                continue
            full = os.path.join(dirpath, name)
            examined += 1

            with open(full, "rb") as fp:
                data = fp.read()

            if b"youtu.be/MCM" not in data and b"youtu.be/XXXXXX" not in data:
                continue

            n_here = [0]

            def sub(m):
                rep = build_replacement(video_data, m.group(1), m.group(2))
                if rep is None:
                    unresolved[m.group(1).decode("ascii")] = \
                        unresolved.get(m.group(1).decode("ascii"), 0) + 1
                    return m.group(0)
                n_here[0] += 1
                if len(samples) < 3 and n_here[0] == 1:
                    samples.append((os.path.relpath(full, args.root),
                                    m.group(0).decode("ascii"),
                                    rep.decode("utf-8", "replace")))
                return rep

            patched = LINK_RE.sub(sub, data)

            if n_here[0]:
                files_changed += 1
                links_changed += n_here[0]
                if args.apply:
                    tmp = full + ".linkfix.tmp"
                    with open(tmp, "wb") as fp:
                        fp.write(patched)
                    os.replace(tmp, full)

    print("html examined :", examined)
    print("files changed :", files_changed)
    print("links changed :", links_changed)
    if unresolved:
        print("\nUNRESOLVED (no 'url' in video_data; left as-is):")
        for k, v in sorted(unresolved.items())[:20]:
            print("   %s  (%d links)" % (k, v))
    if samples:
        print("\nsamples:")
        for rel, before, after in samples:
            print("  ", rel)
            print("     before:", before)
            print("     after :", after)
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
