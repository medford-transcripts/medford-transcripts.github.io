#!/usr/bin/env python3
import os
import re
import json
import time
import shutil
import subprocess
from pathlib import Path
import dateutil.parser as dparser
import datetime

import requests
from internetarchive import get_item
import utils

# ---------- CONFIG ----------

UPLOADER_EMAIL = "medfordcommunitymedia@gmail.com"
SEARCH_URL = "https://archive.org/advancedsearch.php"

OUTDIR = Path("./")            # root for final MP3 directories
TEMPDIR = Path("medford_tmp")             # temp downloads
INDEX_PATH = Path("medford_index.json")   # identifier -> integer mapping

ROWS_PER_PAGE = 200
SLEEP_BETWEEN_ITEMS = 1

OUTDIR.mkdir(exist_ok=True)
TEMPDIR.mkdir(exist_ok=True)


# ---------- INDEX & METADATA HELPERS ----------

def load_json(path, default):
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)


def load_index():
    return load_json(INDEX_PATH, {})


def save_index(idx):
    save_json(INDEX_PATH, idx)

def get_enum_number(identifier, index):
    """
    Stable enumeration: assign next integer if identifier not in index.
    """
    if identifier in index:
        return index[identifier]
    next_id = max(index.values()) + 1 if index else 1
    index[identifier] = next_id
    return next_id


def enum_string(num: int) -> str:
    """
    Build ID: MCM + 8-digit zero-padded integer.
    """
    return "MCM" + str(num).zfill(8)


def normalize_upload_date(publicdate: str) -> str:
    """
    Convert publicdate (e.g. '2023-07-25T04:00:00Z') -> '2023-07-25'.
    Fall back to '1970-01-01' if missing.
    """
    if not publicdate:
        return "1970-01-01"
    # First 10 chars are usually YYYY-MM-DD
    return publicdate[:10]


def parse_air_date(title: str, fallback: str) -> str:
    """
    Parse an air date from the title using dateutil with fuzzy parsing.
    Returns fallback (usually upload_date) if parsing fails.
    Normalizes output to YYYY-MM-DD.
    """
    if not title:
        return fallback

    try:
        dt = dparser.parse(title, fuzzy=True, default=None)
        # If year < 1930, assume 2000's (common in muni meeting titles like 07-25-23)
        year = dt.year
        if year < 1930:
            year += 2000
            dt = dt.replace(year=year)

        return dt.strftime("%Y-%m-%d")
    except Exception:
        return fallback


