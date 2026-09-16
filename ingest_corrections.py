"""
Ingest correction submissions into a local review queue.

NO GOOGLE AUTHENTICATION REQUIRED. The Sheets API would need OAuth or a
service account, but a LINK-SHARED responses sheet exports CSV over plain
HTTP, which is all this needs:

    https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv

(No "publish to web" step is necessary as long as the sheet is shared with
"anyone with the link can view" -- which is also the caveat: anyone holding
that link can read the responses. This form collects no email addresses and
the content is public-transcript corrections, so the exposure is minimal. If
that ever stops being acceptable, download the CSV by hand and pass a path --
both work identically.)

    python ingest_corrections.py --url "https://docs.google.com/spreadsheets/d/<ID>/export?format=csv"
    python ingest_corrections.py --csv responses.csv

Submissions are NEVER applied automatically. This writes them to
corrections_queue.json with status "pending" for human review. A public write
path into a civic record is an abuse target, and these corrections are meant to
become ground truth for the eval set -- unreviewed data would defeat that.

Deduplication is by content hash, so re-ingesting the same sheet repeatedly is
safe and only ever adds genuinely new rows. Existing review decisions are
preserved.
"""

import argparse
import csv
import hashlib
import glob
import io
import json
import os
import re
import sys
import urllib.request

QUEUE = "corrections_queue.json"

# The sheet's column headers are the QUESTION TEXT, which the owner may reword
# at any time. Match loosely on keywords rather than pinning exact strings.
COLUMN_HINTS = [
    ("kind",          ["kind", "what kind", "type of correction"]),
    ("video_id",      ["video id", "video_id"]),
    ("video_title",   ["video title", "title"]),
    ("timestamp",     ["timestamp", "seconds"]),
    ("speaker",       ["speaker"]),
    ("original_text", ["original text", "original"]),
    ("page_url",      ["page url", "url", "link"]),
    ("suggestion",    ["instead", "corrected", "suggestion", "should it say"]),
    ("submitted_at",  ["timestamp of submission", "submitted"]),
]


def map_columns(headers):
    """Best-effort mapping of sheet headers onto our schema."""
    out, used = {}, set()
    low = [(h, (h or "").strip().lower()) for h in headers]

    # Google always puts its own submission time in the first column, named
    # "Timestamp" -- which collides with OUR timestamp question. Claim it first
    # so the media timestamp does not get bound to it.
    if low and low[0][1].startswith("timestamp"):
        out["submitted_at"] = low[0][0]
        used.add(low[0][0])

    for field, hints in COLUMN_HINTS:
        if field in out:
            continue
        for header, l in low:
            if header in used or not l:
                continue
            if any(h in l for h in hints):
                out[field] = header
                used.add(header)
                break
    return out


def load_rows(text):
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    mapping = map_columns(headers)
    missing = [f for f, _ in COLUMN_HINTS if f not in mapping]
    return list(reader), mapping, headers, missing


def row_id(rec):
    key = "|".join(str(rec.get(k, "")) for k in
                   ("video_id", "timestamp", "kind", "suggestion", "submitted_at"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def original_speaker(video_id, timestamp):
    """The speaker label currently in the transcript at this timestamp.

    Needed because every form field is prefilled with the original and the
    contributor edits whichever is wrong -- so on a SPEAKER correction the
    'speaker' field comes back holding the CORRECTED name and the original is
    gone. Text and timestamp corrections keep both sides (original_text, and
    the pristine time in page_url#t=), so only this one needs resolving.

    Recording it at ingest makes the queue self-contained: a reviewer sees
    "SPEAKER_07 -> Zac Bears" without opening the transcript.
    """
    try:
        t = float(timestamp)
    except (TypeError, ValueError):
        return None
    hits = glob.glob("20??-??-??_" + video_id + "/*_" + video_id + ".srt")
    if not hits:
        return None

    best, best_start = None, None
    with io.open(hits[0], encoding="utf-8", errors="replace") as fp:
        start = None
        for line in fp:
            if "-->" in line:
                try:
                    hh, mm, rest = line.split()[0].split(":")
                    ss, ms = rest.split(",")
                    start = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0
                except (ValueError, IndexError):
                    start = None
            elif start is not None and line.strip().startswith("["):
                if start <= t + 0.05 and (best_start is None or start >= best_start):
                    best_start = start
                    best = line.strip().split("]")[0].lstrip("[")
    return best


def classify(rec):
    k = (rec.get("kind") or "").lower()
    if "speaker" in k:
        return "speaker"
    if "timestamp" in k or "timing" in k:
        return "timestamp"
    return "word"


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="published-to-web CSV url")
    src.add_argument("--csv", help="a downloaded CSV file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.url:
        req = urllib.request.Request(args.url, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    else:
        text = io.open(args.csv, encoding="utf-8", errors="replace").read()

    rows, mapping, headers, missing = load_rows(text)
    print("sheet columns :", len(headers))
    print("rows          :", len(rows))
    print("\ncolumn mapping:")
    for field, _ in COLUMN_HINTS:
        print("   %-14s <- %s" % (field, mapping.get(field, "  (UNMATCHED)")))
    if missing:
        print("\nWARNING: unmatched fields:", ", ".join(missing))
        print("The sheet headers are the question text; if you reworded a")
        print("question, add a hint for it in COLUMN_HINTS.")

    queue = {"_comment": "Correction submissions pending review. Never auto-applied.",
             "items": {}}
    if os.path.exists(QUEUE):
        with open(QUEUE, encoding="utf-8") as fp:
            queue = json.load(fp)
    items = queue.setdefault("items", {})

    added = dupes = 0
    for raw in rows:
        rec = {field: (raw.get(col) or "").strip()
               for field, col in mapping.items()}
        if not any(rec.values()):
            continue
        rid = row_id(rec)
        if rid in items:
            dupes += 1
            continue
        rec["target"] = classify(rec)
        if rec["target"] == "speaker":
            was = original_speaker(rec.get("video_id"), rec.get("timestamp"))
            if was:
                rec["original_speaker"] = was
        rec["status"] = "pending"
        items[rid] = rec
        added += 1

    print("\nnew submissions : %d" % added)
    print("already queued  : %d" % dupes)
    pend = sum(1 for v in items.values() if v.get("status") == "pending")
    print("pending review  : %d of %d total" % (pend, len(items)))

    by_target = {}
    for v in items.values():
        if v.get("status") == "pending":
            by_target[v.get("target")] = by_target.get(v.get("target"), 0) + 1
    if by_target:
        print("  by kind:", by_target)

    for v in list(items.values())[:3]:
        print("\n  %-9s %-12s t=%-9s %s" % (v.get("target"), v.get("video_id"),
                                            v.get("timestamp"), v.get("speaker")))
        if v.get("target") == "speaker":
            print("     speaker: %s -> %s"
                  % (v.get("original_speaker") or "?", v.get("speaker")))
        elif v.get("target") == "timestamp":
            print("     time: %s (see page_url for the original)" % v.get("timestamp"))
        else:
            print("     was: %s" % (v.get("original_text") or "")[:88])
            print("     fix: %s" % (v.get("suggestion") or "")[:88])

    if args.dry_run:
        print("\nDry run; %s not written." % QUEUE)
    else:
        with open(QUEUE, "w", encoding="utf-8") as fp:
            json.dump(queue, fp, indent=2)
        print("\nwrote", QUEUE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
