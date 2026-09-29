"""Scrape School Committee agendas and minutes from the MPS site.

WHY A SECOND SCRAPER. scrape.py talks to medfordma.api.civicclerk.com, which is
the CITY clerk's system. The school department publishes separately, so the
corpus holds 576 non-skipped MPS meetings and almost no MPS documents. See
plan.txt 12.5.

DRY RUN BY DEFAULT, AND THE REPORT IS THE POINT. The filename IS the
integration: utils._document_index() derives the date with title_date() and the
meeting type with get_meeting_type_by_title(), both from the basename alone,
and meeting_documents() then requires the derived type to EQUAL the video's
meeting_type. A file whose name derives the wrong type is invisible forever,
with no error anywhere -- so the constructed names get reviewed before anything
is downloaded.

THE ONE TRAP THAT IS ALREADY PROVEN. The site writes "Committee of the Whole".
That phrase is a keyword for BOTH "CC City Council Meeting of the Whole"
(position 4) and "MPS Meeting of the Whole" (position 5), and
get_meeting_type_by_title returns the FIRST match, so the site's own wording
files a school meeting under the city council. Reordering meeting_types.json is
forbidden -- it would silently re-type existing meetings -- so an additive
keyword "msc meeting of the whole" exists for exactly this. PURPOSE_FIXUPS is
the translation and check_naming() refuses to run if it ever stops working.
"""

import argparse
import html as _html
import os
import re
import sys
import urllib.parse
import urllib.request

import requests

import utils

# Agendas and minutes live in SEPARATE directories, each globbed independently
# by utils._document_index(kind). A minutes file written into agendas/ would be
# offered to readers as the agenda.
DEST = {"Agenda": "agendas", "Minutes": "minutes"}

BASE = "https://www.mps02155.org"
INDEX = BASE + "/about/school-committee/meetings"
UA = {"User-Agent": "Mozilla/5.0 (compatible; medford-transcripts/1.0)"}

# Applied to the purpose cell before the filename is built, case-insensitively,
# IN ORDER -- the phrase is rewritten first, then the abbreviation is deleted.
#
# "COW" HAS TO GO, not be rewritten. It is a keyword for BOTH
# "CC City Council Meeting of the Whole" (position 5) and "MPS Meeting of the
# Whole" (position 6), exactly like the long phrase, so leaving a "(COW)" in the
# name re-creates the collision the rewrite just fixed -- the site's real
# wording is "Committee of the Whole (COW)", which rewrites to
# "MSC Meeting of the Whole (COW)" and still derives the CITY COUNCIL. It is a
# redundant abbreviation of the phrase already spelled out, so dropping it
# loses nothing.
PURPOSE_FIXUPS = (
    (r"committee\s+of\s+the\s+whole", "MSC Meeting of the Whole"),
    (r"\bcotw\b", "MSC Meeting of the Whole"),
    (r"\(\s*cow\s*\)", " "),
    (r"\bcow\b", " "),
)

# Stripped from the purpose. Scheduling notes would pollute the filename and,
# worse, "(Begins at 5 p.m.)" gives title_date() something to chew on.
PURPOSE_NOISE = (
    r"\([^()]*\b(?:begins?|starts?|p\.?m\.?|a\.?m\.?|rescheduled|cancell?ed|note)\b[^()]*\)",
    r"\*+",
)


def fetch(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60
    ).read().decode("utf-8", "replace")


def _text(fragment):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _links(fragment):
    """[(label, absolute url)] in document order.

    ABSOLUTE MATTERS. The document links are site-relative
    ("/fs/resource-manager/view/<uuid>"); handing one to requests raises
    "Invalid URL ... No scheme supplied", which is at least loud. Resolving
    here keeps every consumer -- link_kind(), save_pdf() -- working on one
    shape.
    """
    return [(_text(m.group(2)), urllib.parse.urljoin(BASE, _html.unescape(m.group(1))))
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', fragment, re.S)]


def parse_rows(page):
    """Yield one dict per data row of every table on the page."""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        if len(cells) < 3:
            continue
        date_text = _text(cells[0])
        if not date_text or date_text.lower().startswith("date"):
            continue                      # header row
        yield {
            "date_text": date_text,
            "purpose": _text(cells[1]),
            "doc_links": _links(cells[2]),
            "material_links": _links(cells[3]) if len(cells) > 3 else [],
        }


def normalize_purpose(purpose):
    p = purpose
    for pat in PURPOSE_NOISE:
        p = re.sub(pat, " ", p, flags=re.I)
    for pat, repl in PURPOSE_FIXUPS:
        p = re.sub(pat, repl, p, flags=re.I)
    return re.sub(r"\s+", " ", p).strip(" -–")


POSTPONED = re.compile(
    r"\b(?:postponed|rescheduled|moved|changed)\b\W*(?:until|to|for)?\s*(.+)$", re.I)


def _loosen(s):
    """Repair the two shapes this site actually publishes.

    'November9' -- a missing space, seen once -- and ordinal suffixes like
    '16th', which dateutil will not take.
    """
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)
    s = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def iso_date(date_text):
    """'July 20, 2026*' -> '2026-07-20'; None when unparseable.

    A POSTPONED ROW MUST RESOLVE TO THE DATE IT MOVED TO, not the one it was
    announced for. "November9, 2022 Postponed until November 16th" is a single
    row carrying BOTH its agenda and its minutes, and there is no separate row
    for the 16th -- so taking the first date would file two real documents
    against a meeting that never happened, and skipping the row would lose
    them. The replacement half often omits the year; it inherits it.
    """
    cleaned = _loosen(re.sub(r"[*†‡]", " ", date_text))
    m = POSTPONED.search(cleaned)
    if m:
        tail = m.group(1)
        if not re.search(r"\b(?:19|20)\d\d\b", tail):
            year = re.search(r"\b((?:19|20)\d\d)\b", cleaned[:m.start()])
            if year:
                tail = "%s %s" % (tail, year.group(1))
        moved = utils.title_date(_loosen(tail))
        if moved:
            return moved
    return utils.title_date(cleaned)


