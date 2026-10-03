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

from bs4 import BeautifulSoup

BASE = "https://www.medfordma.org"
INDEX = BASE + "/boards-commissions/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; medford-transcripts/1.0)"}
OUT = "rosters.json"

# "Doug Carr, Chair, Full Member, term expires 6/30/28 - $1,100 stipend"
# The name is the leading run; everything after the first comma is role text.
MEMBER = re.compile(
    r"^\s*([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]*){1,3})\s*,\s*(.+?)\s*$")
TERM = re.compile(r"term\s+expires?\s*:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", re.I)
# "X Appointee" names WHO APPOINTED the person, not the post they hold. Without
# the trailing guard, "Mayor Appointee" read as the role "Mayor" and put 17
# people in the mayor's chair -- six of them on the Community Fund Committee at
# once, where the page says "Mayor Appointee Term expires 12/31/26" beside each
# name. Only Breanna Lungo-Koehn, an ex-officio member, actually holds it.
TITLE = re.compile(r"\b(chair(?:person|man|woman)?|vice[\s\-]?chair|clerk|secretary|"
                   r"city councilor|councillor|councilor|alderman|mayor|chief|"
                   r"treasurer|president|director|staff liaison|associate member|"
                   r"alternate|full member|member)\b"
                   r"(?!\s*(?:appointee|appointment|designee|nominee|"
                   r"representative|rep\b))", re.I)
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


# LOWERCASE PARTICLES ARE PART OF THE NAME. Requiring every word after the first
# to be capitalised dropped "Paulette Van der Kloot" -- the lowercase "der" fails
# [A-Z], and because the pattern is anchored the whole name fails rather than
# truncating. Found by testing against a real roster, and it is the same family as
# the hyphen bug in identify_from_text (where [a-z'-] could not match the capital
# after the hyphen in "Edouard-Vincent"). Surnames are not TitleCase-per-word.
_NAME_WORD = (r"(?:[A-Z][A-Za-z.'\-]*|van|von|der|den|de|del|della|di|da|dos|du|"
              r"la|le|ter|bin|ibn)")
BARE_NAME = re.compile(r"^([A-Z][A-Za-z.'\-]+(?:\s+" + _NAME_WORD + r"){1,4})"
                       r"(?:\s*,\s*(.*))?$")


def in_name_run(lines, i, need=3):
    """True when lines[i] sits in a run of >=need consecutive name-shaped lines.

    Counts outward from i in both directions, so the run is recognised from any
    position in it rather than only from its start.
    """
    def name_like(s):
        if not s or len(s) > 60 or VACANT.search(s) or NOT_A_PERSON.search(s):
            return False
        m = BARE_NAME.match(s)
        if not m:
            return False
        # a trailing role is fine ("Milva McDonald, Committee Chair"); a trailing
        # sentence is not
        rest = m.group(2) or ""
        return len(rest.split()) <= 4

    if not name_like(lines[i]):
        return False
    run = 1
    j = i - 1
    while j >= 0 and name_like(lines[j]):
        run += 1
        j -= 1
    j = i + 1
    while j < len(lines) and name_like(lines[j]):
        run += 1
        j += 1
    return run >= need


# Bold text is the strongest roster signal the city's CMS gives us, but it is
# not universal, so it is a first pass and not a replacement -- see parse_roster.
LABEL = re.compile(r"^(members?|summary|questions?|email|phone|address|staff|"
                   r"note|notes|contact|hours|location|website|fax|"
                   r"meetings?|agendas?|minutes?|terms?|appointed by|"
                   r"additional links?|final report|more information|resources?|"
                   r"mission|purpose|history|background|overview|documents?)\b[:\s]*$",
                   re.I)