def get_audio_duration_seconds(path: Path) -> int:
    """
    Use ffprobe to get duration in seconds (rounded).
    Returns 0 on failure.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        val = res.stdout.strip()
        if not val:
            return 0
        return int(round(float(val)))
    except Exception:
        return 0


def get_view_count(item) -> int:
    """
    Use 'downloads' from item.metadata if available; else 10.
    """
    meta = item.metadata or {}
    downloads = meta.get("downloads")
    try:
        if downloads is not None:
            return int(downloads)
    except Exception:
        pass
    return 10


# ---------- FILE SELECTION & DOWNLOAD ----------

def choose_best_audio_file(item):
    """
    Choose the 'best' audio derivative (MP3/OGG). Return filename or None.
    """
    candidates = []
    for f in item.files:
        fmt = (f.get("format") or "").lower()
        if "mp3" in fmt or "ogg" in fmt:
            candidates.append(f)

    if not candidates:
        return None

    def score(f):
        fmt = (f.get("format") or "").lower()
        if "128kbps" in fmt:
            return 3
        if "vbr mp3" in fmt:
            return 2
        if "mp3" in fmt:
            return 1
        if "ogg" in fmt:
            return 0.5
        return 0

    candidates.sort(key=score, reverse=True)
    return candidates[0]["name"]


def choose_best_video_file(item):
    """
    Choose a reasonable video file for audio extraction. Return filename or None.
    """
    video_exts = (".mp4", ".m4v", ".mkv", ".mov", ".mpg", ".mpeg", ".avi", ".ts")
    candidates = []

    for f in item.files:
        name = (f.get("name") or "")
        fmt = (f.get("format") or "").lower()
        lname = name.lower()

        if lname.endswith(video_exts):
            candidates.append(f)
            continue

        if any(v in fmt for v in ["h.264", "mpeg4", "quicktime", "webm", "matroska"]):
            candidates.append(f)

    if not candidates:
        return None

    def score(f):
        name = (f.get("name") or "").lower()
        fmt = (f.get("format") or "").lower()
        if name.endswith((".mp4", ".m4v")) or "h.264" in fmt or "mpeg4" in fmt:
            return 3
        if "quicktime" in fmt or name.endswith(".mov"):
            return 2
        return 1

    candidates.sort(key=score, reverse=True)
    return candidates[0]["name"]


def download_file_from_item(item, filename, dest_dir: Path) -> Path:
    """
    Use item.download() to fetch a single file into dest_dir/identifier/filename.
    Returns local path.
    """
    identifier = item.identifier
    item.download(
        destdir=str(dest_dir),
        files=[filename],
        ignore_existing=True,
        verbose=True,
    )
    return dest_dir / identifier / filename


def ffmpeg_extract_audio(video_path: Path, out_mp3: Path):
    """
    Use ffmpeg to extract audio as MP3 into out_mp3, then delete video file and its dir.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "192k",
        str(out_mp3),
    ]
    print("  ffmpeg:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # cleanup
    try:
        video_path.unlink()
    except FileNotFoundError:
        pass
    try:
        video_path.parent.rmdir()
    except OSError:
        pass

def add_metadata():
    index = load_index()
    video_data = utils.get_video_data()

    query = f'uploader:"{UPLOADER_EMAIL}" AND mediatype:(movies)'
    page = 1

    while True:
        params = {
            "q": query,
            "fl[]": ["identifier", "title", "publicdate"],
            "rows": ROWS_PER_PAGE,
            "page": page,
            "output": "json",
            "sort[]": "publicdate asc",
        }

        r = requests.get(SEARCH_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        response = data.get("response", {})
        docs = response.get("docs", [])
        if not docs:
            break

        num_found = response.get("numFound", 0)

        for doc in docs:
            identifier = doc["identifier"]
            search_title = doc.get("title", "")
            publicdate_raw = doc.get("publicdate", "")
            upload_date = normalize_upload_date(publicdate_raw)

            enum_num = get_enum_number(identifier, index)
            enum_id = enum_string(enum_num)

            print(f"\n[{enum_id}] {identifier} | {search_title}")

            # If we've already created an entry for this enum_id, skip it.
            if enum_id in video_data:
                print("  video_data entry already exists; skipping metadata update.")
                # Still persist the index in case it changed
                save_index(index)
                continue

            # We still fetch the item for metadata, but DO NOT download any files.
            item = get_item(identifier)
            item_meta = item.metadata or {}
            item_title = item_meta.get("title") or search_title or identifier

            # No audio download: just set duration=0 (or leave it out entirely if you prefer)
            duration = 0
            view_count = get_view_count(item)
            air_date = parse_air_date(item_title, upload_date)
            url = f"https://archive.org/details/{identifier}"

            video_data[enum_id] = {
                "title": item_title,
                "channel": "MCM Archive",
                "duration": duration,
                "upload_date": upload_date,
                "view_count": view_count,
                "date": air_date,
                "url": url,
            }

            utils.save_video_data(video_data)
            save_index(index)
            time.sleep(SLEEP_BETWEEN_ITEMS)

        if page * ROWS_PER_PAGE >= num_found:
            break
        page += 1


# ---------- MAIN ----------

def main():


    index = load_index()
    video_data = utils.get_video_data()

    query = f'uploader:"{UPLOADER_EMAIL}" AND mediatype:(movies)'
    page = 1

    while True:
        params = {
            "q": query,
            "fl[]": ["identifier", "title", "publicdate"],
            "rows": ROWS_PER_PAGE,
            "page": page,
            "output": "json",
            "sort[]": "publicdate asc",
        }

        r = requests.get(SEARCH_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        response = data.get("response", {})
        docs = response.get("docs", [])
        if not docs:
            break

        num_found = response.get("numFound", 0)

        for doc in docs:

            # for profiling...
            #t0 = datetime.datetime.utcnow()
            #print(3,(datetime.datetime.utcnow()-t0).total_seconds())

            identifier = doc["identifier"]
            search_title = doc.get("title", "")
            publicdate_raw = doc.get("publicdate", "")
            upload_date = normalize_upload_date(publicdate_raw)

            enum_num = get_enum_number(identifier, index)
            enum_id = enum_string(enum_num)

            if "skip" in video_data[enum_id].keys():
                if video_data[enum_id]["skip"]: continue

            # Directory & filename based on upload_date + enum_id
            dir_name = f"{upload_date}_{enum_id}"
            subdir = OUTDIR / dir_name
            subdir.mkdir(parents=True, exist_ok=True)

            mp3_name = f"{upload_date}_{enum_id}.mp3"
            final_mp3 = subdir / mp3_name

            # we've already got good audio for this video
            if video_data[enum_id]["duration"] != 0 and final_mp3.exists():
                #print(f"  MP3 already exists: {final_mp3}")
                continue

            #print(f"\n[{enum_id}] {identifier} | {search_title}")

            # We always need the item for metadata, even if MP3 already exists
            item = get_item(identifier)
            item_title = (item.metadata or {}).get("title") or search_title or identifier

            # 1) Try to download existing audio derivative
            audio_name = choose_best_audio_file(item)
            if audio_name:
                print(f"  Found audio derivative: {audio_name}")
                local_audio = download_file_from_item(item, audio_name, TEMPDIR)
                shutil.move(str(local_audio), str(final_mp3))
                # clean temp dir
                
                temp_dir_for_item = local_audio.parent
                if temp_dir_for_item.exists():
                    shutil.rmtree(temp_dir_for_item)

                print(f"  Saved audio as {final_mp3}")
            else:
                # 2) Fallback: download video + ffmpeg
                print("  No audio derivative; falling back to video + ffmpeg.")
                video_name = choose_best_video_file(item)
                if not video_name:
                    print("  No suitable video file found; skipping.")
                    # still record in index but no mp3/metadata
                    save_index(index)
                    continue

                print(f"  Downloading video: {video_name}")
                local_video = download_file_from_item(item, video_name, TEMPDIR)
                print(f"  Extracting audio -> {final_mp3}")
                try:
                    ffmpeg_extract_audio(local_video, final_mp3)
                    print(f"  Saved audio as {final_mp3}")
                except subprocess.CalledProcessError as e:
                    print(f"  ffmpeg failed: {e}")
                    if final_mp3.exists():
                        final_mp3.unlink()
                    save_index(index)
                    continue

            # At this point, if final_mp3 exists, we can populate metadata
            if final_mp3.exists():
                duration = get_audio_duration_seconds(final_mp3)
                view_count = get_view_count(item)
                air_date = parse_air_date(item_title, upload_date)
                url = f"https://archive.org/details/{identifier}"

                video_data = utils.get_video_data()
                video_data[enum_id] = {
                    "title": item_title,
                    "channel": "MCM Archive",
                    "duration": duration,
                    "upload_date": upload_date,
                    "view_count": view_count,
                    "date": air_date,
                    "url": url,
                }
                utils.save_video_data(video_data)

            # Persist index after each item
            save_index(index)
            time.sleep(SLEEP_BETWEEN_ITEMS)

        if page * ROWS_PER_PAGE >= num_found:
            break
        page += 1


if __name__ == "__main__":

    #add_metadata()

    main()