def build_filename(iso, purpose, kind):
    """'YYYY.MM.DD - School Committee <purpose> <kind>.pdf'.

    "School Committee" is always present so get_meeting_type_by_title() has
    something to match when the purpose is bare ("Regular Meeting").
    """
    dotted = iso.replace("-", ".")
    purpose = purpose or "Regular Meeting"
    if "school committee" in purpose.lower():
        stem = "%s - %s %s" % (dotted, purpose, kind)
    else:
        stem = "%s - School Committee %s %s" % (dotted, purpose, kind)
    # PATH SEPARATORS AND THE REST OF THE ILLEGAL SET. One purpose cell reads
    # "Joint Session w/ City Council", and the slash in it made open() treat the
    # name as a subdirectory that does not exist. Verified that replacing it
    # changes no derived type -- "school committee" is what get_meeting_type_by
    # _title matches here, and it survives any of the candidate substitutions.
    stem = re.sub(r'[\\/:*?"<>|]+', "-", stem)
    return re.sub(r"\s+", " ", stem).strip(" -") + ".pdf"


def classify_link(label, url):
    """('Agenda'|'Minutes', url), or None when the link is not a document.

    The agenda sits beside a "News Post" link to an HTML announcement. That is
    not a document and must not be collected.
    """
    l = label.lower()
    if "news post" in l:
        return None
    if "minute" in l:
        return "Minutes", url
    if l in ("pdf", "agenda") or "agenda" in l:
        return "Agenda", url
    return None


def link_kind(url):
    """How hard this URL is to fetch. See plan.txt 12.5."""
    if "/fs/resource-manager/view/" in url:
        return "finalsite"            # 302s to a real PDF; easy
    if re.search(r"drive\.google\.com/file/d/", url):
        return "drive-file"           # rewritable; interstitial when large
    if re.search(r"drive\.google\.com/drive/folders/", url):
        return "drive-folder"         # needs Drive API + drive.readonly
    if url.lower().split("?")[0].endswith(".pdf"):
        return "direct"
    return "other"


def save_pdf(url, path):
    """Download to `path` unless it exists. Returns 'saved'|'skip'|reason.

    VERIFIES IT IS ACTUALLY A PDF before writing. scrape.save_file() writes
    whatever came back, which is fine against the civicclerk API and wrong
    here: a finalsite resource id that has been retired answers 200 with an
    HTML error page, and an unauthenticated Drive link answers 200 with a
    sign-in page. Either one saved under a .pdf name is a silent corruption --
    it would sit in agendas/, be indexed by name, and link from a committee
    page to a file no reader can open.
    """
    if os.path.exists(path):
        return "skip"
    try:
        r = requests.get(url, headers=UA, timeout=90, allow_redirects=True)
    except Exception as e:
        return "error %s" % str(e)[:60]
    if r.status_code != 200:
        return "http %d" % r.status_code
    body = r.content
    if not body[:5].startswith(b"%PDF"):
        ctype = (r.headers.get("content-type") or "?").split(";")[0]
        return "not a pdf (%s, %d bytes)" % (ctype, len(body))
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)
    return "saved"