# Words that never appear in a person's name but do appear in the venues,
# services and partner organisations these pages also put in bold. Every entry
# here was found in output, not guessed: Chevalier Theatre, Tufts Pool,
# Wright's Pond, Medford Family Network, Alternate Phone, Important Numbers.
INSTITUTION = re.compile(
    r"\b(theatre|theater|stadium|university|college|school|library|hospital|"
    r"police|fire|department|line|hotline|center|centre|association|society|"
    r"church|clinic|institute|foundation|partners|services|program|project|"
    r"creole|spanish|portuguese|haitian|english|arabic|chinese|"
    r"links?|report|form|survey|map|calendar|newsletter|"
    r"phone|fax|email|mobile|voicemail|emergency|alternate|"
    r"pool|pond|parks?|paths?|network|recreation|hours|numbers|square|"
    r"field|playground|beach|trail|pop-?up|directory|debt|collection|rights|credit|issues|theft|mortgage|retail|identity|charters?|statutes?|ordinances?|bylaws?|regulations?|massachusetts|commonwealth)\b", re.I)


def content_blocks(page):
    """The page's editorial content, with the site chrome removed.

    THIS IS THE FIX FOR THE CONTAMINATION. The previous version flattened the
    WHOLE page to text, so the left-hand navigation -- Snow Policies, Street
    Sweeping, Legal Holidays, Collective Bargaining Agreements -- came through
    as a run of capitalised lines, which is exactly what in_name_run() was built
    to accept. 970 of 1,275 member rows were site navigation, repeated
    identically in all 40 bodies, and not one body was clean.

    No heuristic on the text could have separated those: "Legal Holidays" is
    name-shaped. The signal is structural, and only in the markup.
    """
    soup = BeautifulSoup(page, "lxml")
    for bad in soup.select("script, style, nav, header, footer, div.fsNavigation"):
        bad.decompose()
    return soup.select("div.fsContent div.fsElementContent") or soup.select("body")


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().strip(" ,;:-–")


LEADING_TITLE = re.compile(
    r"^(?:city\s+councilor|councillor|councilor|alderman|mayor|chief|dr|doctor|"
    r"hon|honorable|rev|reverend|prof|professor|police\s+chief|fire\s+chief)"
    r"\.?\s+", re.I)


def _split_name(raw):
    """('MaryAnn O'Connor', 'Chair') from 'MaryAnn O'Connor, Chair'."""
    parts = [p.strip() for p in raw.split(",")]
    name, rest = parts[0], ", ".join(parts[1:])
    lead = LEADING_TITLE.match(name)
    if lead:
        # keep the title as role text, not as part of the person's name
        name, rest = name[lead.end():].strip(), (lead.group(0).strip() + " " + rest).strip()
    return name, rest


def is_person(n, body_name=""):
    """Whether a candidate string can be a member's name."""
    if not n or len(n) > 48:
        return False
    if LABEL.match(n) or n.isupper():
        return False
    if INSTITUTION.search(n) or NOT_A_PERSON.search(n) or VACANT.search(n):
        return False
    # A bolded phrase starting with the city's own name is a place or a
    # service, never a resident: "Medford Family Network", "Medford City Hall".
    # The city's own name anywhere in a bolded phrase marks a place, a
    # document or a service, never a resident: "Medford Family Network",
    # "Revised Medford City Charter".
    if "medford" in n.lower():
        return False
    if body_name and n.lower() in body_name.lower():
        return False
    if not BARE_NAME.match(n):
        return False
    if not 2 <= len(n.split()) <= 5:
        return False
    if not TITLE.sub("", n).strip(" ,-"):
        return False          # the "name" was only a role word
    return True


