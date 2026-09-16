"""
Populate `audio_url` for Medford Bytes (XXXXXX*) episodes from the RSS feed.

The feed is the authoritative, programmatic source: it carries all 152
episodes, and each <item> has an <enclosure url="..."> pointing at the actual
audio file. Matching feed items to our episodes by title is exact.

Why this instead of Spotify episode ids: the feed's <link> is a
podcasters.spotify.com URL carrying an Anchor id (…-e18q1ue), NOT the
open.spotify.com/episode/<22-char> id. Following the redirect lands on a JS
app that never exposes the episode id, so the Spotify id is not derivable from
the feed. Getting it would mean a Spotify Web API credential.

The audio URL needs none of that, and it feeds player.html — our own
timestamped player — which also fixes the 12 episodes whose Spotify URL was
lost entirely (see plan.txt A19).

`url` (the Spotify episode page) is left alone where present; it is still the
right link for "listen/subscribe on Spotify".

Run while the pipeline is stopped if possible; it uses utils.save_video_data
so it respects the video_data.lock protocol either way.

Usage:
    python update_podcast_audio.py            # dry run
    python update_podcast_audio.py --apply
"""

import argparse
import sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import utils

RSS_FEED = "https://anchor.fm/s/6f6f95b8/podcast/rss"


def fetch_items(feed_url=RSS_FEED):
    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=90).read()
    root = ET.fromstring(data)
    channel = root.find("channel")

    # The feed has a few DUPLICATE TITLES (152 items, 149 distinct titles), so
    # title alone can silently attach the wrong audio to an episode. Key on
    # (title, publication date) and keep a title-only index purely as a
    # fallback for episodes whose date we cannot line up.
    by_title_date = {}
    by_title = {}
    dupes = set()

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        enc = item.find("enclosure")
        if not title or enc is None:
            continue
        url = enc.attrib.get("url")
        if not url:
            continue

        pub = (item.findtext("pubDate") or "").strip()
        day = None
        if pub:
            try:
                day = parsedate_to_datetime(pub).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                day = None
        if day:
            by_title_date[(title, day)] = url

        if title in by_title:
            dupes.add(title)
        by_title[title] = url

    return by_title_date, by_title, dupes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- video_data.json will not be written ===\n")

    by_title_date, by_title, dupes = fetch_items()
    print("rss items with audio:", len(by_title_date), "keyed by (title, date)")
    print("distinct titles     :", len(by_title))
    if dupes:
        print("DUPLICATE TITLES in feed (%d) -- these need the date to resolve:" % len(dupes))
        for t in sorted(dupes):
            print("   ", t[:70])

    video_data = utils.get_video_data()
    ids = sorted(k for k in video_data if k.startswith("XXXXXX"))

    added = updated = unchanged = missing = 0
    misses = []

    for yt_id in ids:
        title = (video_data[yt_id].get("title") or "").strip()
        day = (video_data[yt_id].get("date")
               or video_data[yt_id].get("upload_date") or "").strip()

        audio = by_title_date.get((title, day))
        if audio is None and title in dupes:
            # ambiguous and the date did not line up: refuse to guess
            missing += 1
            misses.append((yt_id, "AMBIGUOUS duplicate title, date " + (day or "?")))
            continue
        if audio is None:
            audio = by_title.get(title)
        if not audio:
            missing += 1
            misses.append((yt_id, title[:60]))
            continue

        current = video_data[yt_id].get("audio_url")
        if current == audio:
            unchanged += 1
            continue
        if current:
            updated += 1
        else:
            added += 1
            if added <= 3:
                print("  %s -> %s" % (yt_id, audio[:95]))
        video_data[yt_id]["audio_url"] = audio

    print()
    print("podcast episodes :", len(ids))
    print("audio_url added  :", added)
    print("audio_url updated:", updated)
    print("already current  :", unchanged)
    print("no feed match    :", missing)
    if misses:
        print("\nunmatched (title not in feed):")
        for yt_id, t in misses[:10]:
            print("   %s  %s" % (yt_id, t))

    if args.apply and (added or updated):
        utils.save_video_data(video_data)
        print("\nWROTE video_data.json (%d added, %d updated)." % (added, updated))
    elif not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
