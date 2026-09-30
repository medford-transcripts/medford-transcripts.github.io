"""Scrape board and commission rosters from medfordma.org.

WHY. plan.txt 12.3 scoped a people registry with roles and DATE RANGES, and 12.12
measured why it is the prerequisite for identifying anyone from transcript text:
matching only works against a CLOSED candidate set, and the error rate is a
function of that set's size -- 0.0% wrong at two candidates against 29.6% at
1,229. A per-body roster IS that closed set, and the city publishes one for each
of ~42 bodies.

The pages carry exactly the schema 12.3 asked for, e.g.

    Doug Carr, Chair, Full Member, term expires 6/30/28 - $1,100 stipend
    Andre Leroux, Chair, Term expires 3/31/2028 - $2,000 stipend

so name, TITLE and a term END DATE come straight off the page. Term dates are
what let a meeting resolve roles by date rather than by "current", which is the
bug 12.3 records: a councillor recorded 2015-2017 counted as sitting in 2026.

NO PRIVACY SURFACE. These are public officials listed on the city's own site in
their official capacity, unlike the resident data in build_parcel_directory.py.
Output is tracked.

TWO USES, both of which need the body link as well as the roster:
  - the closed candidate set per body, for identify_from_text.py
  - a link from each committee page to the official body page, so a reader can
    reach the roster, contact and meeting schedule

    python scrape_rosters.py            # dry run: report what parses
    python scrape_rosters.py --apply    # write rosters.json
"""

import argparse
import collections
import html as _html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://www.medfordma.org"
INDEX = BASE + "/boards-commissions/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; medford-transcripts/1.0)"}
OUT = "rosters.json"

# "Doug Carr, Chair, Full Member, term expires 6/30/28 - $1,100 stipend"
# The name is the leading run; everything after the first comma is role text.
MEMBER = re.compile(
    r"^\s*([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]*){1,3})\s*,\s*(.+?)\s*$")
TERM = re.compile(r"term\s+expires?\s*:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", re.I)
TITLE = re.compile(r"\b(chair(?:person|man|woman)?|vice[\s\-]?chair|clerk|secretary|"
                   r"treasurer|president|director|staff liaison|associate member|"
                   r"alternate|full member|member)\b", re.I)
VACANT = re.compile(r"\bvacan(?:t|cy)\b", re.I)

# TYPOS IN THE SOURCE, corrected on the way in. NOT stored as aliases: an alias
# would make a misspelling look like a legitimate variant of the person's name
# and let it spread into the registry, transcripts and summaries, where the next
# reader has no way to tell which spelling is real. One correct spelling, and the
# wrong one lives only here as an inbound fix.
#
# Each entry needs an authority better than the page being scraped.
#   Eneni -> Eleni Glekas: medfordhistoricalcommission.org, the commission's own
#   roster, spells it Eleni; confirmed by the owner 2026-09-30.
SOURCE_TYPOS = {
    "Eneni Glekas": "Eleni Glekas",
}

# Rows that are plainly not a person.
NOT_A_PERSON = re.compile(r"\b(committee|commission|board|council|department|office|"
                          r"authority|trust|meeting|agenda|minutes|contact|apply|"
                          r"application|stipend only|city of medford)\b", re.I)


def fetch(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60
    ).read().decode("utf-8", "replace")


def text_of(fragment):
    f = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    f = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h[1-6]>", "\n", f)
    return _html.unescape(re.sub(r"<[^>]+>", " ", f))


def bodies(index_html):
    """{name: url} for every board/commission linked from the index."""
    found = collections.OrderedDict()
    # ONLY /boards-commissions/. Including /departments/ pulled in the site-wide
    # navigation -- Animal Control, the Building Department, the Collector/
    # Treasurer -- and turned 42 bodies into 135 mostly-rosterless pages. Staff
    # titles are a separate job with a separate source; conflating them here just
    # buries the rosters that do parse.
    for m in re.finditer(
            r'<a[^>]+href="((?:https?://[^"]+)?/boards-commissions/[^"#?]+)"[^>]*>(.*?)</a>',
            index_html, re.S):
        url = urllib.parse.urljoin(BASE, m.group(1))
        name = re.sub(r"\s+", " ", text_of(m.group(2))).strip()
        if not name or len(name) < 4:
            continue
        if url.rstrip("/") == INDEX.rstrip("/"):
            continue
        found.setdefault(name, url)
    return found