def parse_bold(page, body_name=""):
    """[(name, roles, term)] anchored on bold text inside the content blocks.

    THE GATE IS PAGE-LEVEL, NOT BLOCK-LEVEL. Neighborhood Ambassadors gives
    each ambassador their own content block holding a name and an email and
    nothing else, so a "this block holds >= 2 names" test rejected all ten of
    them. What separates a roster from a bolded resource list is a property of
    the page: it names several people, and usually carries a title or a term
    date somewhere in it.
    """
    cands, anchored = [], False
    for blk in content_blocks(page):
        text = _norm(blk.get_text(" "))
        if TITLE.search(text) or TERM.search(text):
            anchored = True
        # EMPTY BOLDS ARE NOT BOUNDARIES. The context walk below stops at the
        # next bold tag, and the CMS wedges whitespace-only <b> between a name
        # and its role -- "<em>Interim</em><b> </b><em>Chair</em>" on the
        # building page. Treating that spacer as the next person's name cut the
        # walk short and lost both the role and the term date, silently: the
        # person still parsed, just stripped of everything after their name.
        tags = [t for t in blk.select("strong, b") if _norm(t.get_text(" "))]
        for idx, t in enumerate(tags):
            name, trailing = _split_name(_norm(t.get_text(" ")))
            name = SOURCE_TYPOS.get(name, name)
            if not is_person(name, body_name):
                continue
            ctx = [trailing]
            for sib in t.next_elements:
                if idx + 1 < len(tags) and sib is tags[idx + 1]:
                    break
                if isinstance(sib, str):
                    ctx.append(sib)
            cands.append((name, _norm(" ".join(ctx))[:200]))

    # Three is the floor, the same reasoning as in_name_run: two capitalised
    # phrases happen in prose, three rarely. A page that also carries a title or
    # a term date is a roster at two.
    if len(cands) < (2 if anchored else 3):
        return []

    out, seen = [], set()
    for name, ctx in cands:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        term = TERM.search(ctx)
        out.append((name, sorted({m.group(1).title() for m in TITLE.finditer(ctx)}),
                    term.group(1) if term else None))
    return out


