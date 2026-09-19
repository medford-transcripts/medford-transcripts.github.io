"""
Preserve videos that exist on only one channel by uploading them to the
Internet Archive.

WHY. 73 Medford meetings exist nowhere but the Mass Traction YouTube channel,
whose host pays a monthly fee and wants to retire it -- held back only because
those meetings are not archived elsewhere. 164 hours, 65 of them from 2014-2016,
which is the thinnest-covered stretch of this archive.

AND THE AUDIO IS ALREADY GONE: 0 of the 73 still have an mp3 on disk (it is
swept after transcription). Today the only surviving copy of the source is the
channel itself. If it goes down first, those meetings exist as a transcript
with nothing to verify it against and no way to ever re-transcribe them. This
is a race, not a cleanup.

archive.org is the right home: free, permanent, already where Medford
Community Media archives, and transcript-player.js already has an "archive"
backend.

HONEST TRADE-OFF: archive.org's embed exposes no reliable seek API, so a page
served from there is informational and line clicks fall back to the <a href>
timestamps. Those 73 pages lose word-level click-to-seek. That is a real
regression and much better than losing the source.

SETUP (once):
    pip install internetarchive
    ia configure            # archive.org account, free

Usage:
    python export_to_archive.py                 # dry run: what would upload
    python export_to_archive.py --limit 2 --apply
    python export_to_archive.py --apply         # all of them
    python export_to_archive.py --repoint       # after upload, point the site at it
"""

import argparse
import glob
import io
import json
import os
import subprocess
import sys
import time

import utils

WORKDIR = "archive_export"
COLLECTION = "opensource_movies"      # the open collection; curators may re-home it
CREATOR = "Mass Traction"


def solo_videos(video_data, channel_match="Mass Traction"):
    """Videos on one channel with no duplicate anywhere else."""
    out = []
    for yt_id, entry in video_data.items():
        if channel_match not in (entry.get("channel") or ""):
            continue
        if entry.get("duplicate_id"):
            continue                      # another copy exists; not at risk
        out.append((yt_id, entry))
    out.sort(key=lambda kv: kv[1].get("date") or "")
    return out


def identifier_for(yt_id, entry):
    """A stable archive.org identifier.

    Includes the YouTube id so the mapping back is unambiguous and a re-run
    cannot create a second item for the same video.
    """
    date = (utils.meeting_date(entry) or "undated").replace("-", "")
    return "medford-%s-%s" % (date, yt_id)


def already_uploaded(identifier):
    try:
        from internetarchive import get_item
        return bool((get_item(identifier).metadata or {}))
    except Exception:
        return False


def download(yt_id, entry):
    """Fetch the source video. Returns a path or None."""
    os.makedirs(WORKDIR, exist_ok=True)
    target = os.path.join(WORKDIR, yt_id + ".mp4")
    if os.path.exists(target) and os.path.getsize(target) > 1_000_000:
        return target
    cmd = [sys.executable, "-m", "yt_dlp",
           "--cookies-from-browser", "firefox",
           "-f", "bv*+ba/b", "--merge-output-format", "mp4",
           "-o", target, "https://youtu.be/" + yt_id]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(target):
        print("    download failed: %s" % (result.stderr or "")[-200:].strip())
        return None
    return target


def upload(path, identifier, yt_id, entry):
    from internetarchive import upload as ia_upload
    meta = {
        "title": entry.get("title") or yt_id,
        "mediatype": "movies",
        "collection": COLLECTION,
        "date": utils.meeting_date(entry) or entry.get("upload_date"),
        "creator": entry.get("channel") or CREATOR,
        "subject": ["Medford", "Massachusetts", "city council",
                    "public meeting", "local government"],
        "description": (
            "Public meeting of the City of Medford, Massachusetts. "
            "Originally published on YouTube as %s. Archived to preserve the "
            "public record. A transcript is available at "
            "https://medford-transcripts.github.io/" % yt_id),
        "originalurl": "https://youtu.be/" + yt_id,
    }
    ia_upload(identifier, files=[path], metadata=meta, retries=3,
              retries_sleep=10, verbose=False)
    return "https://archive.org/details/" + identifier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually download and upload")
    ap.add_argument("--limit", type=int, default=0, help="stop after N (try 1-2 first)")
    ap.add_argument("--channel", default="Mass Traction")
    ap.add_argument("--repoint", action="store_true",
                    help="point video_data at the archive.org copy (after upload)")
    args = ap.parse_args()

    video_data = utils.get_video_data()
    targets = solo_videos(video_data, args.channel)
    hours = sum((e.get("duration") or 0) for _, e in targets) / 3600.0
    print("videos on '%s' with no copy elsewhere: %d (%.0f hours)"
          % (args.channel, len(targets), hours))

    mapping_file = "archive_export.json"
    mapping = {}
    if os.path.exists(mapping_file):
        with io.open(mapping_file, encoding="utf-8") as fp:
            mapping = json.load(fp)

    if args.repoint:
        fresh = utils.get_video_data()
        n = 0
        for yt_id, url in mapping.items():
            if yt_id in fresh and fresh[yt_id].get("archive_url") != url:
                fresh[yt_id]["archive_url"] = url
                n += 1
        utils.save_video_data(fresh)
        print("repointed %d entries at their archive.org copy" % n)
        print("regenerate their pages so the player uses the archive backend")
        return 0

    if not args.apply:
        for yt_id, entry in targets[:12]:
            print("  %-12s %-10s %6.0f min  %s"
                  % (yt_id, utils.meeting_date(entry) or "?",
                     (entry.get("duration") or 0) / 60.0,
                     (entry.get("title") or "")[:46]))
        if len(targets) > 12:
            print("  ... and %d more" % (len(targets) - 12))
        print("\ndry run. --apply downloads and uploads; start with --limit 2")
        return 0

    done = failed = skipped = 0
    for yt_id, entry in targets:
        if args.limit and done >= args.limit:
            break
        identifier = identifier_for(yt_id, entry)
        if yt_id in mapping:
            skipped += 1
            continue
        print("\n%s  %s" % (yt_id, (entry.get("title") or "")[:54]))
        if already_uploaded(identifier):
            print("    already on archive.org as %s" % identifier)
            mapping[yt_id] = "https://archive.org/details/" + identifier
            skipped += 1
        else:
            path = download(yt_id, entry)
            if not path:
                failed += 1
                continue
            print("    downloaded %.0f MB, uploading as %s"
                  % (os.path.getsize(path) / 1048576.0, identifier))
            try:
                mapping[yt_id] = upload(path, identifier, yt_id, entry)
                done += 1
                os.remove(path)          # the point is archive.org, not local disk
            except Exception as err:
                print("    upload failed: %s" % err)
                failed += 1
                continue
        # write after every item: a long run must not lose its record on a crash
        with io.open(mapping_file, "w", encoding="utf-8") as fp:
            json.dump(mapping, fp, indent=2, sort_keys=True)
        time.sleep(2)                    # be a polite client

    print("\nuploaded %d, already present %d, failed %d" % (done, skipped, failed))
    print("mapping in %s; run --repoint to point the site at the copies" % mapping_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