BARE_NAME = re.compile(r"^([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]*){1,3})"
                       r"(?:\s*,\s*(.*))?$")


def parse_roster(page):
    """[(name, roles, term)] from a body page. Handles BOTH published layouts.

    TWO LAYOUTS EXIST and the first version only handled one, because it was
    written against the two pages I happened to sample:

      one line   "Doug Carr, Chair, Full Member, term expires 6/30/28"
      two lines  "Ryan Hayward, Vice Chair"      <- title optional
                 "Term expires 12/1/2026"

    In the two-line form most members have NO title at all ("Doug Carr" then
    "Term expires ..."), so requiring a title keyword on the name line found 1 of
    7 on the Historical Commission and reported the rest as absent. A TERM LINE
    IMMEDIATELY BELOW is what certifies a bare name as a member -- without that
    anchor, accepting titleless names would swallow every capitalised phrase on
    the page.
    """
    lines = [re.sub(r"\s+", " ", l).strip(" –-\t*_")
             for l in text_of(page).split("\n")]
    lines = [l for l in lines if l]
    out, seen = [], set()
    for i, line in enumerate(lines):
        if len(line) > 180 or VACANT.search(line):
            continue
        m = BARE_NAME.match(line)
        if not m:
            continue
        name, rest = m.group(1).strip(), (m.group(2) or "")
        name = SOURCE_TYPOS.get(name, name)
        if NOT_A_PERSON.search(name):
            continue

        term_txt = rest
        titled = bool(TITLE.search(rest))
        has_term = bool(TERM.search(rest))
        if not has_term:
            # look at the next line or two for a bare "Term expires ..."
            for nxt in lines[i + 1:i + 3]:
                if TERM.search(nxt):
                    term_txt = rest + " " + nxt
                    has_term = True
                    break
                if BARE_NAME.match(nxt) and not TITLE.search(nxt):
                    break          # the next member started; no term for this one
        # A name qualifies if it carries a role OR is anchored by a term date.
        if not (titled or has_term):
            continue
        term = TERM.search(term_txt)
        roles = sorted({t.group(1).title() for t in TITLE.finditer(rest)})
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((name, roles, term.group(1) if term else None))
    return out


