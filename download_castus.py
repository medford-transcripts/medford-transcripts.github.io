"""
Fetch Medford Community Media meetings from their Castus VOD platform.

WHY THIS EXISTS. MCM's Castus site is their PRIMARY publication; the archive.org
collection is periodic bulk dumps for posterity, which is why archive.org
uploads arrive in bursts (218/265/239 items in Jul-Sep 2024, then dribbles,
then nothing after 2026-01) while Castus is current to this week.

Because nothing here knew Castus existed, 22 municipal bodies looked like they
had stopped being recorded in late 2025 -- Zoning Board of Appeals,
Conservation Commission, Historical Commission, Board of Health, Community
Preservation, Traffic Commission and more. They had not. They moved.

Measured 2026-09-24: 1,000 retrievable items, of which 534 we already hold
(406 via MCM Archive, 91 from the city's own channel) and 393 are new -- 493
hours, on top of a 1,096-hour backlog.

THE API is undocumented and was read out of the site's minified bundle. It
takes no authentication:

    GET  https://837sc3bew0.execute-api.us-west-2.amazonaws.com/<company>
         -> {"user": "<24-hex station id>", ...}
    POST {BASE}/upload/search  {"_id": <station>, "search": "", "limit": N}
         -> response.payload.files[]
    POST {BASE}/upload/get     {"file": <video _id>, "type": "video"}
         -> response.payload.data = a plain CloudFront MP4 URL, unsigned

Being undocumented, it can change without notice. Every call therefore
verifies the shape it got and raises rather than returning an empty list: a
scraper that silently yields nothing is how the MCM gap hid for months (see
download_mcm.add_metadata, which was never called and reported nothing).

PAGING: the catalogue comes from the site's own "All Videos" endpoint, which
reports a true total in `record` (2,606 on 2026-09-24). The obvious-looking
/upload/search caps at 1,000 and ignores every paging parameter, so it quietly
returned a third of the catalogue.

Usage:
    python download_castus.py --list          # what is there, what is new
    python download_castus.py --register      # add new items to video_data
    python download_castus.py --download      # fetch audio for registered ids
"""

import argparse
import datetime
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

import utils
import download_mcm

CONFIG_API = "https://837sc3bew0.execute-api.us-west-2.amazonaws.com"
BASE = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com"
# The PAGINATED catalogue, used by the site's "All Videos" page. Found by
# reading Components/NewFuncComponents/AllVideos.js out of the published source
# map -- cloud.castus.tv ships .map files, so the real source is readable and
# guessing at endpoints is unnecessary.
ALL_API = "https://tf4pr3wftk.execute-api.us-west-2.amazonaws.com/default/api/all"
PAGE_SIZE = 500
COMPANY = "medford"
CHANNEL = "MCM Castus"
INDEX_PATH = Path("castus_index.json")
OUTDIR = Path("audio")
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
           "Origin": "https://cloud.castus.tv"}
PREFIX = "CAS"
LIST_LIMIT = 1000

TITLE_DATE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})")


def station_id(company=COMPANY):
    r = requests.get("%s/%s" % (CONFIG_API, company), headers=HEADERS, timeout=30)
    r.raise_for_status()
    uid = r.json().get("user")
    if not uid:
        raise RuntimeError("Castus config for %r has no 'user'; the API changed" % company)
    return uid


def catalog(uid=None, page_size=PAGE_SIZE):
    """Every item the station publishes, paged.

    WAS /upload/search, which caps at 1,000 and ignores skip/offset/page/parent
    -- so it silently returned a third of the catalogue and no amount of
    parameter-guessing moved it. The site's own "All Videos" page uses a
    different host entirely and reports the true total in `record`: 2,606 as of
    2026-09-24, against the 1,000 the other endpoint would admit to.

    Paging is 1-based; page=0 returns HTTP 502.
    """
    uid = uid or station_id()
    out, page, total = [], 1, None
    while True:
        r = requests.post(ALL_API, headers=HEADERS,
                          json={"_id": uid, "page": page, "results": page_size},
                          timeout=180)
        r.raise_for_status()
        d = r.json()
        batch = d.get("allFiles")
        if batch is None:
            raise RuntimeError("Castus /api/all has no allFiles; the API changed")
        if total is None:
            total = d.get("record")
            if total is None:
                raise RuntimeError("Castus /api/all reported no record count")
        out += batch
        if not batch or len(out) >= total:
            break
        page += 1
    if total is not None and len(out) < total:
        print("WARNING: collected %d of %d items the API reports" % (len(out), total))
    return out


