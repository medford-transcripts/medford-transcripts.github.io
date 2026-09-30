"""Date the MPS Drive PDFs whose filenames carry no date, behind three gates.

98 Drive PDFs have no date we can read from the name, so the earlier pass skipped
them entirely: undated means unmatchable means never downloaded. The date printed
INSIDE the document can supply one, but it is not ground truth.

MEASURED FIRST, against 131 documents whose filename date we trust: a
context-aware extractor agreed only 67% of the time even at its best confidence,
and a naive "first date on page 1" was worse than the filename because it picks
the POSTING date -- Massachusetts open-meeting law puts that 48 hours before the
meeting, so the disagreement histogram peaked at exactly -2 days. The document
text can also carry the same typos as the titles (owner, 2026-09-30).

SO THE EXTRACTED DATE IS A CLAIM, and passes three independent gates:

  1. confidence 3 only -- the only tier that performed in validation
  2. the date must land on a real MPS meeting date
  3. the date must fall inside the span of the OTHER files in the same Drive
     folder, which are per-academic-year, so the folder bounds its own contents

A wrong date rarely satisfies 2 and 3 together, which is what makes a 67% source
usable. Anything failing a gate is counted and reported, never guessed at.

Every file dated this way is recorded in document_dates.json, so a weaker basis
stays visible and these files remain identifiable if a date proves wrong.

    python scrape_mps_undated.py            # dry run
    python scrape_mps_undated.py --apply    # download, name, and record
"""

import argparse
import collections
import datetime
import io
import json
import os
import re
import sys

import utils
import scrape_mps as M

DOC_DATES = "document_dates.json"

_MONTHS = ("january february march april may june july august september "
           "october november december").split()
_MON = "|".join(m[:3] for m in _MONTHS)
PDF_DATE = re.compile(
    r"(?:(" + _MON + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)"
    r"|(\d{1,2})[/.](\d{1,2})[/.](20\d\d|\d\d))", re.I)
MEETING_CUE = re.compile(r"(meeting\s+date|will\s+be\s+held|is\s+scheduled|"
                         r"regular\s+meeting|special\s+meeting|"
                         r"committee\s+of\s+the\s+whole|subcommittee\s+meeting|"
                         r"meeting\s+of\s+the|agenda\s+for|minutes\s+of|held\s+on|"
                         r"convened)", re.I)
POSTED_CUE = re.compile(r"(posted|notice|filed|received|date\s+posted|city\s+clerk)",
                        re.I)


def _as_date(m):
    if m.group(1):
        mon = [i for i, x in enumerate(_MONTHS, 1) if x.startswith(m.group(1).lower())][0]
        year, day = int(m.group(3)), int(m.group(2))
    else:
        year = int(m.group(6))
        year += 2000 if year < 100 else 0
        mon, day = int(m.group(4)), int(m.group(5))
    try:
        return datetime.date(year, mon, day)
    except ValueError:
        return None


