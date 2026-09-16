"""
Recover the Spotify URLs lost from video_data.json for podcast (XXXXXX*) items.

All 152 XXXXXX entries now carry url == "" (empty string, not a missing key),
but the PUBLISHED English pages for those episodes still contain the real
Spotify episode URLs -- proof the data was present when those pages were
generated and has since been wiped, presumably by an RSS refresh writing an
empty value. See plan.txt A19.

Two things depend on fixing this:
  1. the 152 translated podcast pages still link every timestamp to a dead
     youtu.be/XXXXXX URL, and fix_media_links.py cannot repair them without
     a correct URL to substitute;
  2. more seriously, regenerating any of those pages would strip the Spotify
     links from the ENGLISH page too, because srt2html builds them from
     video_data. The regression is latent and spreads on the next rebuild.

This harvests the episode URL back out of each published English page and
writes it into video_data.json.

Run ONLY while the pipeline is stopped -- video_data.json is shared state.

Usage:
    python restore_podcast_urls.py            # dry run
    python restore_podcast_urls.py --apply
"""

import argparse
import glob
import json
import os
import re
import sys

# https://open.spotify.com/episode/<id>   (stop before ?t= or &)
SPOTIFY_RE = re.compile(r'https://open\.spotify\.com/episode/[A-Za-z0-9]+')


def harvest(yt_id):
    """The episode URL as it appears in this item's published English page."""
    matches = glob.glob("20??-??-??_" + yt_id + os.sep + "*_" + yt_id + ".html")
    if not matches:
        matches = glob.glob("20??-??-??_" + yt_id + "/*_" + yt_id + ".html")
    if not matches:
        return None, "no English page on disk"

    with open(matches[0], "rb") as fp:
        data = fp.read()

    found = SPOTIFY_RE.findall(data.decode("utf-8", "replace"))
    if not found:
        return None, "no spotify url in " + os.path.basename(matches[0])

    uniq = sorted(set(found))
    if len(uniq) > 1:
        return None, "ambiguous: %d distinct urls" % len(uniq)
    return uniq[0], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- video_data.json will not be written ===\n")

    with open("video_data.json", "r", encoding="utf-8") as fp:
        video_data = json.load(fp)

    ids = sorted(k for k in video_data if k.startswith("XXXXXX"))
    recovered = skipped = already = 0
    failures = []

    for yt_id in ids:
        if video_data[yt_id].get("url"):
            already += 1
            continue

        url, why = harvest(yt_id)
        if url is None:
            failures.append((yt_id, why))
            skipped += 1
            continue

        if recovered < 5:
            print("  %s -> %s" % (yt_id, url))
        video_data[yt_id]["url"] = url
        recovered += 1

    print("\npodcast entries : %d" % len(ids))
    print("already had url : %d" % already)
    print("recovered       : %d" % recovered)
    print("could not fix   : %d" % skipped)

    if failures:
        print("\nnot recovered:")
        for yt_id, why in failures[:15]:
            print("   %s  (%s)" % (yt_id, why))

    if args.apply and recovered:
        tmp = "video_data.json.urlfix.tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(video_data, fp, indent=4)
        os.replace(tmp, "video_data.json")
        print("\nWROTE video_data.json (%d urls restored)." % recovered)
    elif not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