def title_of(f):
    return ((f.get("metadata") or {}).get("title") or "").strip()


def duration_of(f):
    try:
        return int(float((f.get("metadata") or {}).get("duration") or 0))
    except (TypeError, ValueError):
        return 0


def meeting_date(f):
    """The date the meeting HAPPENED, from the title; else the upload date.

    Castus `date` is when the file was posted -- "Conservation Commission
    09/16/26" is dated 2026-09-18. Using the upload date as the meeting date
    misaligns everything that joins on it: agendas, duplicate detection, the
    committee pages.
    """
    m = TITLE_DATE.search(title_of(f))
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            pass
    return (f.get("date") or "")[:10]


def upload_date(f):
    return (f.get("date") or "")[:10]


def enumeration_order(files):
    """Catalogue order for MINTING ids: oldest upload first.

    THE ID NUMBER IS A PUBLIC, PERMANENT NAME -- it is the directory on disk
    and the URL on the site -- so the order it is handed out in is a decision,
    not an implementation detail. Every other source here numbers by upload
    date ascending: download_mcm asks archive.org for "publicdate asc" and the
    podcast ids follow episode order, so MCM00000001 and XXXXXX00001 are the
    OLDEST items and the numbers read as a timeline.

    Castus was enumerated in raw API order, which is newest-first, so the
    first import ran the convention backwards: CAS00000001 was 2026-09-21,
    the most recent item in the catalogue, and CAS00002534 the oldest.
    Sorting here puts Castus on the same footing.

    The tie-break on castus_id matters: several items share an upload date,
    and without a deterministic second key the same catalogue could enumerate
    two ways on two runs. The id only has to be stable, not meaningful.
    """
    return sorted(files, key=lambda f: (upload_date(f) or meeting_date(f) or "9999",
                                        f.get("_id") or ""))


def enum_id(castus_id, index):
    """Stable CAS id for a Castus item.

    The mapping lives in castus_index.json (tracked in git), keyed by the
    Castus object id and NOT derived from video_data.json -- video_data is a
    metadata cache that gets rebuilt, and an id that changed when it was
    rebuilt would rename published URLs underneath readers. Once minted, a
    number is never reissued or reordered: new items append.
    """
    if castus_id in index:
        n = index[castus_id]
    else:
        n = (max(index.values()) + 1) if index else 1
        index[castus_id] = n
    return PREFIX + str(n).zfill(8)