def parse_roster(page, body_name=""):
    """[(name, roles, term)] from a body page. Handles ALL THREE published layouts.

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
    # The bold-anchored pass handles the layouts the CMS marks up. It
    # returns [] when a page does not use bold for names, and the
    # line-based parse below still covers those.
    bold = parse_bold(page, body_name)
    if bold:
        return bold

    # SCOPED TO THE CONTENT, not the whole page -- see content_blocks.
    lines = [re.sub(r"\s+", " ", l).strip(" –-\t*_")
             for blk in content_blocks(page)
             for l in blk.get_text(chr(10)).split(chr(10))]
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
        if not is_person(name, body_name):
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
        # A name qualifies if it carries a role, is anchored by a term date, or
        # sits in a RUN of consecutive bare names.
        #
        # THE THIRD LAYOUT is a plain list with no term dates and a title only on
        # the chair (Charter Study Committee: "Milva McDonald, Committee Chair"
        # then ten bare names). Requiring a title or a term accepted the chair and
        # discarded the other ten. A run is the anchor here for the same reason it
        # is in the roll-call detector: eleven capitalised lines in a row are a
        # roster, one is prose. Three is the floor -- two adjacent capitalised
        # phrases happen in ordinary text, three rarely.
        if not (titled or has_term) and not in_name_run(lines, i):
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
    # THE THIRD LAYOUT, copied from the Charter Study Committee page: a plain list,
    # no term dates, a title only on the chair. The previous version found 1 of 11.
    three = parse_roster(
        "<p>Milva McDonald, Committee Chair</p><p>Anthony Andreottola</p>"
        "<p>Danielle Balocca</p><p>Eunice Browne</p><p>Maury Carroll</p>"
        "<p>Ron Giovino</p><p>Phyllis Morrison</p><p>Paulette Van der Kloot</p>"
        "<p>Aubree Webb</p><p>David Zabner</p><p>Jean Zotter</p>")
    n3 = [r[0] for r in three]
    check("bare list: chair found", "Milva McDonald" in n3, True)
    check("bare list: titleless found", "Anthony Andreottola" in n3, True)
    check("bare list: all eleven", len(three), 11)
    check("bare list: chair role read",
          "Chair" in dict((r[0], r[1]) for r in three)["Milva McDonald"], True)
    # a lone capitalised phrase in prose must NOT become a member
    lone = parse_roster("<p>The board met in January.</p><p>Medford Square Study</p>"
                        "<p>Applications are reviewed quarterly.</p>")
    check("lone phrase rejected", len(lone), 0)

    typo = parse_roster("<p><strong>Eneni Glekas</strong><br>Term expires 12/1/2026</p>")
    check("source typo corrected", [r[0] for r in typo], ["Eleni Glekas"])

    tby = {r[0]: r for r in two}
    check("two-line: term from next line", tby["Peter Miller"][2], "12/1/27")
    check("two-line: role still read", "Vice Chair" in tby["Ryan Hayward"][1], True)
    # THE CONTAMINATION THIS PARSER EXISTS TO PREVENT. The previous version
    # flattened the whole page, so the site's left-hand navigation arrived as a
    # run of capitalised lines and in_name_run() accepted it: 970 of 1,275
    # member rows were nav, identical in all 40 bodies. The fix is structural --
    # content_blocks drops fsNavigation -- so the test must be structural too.
    nav = parse_roster(
        '<div class="fsElement fsNavigation fsList nav-main">'
        "<p>Human Resources Employee Benefits</p><p>Legal Holidays</p>"
        "<p>Collective Bargaining Agreements</p><p>Snow Policies</p>"
        "<p>Street Sweeping</p><p>Employment Opportunities</p></div>"
        '<div class="fsElement fsContent"><div class="fsElementContent">'
        "<p><strong>Doug Carr</strong><br>Term expires 6/30/28</p>"
        "<p><strong>Peter Miller</strong><br>Term expires 12/1/27</p>"
        "</div></div>")
    nav_names = [r[0] for r in nav]
    check("navigation excluded", any("Snow" in n or "Holidays" in n
                                     for n in nav_names), False)
    check("roster still found beside nav", sorted(nav_names),
          ["Doug Carr", "Peter Miller"])

    # A bolded RESOURCE list is not a roster. Welcoming Committee bolds phone
    # lines, languages and partner organisations the same way other pages bold
    # member names.
    res = parse_roster(
        '<div class="fsElement fsContent"><div class="fsElementContent">'
        "<p><strong>Important Numbers</strong></p><p><strong>Tufts Pool</strong></p>"
        "<p><strong>Medford Family Network</strong></p>"
        "<p><strong>Alternate Phone</strong></p>"
        "<p><strong>Wright's Pond</strong></p></div></div>")
    check("resource list rejected", len(res), 0)

    # A leading title belongs in the roles, not in the person's name.
    lead = parse_roster(
        '<div class="fsElement fsContent"><div class="fsElementContent">'
        "<p><strong>City Councilor Kit Collins</strong>, Chair</p>"
        "<p><strong>Dr. David S. Pladziewicz</strong></p>"
        "<p><strong>Mayor Breanna Lungo-Koehn</strong></p></div></div>")
    lnames = [r[0] for r in lead]
    check("leading title lifted off name", "Kit Collins" in lnames, True)
    check("honorific lifted off name", "David S. Pladziewicz" in lnames, True)
    check("bare title is not a member", "City Councilor" in lnames, False)

    for nm, pat in (("MEMBER", MEMBER), ("TERM", TERM), ("TITLE", TITLE)):
        if [c for c in pat.pattern if ord(c) < 32]:
            fails.append("%s contains a control character" % nm)
    # A whitespace-only <b> between a name and its role must not end the walk.
    # Verbatim shape from /departments/building-department. This failed quietly
    # in the worst way: the person still parsed, just with no role and no term.
    spacer = ('<div class="fsContent"><div class="fsElementContent">'
              "<p><b>Bill Forte</b><br><em>Interim</em><b> </b><em>Chair</em>"
              "<br>term expires 6/30/28</p>"
              "<p><b>Deb Nee</b><br><em>Member</em></p>"
              "<p><b>Amy Tenaglia</b><br><em>Member</em></p>"
              "</div></div>")
    check("empty <b> does not truncate the role",
          parse_roster(spacer, "Test Commission")[0], ("Bill Forte", ["Chair"], "6/30/28"))
    # verbatim from the Community Fund Committee page
    check("'Mayor Appointee' is not the role Mayor",
          sorted({m.group(1).title()
                  for m in TITLE.finditer("Mayor Appointee Term expires 12/31/26")}),
          [])
    check("the actual mayor still reads as Mayor",
          sorted({m.group(1).title()
                  for m in TITLE.finditer("Mayor Breanna Lungo-Koehn")}),
          ["Mayor"])

    for f in fails:
        print("  FAIL %s" % f)
    print("self-test: 31 checks, %d failed" % len(fails))
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
        members = parse_roster(page, name)
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
