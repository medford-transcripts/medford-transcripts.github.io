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

# Contributors whose submissions skip review. GITIGNORED ON PURPOSE: the file
# holds bearer tokens, and this repository is public, so committing it would
# publish the exact value that grants the privilege.
#
# WHAT A TOKEN IS WORTH, stated plainly so nobody mistakes it for auth. The
# token is a random value in a contributor's localStorage. It is a fine
# CORRELATION aid -- grouping one browser's submissions so a reviewer can see a
# track record -- and it is NOT authentication:
#   * anyone can copy a token they have seen and submit as its owner
#   * every token ever submitted is recorded in the responses sheet, so anyone
#     who can read that sheet can read the tokens in it
#   * a token survives no further than the browser holding it
# So this whitelist is exactly as strong as the secrecy of the responses sheet.
# While that sheet is link-shared, the honest description is "obscurity", and
# auto-accept is a convenience with a real if small integrity risk attached.
# The fix is not a better token: it is form sign-in plus a private sheet, so
# that identity is asserted by Google rather than by the submitter. See
# TRUST.md. Until then, keep an eye on what gets auto-applied.
TRUSTED = "trusted_contributors.json"

# The sheet's column headers are the QUESTION TEXT, which the owner may reword
# at any time. Match loosely on keywords rather than pinning exact strings.
COLUMN_HINTS = [
    ("suggestion",   ["corrected", "transcript", "instead", "should it say"]),
    ("reference",    ["reference", "do not edit"]),
    ("contributor",  ["contributor", "your id", "nickname"]),
    ("submitted_at", ["timestamp"]),
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


def token_of(contributor):
    """The opaque token out of a contributor tag.

    transcript-player.js sends nick + "/" + token when a display name is set,
    and a bare token otherwise. Trust decisions key on the TOKEN ONLY -- the
    nick is typed by the submitter and anyone can type any name, so matching on
    it would let a stranger inherit someone's standing by choosing their name.
    """
    who = (contributor or "").strip()
    if not who:
        return ""
    return who.rsplit("/", 1)[-1].strip()


def load_trusted(path=TRUSTED):
    """{token: label} for contributors whose edits skip review.

    Absent file means nobody is trusted, which is the right default: a missing
    whitelist must never be read as an empty allow-all.
    """
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except (ValueError, OSError) as exc:
        # Fail CLOSED and loudly. A malformed whitelist silently becoming an
        # empty one would be fine; silently becoming a permissive one would
        # not, and the operator needs to know either way.
        sys.stderr.write("WARNING: %s is unreadable (%s); trusting nobody.\n"
                         % (path, exc))
        return {}

    out = {}
    for entry in data.get("contributors", []):
        tok = (entry.get("token") or "").strip()
        if tok:
            out[tok] = (entry.get("label") or "").strip() or tok
    return out


def row_id(rec):
    key = "|".join(str(rec.get(k, "")) for k in
                   ("reference", "suggestion", "submitted_at"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def parse_reference(ref):
    """'<video_id>@<seconds>[#<contributor>]' -> (video_id, seconds, contributor).

    The contributor tag rides along on the reference when the form has no
    dedicated question for it, so the feature works without another form
    rebuild. If a 'contributor' column exists it wins.
    """
    m = re.match(r"\s*([A-Za-z0-9_-]+)@([0-9.]+)(?:#(.*))?\s*$", ref or "")
    if not m:
        return None, None, None
    return m.group(1), m.group(2), (m.group(3) or "").strip() or None


def original_line(video_id, timestamp):
    """(speaker, text) currently in the transcript at this timestamp.

    The form sends only a reference, never the originals, so this is where
    they come from. Reading them from the transcript is strictly better than
    round-tripping them through a text box the submitter can edit by accident.
    """
    try:
        t = float(timestamp)
    except (TypeError, ValueError):
        return None, None
    hits = glob.glob("20??-??-??_" + video_id + "/*_" + video_id + ".srt")
    if not hits:
        return None, None

    best = (None, None)
    best_start = None
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
                    body = line.strip()
                    spk, _, txt = body.partition("]:")
                    best = (spk.lstrip("[").strip(), txt.strip())
    return best


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


# optional leading [seconds], then [Name]: text
TURN_RE = re.compile(
    r"^\s*(?:\[\s*([0-9]+(?:\.[0-9]+)?)\s*\]\s*)?\[([^\]]{1,60})\]\s*:\s*(.*)$")


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
        turn = {"speaker": m.group(2).strip(), "text": m.group(3).strip()}
        if m.group(1):
            turn["time"] = m.group(1)
        turns.append(turn)
    return turns or None


def classify(rec):
    """Infer WHAT was corrected by diffing the submission against the original.

    The form asks nothing beyond the corrected text: every correctable thing
    lives in that one box, so what the contributor CHANGED is the answer. A
    single submission can legitimately correct several things at once, so this
    returns a list.
    """
    changed = []
    turns = rec.get("turns") or []
    was_s = (rec.get("original_speaker") or "").strip()
    was_x = (rec.get("original_text") or "").strip()

    if not turns:
        return ["unparsed"]

    if len(turns) > 1:
        changed.append("split")
    else:
        if was_s and turns[0]["speaker"].strip() != was_s:
            changed.append("speaker")
        if was_x and turns[0]["text"].strip() != was_x:
            changed.append("text")

    if any("time" in t for t in turns):
        changed.append("timestamp")

    return changed or ["none"]


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="published-to-web CSV url")
    src.add_argument("--csv", help="a downloaded CSV file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--trusted", default=TRUSTED,
                    help="whitelist file (default: %s)" % TRUSTED)
    ap.add_argument("--no-trust", action="store_true",
                    help="ignore the whitelist; queue everything for review")
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

    queue = {"_comment": ("Correction submissions. status=pending needs review; "
                          "status=accepted was auto-accepted from the trusted "
                          "whitelist and records accepted_by. Applying is a "
                          "separate step and every applied edit must land in "
                          "its own revertible, attributed commit."),
             "items": {}}
    if os.path.exists(QUEUE):
        with open(QUEUE, encoding="utf-8") as fp:
            queue = json.load(fp)
    items = queue.setdefault("items", {})

    trusted = load_trusted(args.trusted)
    if trusted:
        print("\ntrusted contributors: %d (%s)"
              % (len(trusted), ", ".join(sorted(trusted.values()))))
        if args.no_trust:
            print("--no-trust given: whitelist IGNORED, everything queues for review")
            trusted = {}
    else:
        print("\ntrusted contributors: none (%s absent or empty)" % args.trusted)

    added = dupes = auto = 0
    for raw in rows:
        rec = {field: (raw.get(col) or "").strip()
               for field, col in mapping.items()}
        if not any(rec.values()):
            continue
        rid = row_id(rec)
        if rid in items:
            dupes += 1
            continue
        # everything is derived from the reference -- the form sends no
        # originals, so they come from the transcript
        vid, t0, who = parse_reference(rec.get("reference"))
        # a dedicated form column beats the tag appended to the reference
        if not rec.get("contributor"):
            rec["contributor"] = who or ""
        rec["video_id"] = vid
        rec["original_timestamp"] = t0
        spk, txt = original_line(vid, t0) if vid else (None, None)
        if spk:
            rec["original_speaker"] = spk
        if txt:
            rec["original_text"] = txt
        rec["turns"] = parse_turns(rec.get("suggestion")) or []
        rec["target"] = classify(rec)

        # Trusted contributors skip review -- but only when the submission
        # actually parsed. An unparsed or empty edit from a trusted account is
        # still a broken edit, and auto-applying it would write nonsense into a
        # transcript with nobody looking. Trust is about WHO, never about
        # whether the content is well formed.
        tok = token_of(rec.get("contributor"))
        tg = rec.get("target") or []
        if tok and tok in trusted and "unparsed" not in tg and tg != ["none"]:
            rec["status"] = "accepted"
            rec["accepted_by"] = "whitelist:" + trusted[tok]
            auto += 1
        else:
            rec["status"] = "pending"
        items[rid] = rec
        added += 1

    print("\nnew submissions : %d" % added)
    print("already queued  : %d" % dupes)
    if auto:
        print("AUTO-ACCEPTED   : %d (trusted contributor, skipped review)" % auto)
    pend = sum(1 for v in items.values() if v.get("status") == "pending")
    print("pending review  : %d of %d total" % (pend, len(items)))

    by_contrib = {}
    for v in items.values():
        who = (v.get("contributor") or "").strip() or "(none)"
        by_contrib[who] = by_contrib.get(who, 0) + 1
    if len(by_contrib) > 1 or "(none)" not in by_contrib:
        print("\nsubmissions by contributor:")
        for who, n in sorted(by_contrib.items(), key=lambda kv: -kv[1])[:10]:
            print("   %-28s %d" % (who, n))

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
                                        v.get("original_timestamp")))
        if "unparsed" in tg:
            print("     COULD NOT PARSE -- expected '[Name]: text' lines")
            print("     got: %s" % (v.get("suggestion") or "")[:80])
            continue
        if "split" in tg:
            print("     SPLIT into %d turns:" % len(v.get("turns") or []))
            for t in (v.get("turns") or [])[:6]:
                print("        %s[%s] %s"
                      % (("@" + t["time"] + " ") if "time" in t else "",
                         t["speaker"], t["text"][:52]))
        else:
            turn = (v.get("turns") or [{}])[0]
            if "speaker" in tg:
                print("     speaker: %s -> %s"
                      % (v.get("original_speaker") or "?", turn.get("speaker")))
            if "text" in tg:
                print("     was: %s" % (v.get("original_text") or "")[:80])
                print("     fix: %s" % (turn.get("text") or "")[:80])
            if "timestamp" in tg:
                print("     time: %s -> %s"
                      % (v.get("original_timestamp"), turn.get("time")))
        if tg == ["none"]:
            print("     (nothing changed -- test or accidental submit)")

    if args.dry_run:
        print("\nDry run; %s not written." % QUEUE)
    else:
        with open(QUEUE, "w", encoding="utf-8") as fp:
            json.dump(queue, fp, indent=2)
        print("\nwrote", QUEUE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