def self_test():
    """Literal-string assertions, run before any fetch. Same gate as
    identify_from_text.py, for the same reason: a pattern that silently matches
    nothing looks exactly like a page with no roster."""
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (label, got, want))

    rows = parse_roster(
        "<p>Doug Carr, Chair, Full Member, term expires 6/30/28 - $1,100 stipend</p>"
        "<p>Ari Gofman Fishman, Full Member, term expires 6/30/25 - $900 stipend</p>"
        "<p>Andre Leroux, Chair, Term expires 3/31/2028 - $2,000 stipend</p>"
        "<p>Mary K.Y. Lee, Full Member, term expires 3/31/2029</p>"
        "<p>One Governor's appointee, vacant</p>"
        "<p>The Community Development Board, established by ordinance, meets monthly</p>")
    names = [r[0] for r in rows]
    check("chair parsed", "Doug Carr" in names, True)
    check("three-word name", "Ari Gofman Fishman" in names, True)
    check("initials in name", "Mary K.Y. Lee" in names, True)
    check("vacancy skipped", any("Governor" in n for n in names), False)
    check("prose skipped", any("Community Development" in n for n in names), False)
    byname = {r[0]: r for r in rows}
    check("title captured", "Chair" in byname["Doug Carr"][1], True)
    check("term captured", byname["Doug Carr"][2], "6/30/28")
    check("term case-insensitive", byname["Andre Leroux"][2], "3/31/2028")
    check("no term is None", byname["Mary K.Y. Lee"][2], "3/31/2029")

    # THE SECOND LAYOUT, copied from the Historical Commission page. The first
    # version of this parser found 1 of 7 here and called the rest absent.
    two = parse_roster(
        "<p><strong>Ryan Hayward,</strong> Vice Chair<br>Term expires 12/1/2026</p>"
        "<p><strong>Doug Carr</strong><br>Term expires 12/1/2025</p>"
        "<p><strong>Peter Miller</strong><br>Term expires 12/1/27</p>"
        "<p><strong>Sara Berndt</strong><br>Term expires 12/1/2028</p>"
        "<p><em><strong>Vacancy</strong></em></p>")
    tnames = [r[0] for r in two]
    check("two-line: titled member", "Ryan Hayward" in tnames, True)
    check("two-line: titleless member", "Doug Carr" in tnames, True)
    check("two-line: all four found", len(two), 4)
    check("two-line: vacancy skipped", any("Vacan" in n for n in tnames), False)
    typo = parse_roster("<p><strong>Eneni Glekas</strong><br>Term expires 12/1/2026</p>")
    check("source typo corrected", [r[0] for r in typo], ["Eleni Glekas"])

    tby = {r[0]: r for r in two}
    check("two-line: term from next line", tby["Peter Miller"][2], "12/1/27")
    check("two-line: role still read", "Vice Chair" in tby["Ryan Hayward"][1], True)
    for nm, pat in (("MEMBER", MEMBER), ("TERM", TERM), ("TITLE", TITLE)):
        if [c for c in pat.pattern if ord(c) < 32]:
            fails.append("%s contains a control character" % nm)
    for f in fails:
        print("  FAIL %s" % f)
    print("self-test: 16 checks, %d failed" % len(fails))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if self_test():
        print("REFUSING to fetch: patterns failed their own tests.")
        return 1
    print()

    index = fetch(INDEX)
    found = bodies(index)
    print("bodies linked from the index: %d" % len(found))
    print()

    rosters, stats = {}, collections.Counter()
    for i, (name, url) in enumerate(found.items(), 1):
        if args.limit and i > args.limit:
            break
        try:
            page = fetch(url)
        except Exception as e:
            print("  %-46s FETCH FAILED %s" % (name[:46], str(e)[:40]))
            stats["fetch_failed"] += 1
            continue
        members = parse_roster(page)
        stats["bodies"] += 1
        stats["members"] += len(members)
        if members:
            stats["bodies_with_a_roster"] += 1
            with_term = sum(1 for m in members if m[2])
            stats["members_with_a_term"] += with_term
            print("  %-46s %2d members, %2d with term dates"
                  % (name[:46], len(members), with_term))
        else:
            print("  %-46s  no roster found" % name[:46])
        rosters[name] = {"url": url,
                         "members": [{"name": n, "roles": r, "term_expires": t}
                                     for n, r, t in members]}

    print()
    print("  bodies fetched            %d" % stats["bodies"])
    print("  with a parseable roster   %d" % stats["bodies_with_a_roster"])
    print("  members found             %d" % stats["members"])
    print("  members with a term date  %d" % stats["members_with_a_term"])
    print("  fetch failures            %d" % stats["fetch_failed"])

    if not args.apply:
        print()
        print("DRY RUN -- %s not written. Review the names and titles above." % OUT)
        return 0
    payload = {"_comment": ["Board and commission rosters scraped from medfordma.org.",
                            "Public officials in their official capacity; tracked.",
                            "term_expires is what lets a meeting resolve roles BY DATE."],
               "source": INDEX,
               "scraped": __import__("datetime").date.today().isoformat(),
               "bodies": rosters}
    with io.open(OUT, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=1, ensure_ascii=False)
    print()
    print("wrote %s (%s bytes)" % (OUT, format(os.path.getsize(OUT), ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