def pdf_meeting_date(body):
    """(iso, confidence, why) for the MEETING date printed in a PDF."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(body))
        text = ""
        for page in reader.pages[:2]:
            text += (page.extract_text() or "") + "\n"
        created = None
        mm = re.search(r"(20\d\d)(\d\d)(\d\d)",
                       str((reader.metadata or {}).get("/CreationDate") or ""))
        if mm:
            try:
                created = datetime.date(int(mm.group(1)), int(mm.group(2)),
                                        int(mm.group(3)))
            except ValueError:
                created = None
    except Exception as exc:
        return None, 0, "unreadable: %s" % str(exc)[:32]
    if not text.strip():
        return None, 0, "no text layer (scan)"

    flat = re.sub(r"\s+", " ", text)
    best = None
    for m in PDF_DATE.finditer(flat):
        d = _as_date(m)
        if not d or not (2005 <= d.year <= 2030):
            continue
        ctx = flat[max(0, m.start() - 120):m.end() + 120]
        # THE POSTING CUE ONLY COUNTS IMMEDIATELY BEFORE THE DATE. "Posted:" and
        # "Notice" govern the date that FOLLOWS them, so a wide window penalised
        # the meeting date for a posting line one line below it -- a correctly
        # formed agenda scored 1 instead of 3. Caught by the self-test before any
        # download: the naive wide window would have rejected exactly the
        # documents this is meant to accept.
        lead = flat[max(0, m.start() - 40):m.start()]
        score, why = 0, []
        if MEETING_CUE.search(ctx):
            score += 2
            why.append("meeting cue")
        if POSTED_CUE.search(lead):
            score -= 2
            why.append("posted cue")
        if created and d == created:
            # for an agenda the file's creation date IS the posting date
            score -= 1
            why.append("== CreationDate")
        if m.start() < 400:
            score += 1
            why.append("near top")
        if best is None or score > best[1]:
            best = (d, score, ", ".join(why) or "no cue")
    if best is None:
        return None, 0, "no date in text"
    return best[0].isoformat(), max(best[1], 0), best[2]


def self_test():
    """Gate logic on literal text, before any download."""
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (label, got, want))

    # a meeting cue near the top should win over a posting date further down
    good = ("MEDFORD SCHOOL COMMITTEE\n"
            "Regular Meeting will be held on September 8, 2026 at 6:00 p.m.\n"
            "Posted: September 4, 2026 by the City Clerk\n")
    iso, conf, _why = pdf_meeting_date(_fake_pdf(good))
    check("meeting cue wins", iso, "2026-09-08")
    check("confidence 3", conf >= 3, True)

    # a posting date alone must not reach confidence 3
    only_posted = "Notice posted September 4, 2026 by the City Clerk\n"
    iso2, conf2, _ = pdf_meeting_date(_fake_pdf(only_posted))
    check("posting-only is low confidence", conf2 < 3, True)

    for nm, pat in (("PDF_DATE", PDF_DATE), ("MEETING_CUE", MEETING_CUE),
                    ("POSTED_CUE", POSTED_CUE)):
        if [c for c in pat.pattern if ord(c) < 32]:
            fails.append("%s has a control character" % nm)
    for f in fails:
        print("  FAIL %s" % f)
    print("self-test: 4 checks, %d failed" % len(fails))
    return 1 if fails else 0


def _fake_pdf(text):
    """A one-page PDF containing `text`, for the self-test only."""
    try:
        from pypdf import PdfWriter
        from reportlab.pdfgen import canvas       # optional
    except Exception:
        pass
    # reportlab is not a dependency here; build the smallest valid PDF by hand.
    esc = text.replace("(", r"\(").replace(")", r"\)")
    lines = esc.split("\n")
    content = "BT /F1 12 Tf 72 720 Td 14 TL\n"
    for ln in lines:
        content += "(%s) Tj T*\n" % ln
    content += "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += "%d 0 obj\n%s\nendobj\n" % (i, o)
    start = len(out)
    out += "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += "%010d 00000 n \n" % off
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, start))
    return out.encode("latin-1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--inert", action="store_true",
                    help="also collect documents whose date matches no meeting we "
                         "hold: measurement says these are mostly real meetings "
                         "never recorded, and they link from nothing until one is")
    args = ap.parse_args()

    if self_test():
        print("REFUSING to run: gate logic failed its own tests.")
        return 1
    print()

    svc = M.drive_service()
    folders = M.drive_folders(M.discover_pages(M.fetch(M.INDEX)))

    vd = utils.get_video_data()
    meetings = {}
    for yt, e in vd.items():
        if e.get("skip"):
            continue
        meetings.setdefault(
            (str(utils.meeting_date(e)), str(e.get("meeting_type"))), []).append(yt)
    mps_dates = {d for (d, t) in meetings if str(t).startswith("MPS")}
    print("MPS meeting dates available for gate 2: %s" % format(len(mps_dates), ","))

    if args.apply:
        for d in set(M.DEST.values()):
            if not os.path.isdir(d):
                os.makedirs(d)
    ledger = {}
    if os.path.exists(DOC_DATES):
        try:
            ledger = json.load(io.open(DOC_DATES, encoding="utf-8")).get("documents", {})
        except Exception:
            ledger = {}

    stats = collections.Counter()
    for fid, label in folders.items():
        low = label.lower()
        kind = "Agenda" if "agenda" in low else ("Minutes" if "minute" in low else None)
        if not kind:
            continue
        files = [f for f in M.drive_list(svc, fid) if "pdf" in f["mimeType"]]
        dated, undated = [], []
        for f in files:
            iso, _rest = M.drive_date(f["name"])
            (dated if iso else undated).append(f)
        if not undated:
            continue
        span = sorted(M.drive_date(f["name"])[0] for f in dated)
        span = [s for s in span if s]
        if not span:
            stats["folder has no dated files to bound it"] += len(undated)
            continue
        lo, hi = span[0], span[-1]

        for f in undated:
            stats["undated files seen"] += 1
            body = _download(svc, f["id"])
            if body is None:
                stats["download failed"] += 1
                continue
            if not body[:5].startswith(b"%PDF"):
                stats["not a pdf"] += 1
                continue
            iso, conf, why = pdf_meeting_date(body)
            if not iso:
                stats["gate1: " + why[:30]] += 1
                continue
            if conf < 3:
                stats["gate1: confidence %d too low" % conf] += 1
                continue
            if iso not in mps_dates:
                # NO MEETING ON THAT DATE -- and measurement says that mostly means
                # a real meeting we never recorded, not a misread. Of the 62 such
                # files: 61 fall Mon-Thu, matching the real MPS weekday
                # distribution (Mon 49%, Wed 25%, Thu 12%); 53 are more than a
                # month from ANY meeting we hold, so they cannot be posting-date
                # errors, which by definition land 1-7 days out; and 52 are
                # 2009-2014, the era with almost no recordings.
                #
                # plan.txt 12.5 argues for collecting these anyway: the meeting may
                # be published later and the document would already be in hand, and
                # for the oldest material the document may be the only surviving
                # record. They are INERT by construction -- _document_index keys on
                # (date, meeting_type), so with no meeting on that date
                # meeting_documents() returns nothing and no page links them. They
                # start appearing the day a matching meeting is added.
                if not args.inert:
                    stats["gate2: no MPS meeting that date"] += 1
                    continue
                if datetime.date.fromisoformat(iso).weekday() >= 4:
                    # Fri/Sat/Sun is 1.7% of real MPS meetings, so a weekend date
                    # here is the one shape that really does look misread.
                    stats["inert: rejected, weekend date"] += 1
                    continue
                if not (lo <= iso <= hi):
                    stats["inert: rejected, outside folder span"] += 1
                    continue
                purpose = M.drive_purpose(re.sub(r"\.pdf$", "", f["name"], flags=re.I))
                name = M.build_filename(iso, purpose, kind)
                stats["INERT: no meeting yet"] += 1
                print("  %-58s %s  INERT (%s)" % (name[:58], iso, why))
                if args.apply:
                    dest = os.path.join(M.DEST[kind], name)
                    if os.path.exists(dest):
                        stats["write: already present"] += 1
                        continue
                    tmp = dest + ".part"
                    with open(tmp, "wb") as fp:
                        fp.write(body)
                    os.replace(tmp, dest)
                    stats["write: saved inert"] += 1
                    ledger[name] = {"date_source": "pdf_text", "confidence": conf,
                                    "why": why, "drive_id": f["id"],
                                    "original_name": f["name"],
                                    "folder_span": [lo, hi],
                                    "no_meeting_yet": True,
                                    "recorded": datetime.date.today().isoformat()}
                continue
            if not (lo <= iso <= hi):
                stats["gate3: outside folder span"] += 1
                continue
            purpose = M.drive_purpose(re.sub(r"\.pdf$", "", f["name"], flags=re.I))
            name = M.build_filename(iso, purpose, kind)
            mtype = str(utils.get_meeting_type_by_title(os.path.splitext(name)[0]))
            if not meetings.get((iso, mtype)):
                stats["gate2: date ok, type has no meeting"] += 1
                continue
            stats["PASSED all three gates"] += 1
            print("  %-58s %s  (%s)" % (name[:58], iso, why))
            if args.apply:
                dest = os.path.join(M.DEST[kind], name)
                if os.path.exists(dest):
                    stats["write: already present"] += 1
                    continue
                tmp = dest + ".part"
                with open(tmp, "wb") as fp:
                    fp.write(body)
                os.replace(tmp, dest)
                stats["write: saved"] += 1
                ledger[name] = {"date_source": "pdf_text", "confidence": conf,
                                "why": why, "drive_id": f["id"],
                                "original_name": f["name"],
                                "folder_span": [lo, hi],
                                "recorded": datetime.date.today().isoformat()}

    print()
    for k in sorted(stats, key=lambda x: -stats[x]):
        print("   %-40s %s" % (k, format(stats[k], ",")))

    if args.apply and ledger:
        payload = {"_comment": [
            "Documents whose date came from the PDF TEXT rather than the filename.",
            "A weaker source: 67% agreement at best confidence in validation, and",
            "the text can carry the same typos as the titles. Recorded so these",
            "files stay identifiable if a date turns out to be wrong."],
            "documents": ledger}
        with io.open(DOC_DATES, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=1, ensure_ascii=False)
        print()
        print("wrote %s (%d documents)" % (DOC_DATES, len(ledger)))
    elif not args.apply:
        print()
        print("DRY RUN -- nothing downloaded or written.")
    return 0


def _download(svc, file_id):
    try:
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _status, done = dl.next_chunk()
        return buf.getvalue()
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
