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


def original_timestamp(page_url):
    """The pristine timestamp, carried at full precision in page_url#t=."""
    m = re.search(r"[#&]t=([0-9.]+)", page_url or "")
    return m.group(1) if m else None


TURN_RE = re.compile(r"^\s*\[([^\]]{1,60})\]\s*:\s*(.*)$")


def parse_turns(text):
    """Parse a correction written as multiple speaker turns, or return None.

    The most valuable correction shape is SPLITTING one run-on segment into
    several turns -- a roll call being the canonical case, where diarization
    collapses "Councilor Bears? / Present. / Councilor Collins? / Present."
    into a single speaker. Both hand corrections found in the archive were
    exactly this.

    Convention: one turn per line, written as
        [Name]: what they said
    The prefilled text carries NO speaker prefix, so the presence of labelled
    lines is an unambiguous signal that a split was intended.

    Timings are NOT assigned here. At apply time the split points can be
    aligned to real word boundaries using the per-word timings in model.pkl
    (see make_word_times.py), which is far better than interpolating evenly
    across the segment.
    """
    if not text or "[" not in text:
        return None
    turns = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = TURN_RE.match(raw)
        if not m:
            # a stray unlabelled line means this is not a clean split;
            # treat the whole thing as ordinary replacement text
            return None
        turns.append({"speaker": m.group(1).strip(), "text": m.group(2).strip()})
    return turns or None


def classify(rec):
    """Infer WHAT was corrected by diffing against the originals.

    The form no longer asks. Every correctable field is prefilled with the
    original, so what the contributor changed IS the answer -- and asking made
    the form look harder than it is. A single submission can legitimately
    correct more than one thing, so this returns a list.
    """
    changed = []

    was_t = rec.get("original_timestamp")
    now_t = rec.get("timestamp")
    if was_t and now_t:
        try:
            if abs(float(was_t) - float(now_t)) > 0.001:
                changed.append("timestamp")
        except ValueError:
            if was_t.strip() != now_t.strip():
                changed.append("timestamp")

    was_s = rec.get("original_speaker")
    now_s = rec.get("speaker")
    if was_s and now_s and was_s.strip() != now_s.strip():
        changed.append("speaker")

    was_x = (rec.get("original_text") or "").strip()
    now_x = (rec.get("suggestion") or "").strip()
    if was_x and now_x and was_x != now_x:
        # a correction written as several [Name]: lines is a SPLIT of one
        # segment into multiple speaker turns, not a text replacement
        turns = parse_turns(now_x)
        if turns and len(turns) > 1:
            rec["turns"] = turns
            changed.append("split")
        else:
            changed.append("text")

    return changed or ["none"]


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
        # resolve the originals BEFORE classifying -- the diff depends on them
        rec["original_timestamp"] = original_timestamp(rec.get("page_url"))
        was = original_speaker(rec.get("video_id"),
                               rec["original_timestamp"] or rec.get("timestamp"))
        if was:
            rec["original_speaker"] = was
        rec["target"] = classify(rec)
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
            for t in (v.get("target") or ["none"]):
                by_target[t] = by_target.get(t, 0) + 1
    if by_target:
        print("  by kind:", by_target)

    for v in list(items.values())[:3]:
        tg = v.get("target") or []
        print("\n  %-18s %-12s t=%s" % ("+".join(tg), v.get("video_id"),
                                        v.get("timestamp")))
        if "speaker" in tg:
            print("     speaker  : %s -> %s"
                  % (v.get("original_speaker") or "?", v.get("speaker")))
        if "timestamp" in tg:
            print("     timestamp: %s -> %s"
                  % (v.get("original_timestamp") or "?", v.get("timestamp")))
        if "split" in tg:
            print("     SPLIT into %d turns:" % len(v.get("turns") or []))
            for t in (v.get("turns") or [])[:6]:
                print("        [%s] %s" % (t["speaker"], t["text"][:60]))
        if "text" in tg:
            print("     was: %s" % (v.get("original_text") or "")[:84])
            print("     fix: %s" % (v.get("suggestion") or "")[:84])
        if tg == ["none"]:
            print("     (nothing changed -- likely a test or an accidental submit)")

    if args.dry_run:
        print("\nDry run; %s not written." % QUEUE)
    else:
        with open(QUEUE, "w", encoding="utf-8") as fp:
            json.dump(queue, fp, indent=2)
        print("\nwrote", QUEUE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