def load_index():
    try:
        with io.open(INDEX_PATH, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {}


def save_index(index):
    tmp = str(INDEX_PATH) + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
        json.dump(index, fp, indent=1, sort_keys=True)
    os.replace(tmp, str(INDEX_PATH))


# The CloudFront object an entry's video lives at. video_url() below is the
# authoritative lookup but needs a live API round-trip, which a page render
# cannot afford; this is the pattern that lookup returns, verified identical
# for every item sampled. Unsigned and publicly readable (HTTP 200,
# video/mp4), so it works in a plain <video> tag.
MP4_PATTERN = "https://dlttx48mxf9m3.cloudfront.net/outputs/%s/Default/MP4/out_1080.mp4"


def mp4_url(entry):
    """Playable URL for a registered Castus entry, or None.

    Prefers a resolved URL if one was stored; otherwise derives it. Derivation
    is a guess about an undocumented vendor layout -- if Castus ever changes
    it, every Castus page loses its player at once, which is at least loud.
    """
    if not entry:
        return None
    if entry.get("video_url"):
        return entry["video_url"]
    cid = entry.get("castus_id")
    return (MP4_PATTERN % cid) if cid else None


def video_url(castus_id):
    r = requests.post(BASE + "/upload/get", headers=HEADERS,
                      json={"file": castus_id, "type": "video", "user": ""}, timeout=60)
    r.raise_for_status()
    data = ((r.json().get("response") or {}).get("payload") or {}).get("data")
    if not data or data == "/":
        return None
    return data.split("?")[0]


def add_metadata(dry_run=False):
    """Register items not already in video_data.

    Registration and download are separate, deliberately: download_mcm had them
    fused and its guard rejected any id it had just minted, so no new item
    could ever enter. Nothing new here can be skipped for not already existing.
    """
    index = load_index()
    video_data = utils.get_video_data()
    files = enumeration_order(catalog())
    print("castus catalogue: %d items" % len(files))

    added = 0
    for f in files:
        cid = f.get("_id")
        title = title_of(f)
        if not cid or not title:
            continue
        yt_id = enum_id(cid, index)
        if yt_id in video_data:
            continue
        up = upload_date(f) or meeting_date(f)
        if not up:
            continue
        video_data[yt_id] = {
            "title": title,
            "channel": CHANNEL,
            "duration": duration_of(f),
            "upload_date": up,
            "date": meeting_date(f),
            "url": "https://cloud.castus.tv/vod/%s/?page=HOME&video=%s" % (COMPANY, cid),
            "castus_id": cid,
            "view_count": 0,
        }
        # Classify NOW. identify_duplicate_videos matches on "same meeting type
        # and date", so an entry without a type can never be recognised as a
        # duplicate of a copy we already hold -- the first run registered 927
        # items, found 642 pairs and skipped none of them for exactly this
        # reason.
        try:
            video_data[yt_id]["meeting_type"] = utils.get_meeting_type(video_data[yt_id])
        except Exception:
            video_data[yt_id]["meeting_type"] = None
        added += 1
        print("  + %-12s %s  %s" % (yt_id, video_data[yt_id]["date"], title[:54]))
    print("new entries: %d" % added)
    if dry_run:
        print("dry run; nothing written")
        return added
    if added:
        utils.save_video_data(video_data)
    save_index(index)
    return added


def download(yt_id, video_data=None):
    """Fetch one registered item's audio into audio/<upload_date>_<id>.mp3."""
    video_data = video_data or utils.get_video_data()
    entry = video_data.get(yt_id)
    if not entry or not entry.get("castus_id"):
        print("%s is not a Castus item" % yt_id)
        return False
    base = entry["upload_date"] + "_" + yt_id
    mp3 = OUTDIR / (base + ".mp3")
    if mp3.exists() and mp3.stat().st_size > 0:
        return True
    url = video_url(entry["castus_id"])
    if not url:
        print("  no playable URL for %s" % yt_id)
        return False
    OUTDIR.mkdir(exist_ok=True)
    tmpdir = OUTDIR / ("_castus_" + yt_id)
    tmpdir.mkdir(exist_ok=True)
    mp4 = tmpdir / (base + ".mp4")
    print("  downloading %s (%s)" % (yt_id, url.rsplit("/", 1)[-1]))
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(mp4, "wb") as fp:
            for chunk in r.iter_content(1 << 20):
                fp.write(chunk)
    download_mcm.ffmpeg_extract_audio(mp4, mp3)
    return mp3.exists()


def main(limit=0):
    video_data = utils.get_video_data()
    ours = [(k, v) for k, v in video_data.items()
            if k.startswith(PREFIX) and v.get("castus_id")]
    todo = []
    for yt_id, e in ours:
        if e.get("skip"):
            continue
        base = e.get("upload_date", "") + "_" + yt_id
        if not (OUTDIR / (base + ".mp3")).exists():
            todo.append(yt_id)
    print("castus items registered: %d, awaiting audio: %d" % (len(ours), len(todo)))
    done = 0
    for yt_id in todo:
        if limit and done >= limit:
            break
        try:
            if download(yt_id, video_data):
                done += 1
        except Exception as e:
            print("  FAILED %s: %s" % (yt_id, str(e)[:120]))
    print("downloaded %d" % done)
    return done


def report():
    files = catalog()
    vd = utils.get_video_data()
    known = {v.get("castus_id") for v in vd.values() if v.get("castus_id")}
    import collections
    years = collections.Counter(meeting_date(f)[:4] for f in files)
    print("catalogue : %d items, %.0f hours"
          % (len(files), sum(duration_of(f) for f in files) / 3600.0))
    print("by year   :", dict(sorted(years.items())))
    print("registered here already: %d" % sum(1 for f in files if f.get("_id") in known))
    print("captioned : %d" % sum(1 for f in files if f.get("captioned")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.list or not (a.register or a.download):
        report()
    if a.register:
        add_metadata(dry_run=a.dry_run)
    if a.download:
        main(limit=a.limit)