def check_naming():
    """Refuse to run if the filename no longer derives the intended type.

    Cheap, and the failure it guards is completely silent: a misnamed document
    is simply never shown on any page.

    THE CASES ARE WORDINGS THE SITE ACTUALLY PUBLISHES, not tidy inventions.
    An earlier version of this check tested "MSC Meeting of the Whole" -- which
    the scraper never produces on its own -- passed, and 17 documents still
    derived the city council, because the real cell reads "Committee of the
    Whole (COW)" and the surviving abbreviation re-created the collision.
    """
    bad = []
    cases = (
        ("Regular Meeting", "MPS School Committee"),
        ("Special Meeting", "MPS School Committee"),
        # the real wordings, straight off the page
        ("Committee of the Whole (COW)", "MPS Meeting of the Whole"),
        ("Committee of the Whole (COW) FY 25 Budget Meeting #2",
         "MPS Meeting of the Whole"),
        ("Committee of the Whole", "MPS Meeting of the Whole"),
    )
    for raw, expected in cases:
        stem = os.path.splitext(
            build_filename("2026-09-08", normalize_purpose(raw), "Agenda"))[0]
        got = utils.get_meeting_type_by_title(stem)
        if got != expected:
            bad.append((stem, expected, got))
    return bad


def discover_pages(index_page):
    """The index, plus the per-year subpages it links to."""
    pages = [INDEX]
    for m in re.finditer(
            r'href="(/fs/pages/\d+|/about/school-committee/meetings/[^"#?]+)"', index_page):
        u = BASE + m.group(1)
        if u not in pages:
            pages.append(u)
    return pages


def collect(urls):
    rows = []
    for u in urls:
        try:
            page = fetch(u)
        except Exception as e:
            print("  FETCH FAILED %-46s %s" % (u.replace(BASE, ""), str(e)[:70]))
            continue
        n = 0
        for r in parse_rows(page):
            r["source_page"] = u
            rows.append(r)
            n += 1
        print("  %-60s %3d rows" % (u.replace(BASE, ""), n))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="download the documents (default: report only)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    bad = check_naming()
    if bad:
        print("NAMING CHECK FAILED -- refusing to run:")
        for stem, want, got in bad:
            print("   %-54s want %-30s got %s" % (stem[:54], want, got))
        return 1
    print("naming check ok\n\npages:")

    rows = collect(discover_pages(fetch(INDEX)))
    print("\n%d rows total\n" % len(rows))

    vd = utils.get_video_data()
    meetings = {}
    for yt, e in vd.items():
        if e.get("skip"):
            continue
        meetings.setdefault(
            (str(utils.meeting_date(e)), str(e.get("meeting_type"))), []).append(yt)

    print("%-54s %-26s %-12s %s" % ("constructed filename", "derived type", "fetchable", "meeting?"))
    print("-" * 112)
    stats = dict(rows=0, docs=0, nodate=0, matched=0, unmatched=0)
    by_kind, by_type, seen, results = {}, {}, set(), {}
    if args.apply:
        for d in set(DEST.values()):
            if not os.path.isdir(d):
                os.makedirs(d)
    for r in rows:
        stats["rows"] += 1
        iso = iso_date(r["date_text"])
        if not iso:
            stats["nodate"] += 1
            print("%-54s %-26s %-12s %s" % ("(UNPARSED DATE) " + r["date_text"][:36], "-", "-", "-"))
            continue
        purpose = normalize_purpose(r["purpose"])
        for label, url in r["doc_links"]:
            c = classify_link(label, url)
            if not c:
                continue
            kind, href = c
            name = build_filename(iso, purpose, kind)
            if name in seen:
                continue
            seen.add(name)
            stats["docs"] += 1
            mtype = str(utils.get_meeting_type_by_title(os.path.splitext(name)[0]))
            fetchable = link_kind(href)
            by_kind[fetchable] = by_kind.get(fetchable, 0) + 1
            by_type[mtype] = by_type.get(mtype, 0) + 1
            hit = meetings.get((iso, mtype))
            stats["matched" if hit else "unmatched"] += 1
            note = hit[0] if hit else "no meeting"
            if args.apply:
                if fetchable in ("finalsite", "direct"):
                    dest = os.path.join(DEST[kind], name)
                    res = save_pdf(href, dest)
                else:
                    # Drive needs the API and drive.readonly on the service
                    # account; reported rather than half-attempted.
                    res = "todo (%s)" % fetchable
                results[res.split(" ")[0]] = results.get(res.split(" ")[0], 0) + 1
                note = "%-34s %s" % (res[:34], note)
            print("%-54s %-26s %-12s %s" % (
                name[:54], mtype[:26], fetchable, note))
            if args.limit and stats["docs"] >= args.limit:
                break
        if args.limit and stats["docs"] >= args.limit:
            break

    print("-" * 112)
    print("rows %(rows)d | documents %(docs)d | unparsed dates %(nodate)d" % stats)
    print("matched to a meeting %(matched)d | no meeting %(unmatched)d" % stats)
    print("by link type: %s" % by_kind)
    print("by derived meeting type:")
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print("    %-42s %d" % (t, n))
    if args.apply:
        print("downloads: %s" % (results or "none attempted"))
        bad = sum(n for k, n in results.items() if k not in ("saved", "skip", "todo"))
        if bad:
            print("  %d failed -- shown inline above; nothing partial was written." % bad)
    else:
        print("\nDRY RUN -- nothing downloaded. The filenames above ARE the")
        print("integration; review them before re-running with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
