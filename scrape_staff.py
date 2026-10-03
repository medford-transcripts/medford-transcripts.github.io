"""Scrape city staff and their titles from medfordma.org/departments.

WHY. A title beside a name is real context in a transcript -- "Mayor's Chief of
Staff" tells a reader something the name alone does not -- and these posts change
often enough that a hand-kept list rots. councilors.json covers ELECTED office
and rosters.json covers boards and commissions; neither knows who the City Clerk
or the Chief Assessor is. This is the third leg.

THE SOURCE LOOKS EMPTY AND IS NOT. The department pages are mostly service
content -- exemption deadlines, dog licences, "before you dig, call Dig Safe" --
and a first look says there is no directory here. The staff block is a separate
element and is cleanly structured:

    <p><strong>Laurel Siegel</strong><br>
       <em>City Clerk</em><br>
       <strong>Email</strong>: <a href="mailto:lsiegel@medford-ma.gov">..</a>

<strong> is the name, <em> is the post. An <h3>STAFF</h3> separates a department
head from their staff, which is useful to a reader but not to this parser.

THE DEPARTMENT LIST LIVES IN THE NAVIGATION, so the content-only selector that
scrape_rosters uses finds 2 of 94. Links are gathered from the whole page and
only then is each department page content-scoped.

NOT EVERY <strong>/<em> PAIR IS A PERSON. Seen on real pages:
  - "Main Roads" / "(also called main drags)"
  - "Reminder: before you dig, call Dig Safe!" in BOTH tags -- when the two
    carry the same text it is emphasis, not a name and a post
  - "Vacant" where a person would be, with a real title under it

CREDENTIALS ARE STRIPPED. The site writes "Owen Wartella, PE, CPESC, LEED AP"
and "Timothy J. McGivern, PE"; a transcript says "Owen Wartella". Keeping the
letters would stop every name matching.

THE EMAIL CORROBORATES THE NAME BUT IS NOT AUTHORITATIVE. On the city-clerk page
Rich Eliseo's address is split across two <a> tags and the second points at
lyoung@medford-ma.gov -- the city's own copy-paste error. So a mismatch is
recorded and surfaced, never used to rename anyone.

STAFF.JSON IS NOT TRACKED. This script is; the roster it writes is gitignored,
the same call made for addresses.json. Everything in it is already public on
medfordma.org, one department page at a time -- but a single committed file is
a ready-made mailing list for every city employee, and that aggregation is the
objection. Re-run the scraper rather than committing its output.

    python scrape_staff.py             # dry run: report what parses
    python scrape_staff.py --apply     # write staff.json (gitignored)
"""

import argparse
import collections
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

BASE = "https://www.medfordma.org"
INDEX = BASE + "/departments"
UA = {"User-Agent": "Mozilla/5.0 (compatible; medford-transcripts/1.0)"}
OUT = "staff.json"

# Letters after a comma are credentials, not part of the name.
CREDENTIALS = re.compile(
    r",\s*(?:PE|P\.E\.|CPESC|LEED\s*AP|AICP|Esq\.?|CPA|MBA|MPA|PhD|Ph\.D\.|MD|RN|"
    r"JD|CFM|CFE|CMMC|MCPPO|RS|CHO|LSP|PLS|AIA|GISP)\b\.?", re.I)
NAME = re.compile(r"^[A-Z][A-Za-z.'\-]+(?:\s+[A-Za-z.'\-]+){1,3}$")
VACANT = re.compile(r"\bvacan(?:t|cy)\b", re.I)
# A post, not a sentence. Titles are short and do not end in punctuation.
TITLE_OK = re.compile(r"^[A-Z][A-Za-z/&.,'\- ]{2,58}$")
NOT_A_TITLE = re.compile(
    r"\b(reminder|please|click|call|visit|hours|phone|email|address|room|"
    r"also called|www|http|form|apply|download|schedule|notice|help|"
    r"volunteer|assist|sign up|drop in|data entry)\b", re.I)
# A post is a noun phrase. It does not end in a full stop -- that is how the
# Council on Aging volunteer listings read ("Help with mailings, filing, or
# data entry in the office.") and how the benefits page names a vendor
# ("AllOne Health."), and both land exactly where a title belongs.
SENTENCE_TITLE = re.compile(r"\.\s*$")
EMAIL = re.compile(r"[\w.\-]+@[\w.\-]+")
PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
# Capitalised and multi-word, but not a person: "Media Requests" sits where a
# name goes on the mayor's page and "Employee Assistance Program" on benefits.
NOT_A_PERSON = re.compile(
    r"(?<![A-Za-z])(programs|program|departments|department|offices|office|"
    r"committee|commission|association|services|service|center|centre|team|"
    r"fund|requests|inquiries|division|board|council|city|medford|roads|"
    r"group|bureau|unit|hotline|assistance|insurance|support|outreach|"
    r"donations|opportunities)(?![a-z])", re.I)
# Where the post stops and the contact block starts. The boundary is a
# lookahead and not \b on purpose: "direct" must not fire on "Director", which
# is how a good third of the real titles start.
FIELD = re.compile(
    r"^\s*(e-?mail|telephone|phone|tel|fax|address|hours|room|mobile|cell|"
    r"direct|website|location)(?![a-z])", re.I)
# Where a post should be, the Elections Commission writes an APPOINTMENT: party,
# term expiry and stipend. That is not a title and must not be stored as one --
# but the expiry is a real dated fact, so it is parsed out instead of dropped.
TERM = re.compile(r"term\s+expires:?\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
PARTY = re.compile(r"(?<![A-Za-z])(Democrat|Republican|Unenrolled|Independent)"
                   r"(?![a-z])", re.I)
# Words that turn a post into a DIFFERENT post, and so must not sit in front of
# one being matched as transcript evidence. A plain word boundary is not enough:
# "Mayor" matches inside "Vice Mayor", which dated Breanna Lungo-Koehn as mayor
# in 2015 off a single garbled roll call, five years before she took office --
# that meeting calls her "Councilor" and "Vice President" throughout. "former"
# is here for the same reason in the other direction.
# Checked in Python AFTER a match rather than as a lookbehind: 17 modifiers in
# two spacings is 34 fixed-width lookbehinds, each retried at every character,
# which took the corpus scan from 3.6 minutes back over ten. Matches are rare,
# so one cheap string test per match costs nothing.
MODIFIER_BEFORE = re.compile(
    r"(?:vice|deputy|assistant|asst\.?|acting|interim|former|ex|senior|junior|"
    r"chief|head|associate|co|late|outgoing|incoming)[\s-]+$", re.I)


def preceded_by_modifier(text, start):
    """Is the post at `start` actually the tail of a longer post?"""
    return bool(MODIFIER_BEFORE.search(text[max(0, start - 16):start]))


def fetch(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=60
    ).read().decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def strip_credentials(name):
    out = CREDENTIALS.sub("", name)
    return clean(out.rstrip(" ,"))


def departments(index_html):
    """{slug: label} for every department linked from the index.

    Gathered from the WHOLE page: the list is a navigation menu, so scoping to
    content first finds 2 of 94.
    """
    found = collections.OrderedDict()
    soup = BeautifulSoup(index_html, "lxml")
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if "/departments/" not in href:
            continue
        slug = href.split("/departments/", 1)[1].strip("/")
        if not slug or "#" in slug or "?" in slug:
            continue
        label = clean(a.get_text(" "))
        if len(label) < 3:
            continue
        found.setdefault(slug, label)
    return found


def content_blocks(page):
    soup = BeautifulSoup(page, "lxml")
    for bad in soup.select("script, style, nav, header, footer, div.fsNavigation"):
        bad.decompose()
    return soup.select("div.fsContent div.fsElementContent") or soup.select("body")


def title_after(p, st):
    """The post written between the name and the first contact field.

    THE SITE DOES NOT KEEP A POST IN ONE TAG, so taking the first <em> loses
    most of it, and silently:

        <em>Interim</em><b> </b><em>Building Commissioner</em>   -> "Interim"
        <strong>Brett Zografos, </strong>Director of <em>HR</em> -> "HR"

    Both read as a plausible title, which is what makes the bug expensive --
    "Interim" and "Human Resources" are exactly the sort of thing a reviewer
    skims past. So the post is everything after the name up to the first
    contact detail, with the name's own text skipped.

    AND THE CONTACT DETAIL IS NOT ALWAYS LABELLED. Most blocks write
    "<strong>Email:</strong> <a>..", but the Prevention & Outreach page writes
    the address as the link text with no label at all:

        <strong>Darline Raymond</strong><br><em>..Liaison</em><br>
        <a href="mailto:draymond@medford-ma.gov">draymond@medford-ma.gov</a>

    Stopping only at a label swallowed the address into the title and the whole
    row then failed validation -- six real staff vanished from one page. So a
    mailto/tel link, an address, or a phone number ends the post too.
    """
    parts = []
    started = False
    for node in p.descendants:
        if node is st:
            started = True
            continue
        if not started or st in node.parents:
            continue                      # the name's own strings
        name = getattr(node, "name", None)
        if name in ("strong", "b"):
            text = clean(node.get_text(" "))
            if FIELD.match(text):
                break
            if NAME.match(text) and len(text.split()) > 1:
                break                     # a second person in the same <p>
            continue                      # its strings arrive on their own
        if name == "a":
            href = (node.get("href") or "").lower()
            if href.startswith("mailto:") or href.startswith("tel:"):
                break                     # the contact block, labelled or not
            continue
        if name is not None:
            if name in ("em", "span", "i", "u"):
                continue
            if FIELD.match(clean(node.get_text(" "))):
                break
            continue
        text = clean(node)
        if FIELD.match(text) or EMAIL.search(text) or PHONE.search(text):
            break
        parts.append(str(node))
    return clean(" ".join(parts)).lstrip(", -" + chr(0x2013) + chr(0x2014)).strip()


CONTAINERS = ("p", "div", "li")


def staff_blocks(block):
    """The innermost containers that could hold one person.

    NOT ONLY <p>. The cemetery page writes its department head in a <p> and the
    clerk under it in a bare <div>:

        <h2>STAFF</h2>
        <div><strong>Deb Nee</strong><br><em>Principal Clerk</em>..</div>

    so walking paragraphs alone found the superintendent and silently dropped
    the only other person in the department. Divs have to be taken leaf-first:
    the content wrapper is itself a div containing every <p> on the page, and
    accepting it would read the whole page as one person.
    """
    for node in block.find_all(CONTAINERS):
        if node.name != "p" and node.find(CONTAINERS) is not None:
            continue                      # a wrapper, not a leaf
        yield node


def body_role(label):
    """How a member of this body is addressed, from the body's own name.

    "Elections Commission" -> "Elections Commissioner". Only used where the page
    gives an appointment instead of a post, and recorded with
    title_source="derived from body name" so a reviewer can see it was not
    written on the page. Returns None when nothing defensible can be built --
    inventing a post is worse than having none.
    """
    label = clean(label)
    m = re.match(r"^(.*?)\s+Commission$", label, re.I)
    if m:
        return clean(m.group(1)) + " Commissioner"
    m = re.match(r"^(.*?)\s+Board$", label, re.I)
    if m:
        return clean(m.group(1)) + " Board Member"
    return None


def staff_on(page, dept_label=""):
    """[{name, title, email, email_agrees, party, term_expires}] for one page."""
    out = []
    seen_here = set()
    for block in content_blocks(page):
        for p in staff_blocks(block):
            st = p.find(["strong", "b"])
            if not st:
                continue
            # NO EMPHASIS REQUIREMENT. <em> around the post was treated as the
            # signal that a block describes a person, and it is not one: the
            # whole Recreation department writes the post as bare text between
            # <br> tags --
            #
            #   <strong>Kevin J. Bailey</strong><br> Director of Recreation<br>
            #
            # -- so requiring <em> silently skipped a department of three, the
            # director included. (Prevention & Outreach uses <i>, which is why
            # the gate was widened before being removed.) What a person looks
            # like is decided by NAME, TITLE_OK, NOT_A_TITLE and NOT_A_PERSON
            # below; emphasis is just one way this CMS happens to mark it up.
            name = strip_credentials(clean(st.get_text(" ")))
            title = title_after(p, st)
            if not name or not title:
                continue
            if clean(st.get_text(" ")) == title:
                continue                      # emphasis, not a name and a post
            # An appointment, not a post: "Democrat, term expires: 3/31/2030,
            # $1,250 stipend". Storing that string as a title would put a party
            # registration and a dollar figure in front of a speaker's name, so
            # the post is named after the body and the dates are kept apart.
            party, term = None, None
            mterm = TERM.search(title)
            if mterm:
                mo, day, yr = mterm.groups()
                term = "%s-%02d-%02d" % (yr, int(mo), int(day))
                mp = PARTY.search(title)
                party = mp.group(1).title() if mp else None
                title = body_role(dept_label)
                if not title:
                    continue              # no defensible post to name
            if VACANT.search(name) or VACANT.search(title):
                continue
            if not NAME.match(name) or len(name.split()) < 2:
                continue
            if NOT_A_PERSON.search(name):
                continue
            if not TITLE_OK.match(title) or NOT_A_TITLE.search(title):
                continue
            if SENTENCE_TITLE.search(title):
                continue
            mail = None
            agrees = None
            a = p.find("a", href=re.compile(r"^mailto:", re.I))
            if a:
                m = EMAIL.search(a.get("href") or "")
                if m:
                    mail = m.group(0).lower()
                    # first initial + surname is the house convention.
                    # Punctuation is dropped from the surname first: O'Connor
                    # is moconnor@, so comparing "o'conn" reported the city's
                    # own page as wrong.
                    last = re.sub(r"[^a-z]", "", name.split()[-1].lower())
                    agrees = bool(last) and last[:6] in mail.split("@")[0]
            # content_blocks can hand back nested elements, and a leaf can now
            # be reached twice. Same name and post on one page is one person.
            if (name.lower(), title) in seen_here:
                continue
            seen_here.add((name.lower(), title))
            row = {"name": name, "title": title, "email": mail,
                   "email_agrees": agrees}
            if party:
                row["party"] = party
            if term:
                row["term_expires"] = term
            if mterm:
                row["title_source"] = "derived from body name"
            out.append(row)
    return out


def byname_of(rows):
    return {r["name"]: r["title"] for r in rows}


def self_test():
    """Literal fixtures, run before any fetch -- the same gate scrape_rosters uses."""
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (label, got, want))

    page = (
        '<div class="fsElement fsContent"><div class="fsElementContent">'
        "<p><strong>Laurel Siegel</strong><br><em>City Clerk</em><br>"
        '<strong>Email</strong>: <a href="mailto:lsiegel@medford-ma.gov">x</a></p>'
        "<h3>STAFF</h3>"
        "<p><strong>Rich Eliseo</strong><br><em>Assistant City Clerk</em><br>"
        '<strong>Email</strong>: <a href="mailto: reliseo@medford-ma.gov">x</a>'
        '<a href="mailto:lyoung@medford-ma.gov">y</a></p>'
        "<p><strong>Lisa Young</strong><br><em>Head Clerk</em><br>"
        '<strong>Email</strong>: <a href="mailto:lyoung@medford-ma.gov">x</a></p>'
        "<p><b>Vacant</b><br><em>Principal Clerk</em></p>"
        "<p><strong>Main Roads</strong><br><em>(also called main drags)</em></p>"
        "<p><strong>Reminder: before you dig, call Dig Safe!</strong><br>"
        "<em>Reminder: before you dig, call Dig Safe!</em></p>"
        "<p><strong>Owen Wartella, PE, CPESC, LEED AP</strong><br>"
        "<em>City Engineer</em></p>"
        # verbatim from /departments/building-department -- the post is two
        # <em> tags with a <b> space wedged between them
        "<p><b>Bill Forte</b><br> <em>Interim</em><b> </b>"
        "<em>Building Commissioner</em><br> <strong>Email</strong>: "
        '<a href="mailto:wforte@medford-ma.gov">x</a></p>'
        # verbatim from /departments/human-resources -- the post starts as bare
        # text outside any tag and the name carries the comma
        "<p><strong>Brett Zografos, </strong>Director of "
        "<em>Human Resources </em><br> <strong>Phone:</strong> "
        '<a href="tel:(781) 393-2407">x</a></p>'
        # verbatim from /departments/mayors-office -- a mailbox, not a person
        "<p><strong>Media Requests</strong><br><em>Director of Communications"
        '</em><br><strong>Email</strong>: <a href="mailto:jpiques@medford-ma.gov">x</a></p>'
        # verbatim from /departments/human-resources/employee-benefits
        "<p><b>Employee Assistance Program </b>through "
        "<em><strong>AllOne Health.</strong></em></p>"
        # verbatim from /departments/health-department/office-prevention-outreach
        # -- no "Email:" label, the address IS the link text
        "<p><strong>Darline Raymond</strong><br> "
        "<em>Haitian-Creole Community Liaison</em><br> "
        '<a href="mailto:draymond@medford-ma.gov">draymond@medford-ma.gov</a></p>'
        # same page -- the post is in <i>, not <em>
        "<p><strong>Matisse Monty</strong><br> "
        "<i>Regional Prevention Strategist</i><br> "
        '<strong>Email:</strong><em> </em>'
        '<a href="mailto:mmonty@medford-ma.gov">mmonty@medford-ma.gov</a></p>'
        # verbatim from /departments/civil-defense -- an apostrophe in the
        # surname must not read as a mismatched address
        "<p><strong>MaryAnn O'Connor</strong><br><em>Director</em><br>"
        '<strong>Email</strong>: <a href="mailto:moconnor@medford-ma.gov">x</a></p>'
        # verbatim from /departments/cemetery -- the second person on the page
        # is in a bare <div>, not a <p>
        "<h2>STAFF</h2>"
        "<div><strong>Deb Nee</strong><br> <em>Principal Clerk</em><br> "
        '<strong>Phone:</strong>&nbsp;(<a href="tel:781-393-2487">781)-393-2487</a>'
        "</div>"
        # verbatim from /departments/recreation -- no emphasis anywhere on the
        # page; the post is bare text between <br> tags
        "<p><strong>Kevin J. Bailey</strong><br> Director of Recreation<br> "
        '<strong>Email:</strong><a href="mailto: kbailey@medford-ma.gov">'
        " kbailey@medford-ma.gov</a></p>"
        # a business with an address where a post would go -- must stay out
        "<p><strong>Blue Pearl Pet Hospital</strong><br>"
        "<em>56 Roland St., Charlestown, MA</em></p>"
        "</div></div>")
    got = staff_on(page)
    names = [r["name"] for r in got]
    check("city clerk found",
          ("Laurel Siegel", "City Clerk") in [(r["name"], r["title"]) for r in got],
          True)
    check("staff after the STAFF heading", "Rich Eliseo" in names, True)
    check("second staff member", "Lisa Young" in names, True)
    check("Vacant skipped", any("Vacant" in n for n in names), False)
    check("non-person skipped", "Main Roads" in names, False)
    check("same text in both tags skipped",
          any(n.startswith("Reminder") for n in names), False)
    check("credentials stripped", "Owen Wartella" in names, True)
    check("post split across two <em>", byname_of(got).get("Bill Forte"),
          "Interim Building Commissioner")
    check("post starting outside any tag", byname_of(got).get("Brett Zografos"),
          "Director of Human Resources")
    check("mailbox label skipped", "Media Requests" in names, False)
    check("programme skipped",
          any(n.startswith("Employee Assistance") for n in names), False)
    check("unlabelled contact ends the post",
          byname_of(got).get("Darline Raymond"), "Haitian-Creole Community Liaison")
    check("post set in <i>", byname_of(got).get("Matisse Monty"),
          "Regional Prevention Strategist")
    check("apostrophe surname corroborates",
          [r["email_agrees"] for r in got if r["name"].startswith("MaryAnn")],
          [True])
    check("person in a bare <div>", byname_of(got).get("Deb Nee"),
          "Principal Clerk")
    check("post with no emphasis at all", byname_of(got).get("Kevin J. Bailey"),
          "Director of Recreation")
    check("business with an address skipped",
          "Blue Pearl Pet Hospital" in names, False)
    # the wrapper div holds every <p> above; reading it as a person would
    # return one row whose "title" is the whole page
    check("wrapper div not read as a person",
          [r["name"] for r in got if len(r["title"]) > 60], [])
    check("count", len(got), 11)

    byname = {r["name"]: (r["title"], r["email"], r["email_agrees"])
              for r in got}
    check("title read", byname["Lisa Young"][0], "Head Clerk")
    # the city's own error: Eliseo's block links lyoung@ second. We take the
    # FIRST mailto, so this still agrees -- but the flag must exist and be used
    # for reporting rather than for renaming.
    check("email corroboration recorded", byname["Laurel Siegel"][2], True)

    # --- the alias merge, and the two things it must refuse to merge ---------
    def person(name, title, dept, mail, agrees):
        return {"name": name, "title": title, "department": dept,
                "email": mail, "email_agrees": agrees, "url": "", "also": []}

    pp = {
        "michael roberts": person("Michael Roberts", "Federal Funds Manager",
                                  "Finance", "mroberts@medford-ma.gov", True),
        "mike roberts": person("Mike Roberts", "Federal Funds Manager",
                               "ARPA", "mroberts@medford-ma.gov", True),
        # a role mailbox two people share: merging would invent a person
        "tanya arruda": person("Tanya Arruda", "Manager", "Credit Union",
                               "creditunion@medford-ma.gov", False),
        "deborah petrone": person("Deborah Petrone", "Customer Service",
                                  "Credit Union", "creditunion@medford-ma.gov",
                                  False),
        # same personal-looking address, different surnames -> leave alone
        "ann smith": person("Ann Smith", "Clerk", "X", "shared@x.gov", True),
        "bob jones": person("Bob Jones", "Clerk", "X", "shared@x.gov", True),
    }
    merged = merge_aliases(pp)
    check("nickname merged", sorted(pp), ["ann smith", "bob jones",
                                          "deborah petrone", "michael roberts",
                                          "tanya arruda"])
    check("formal name kept", pp["michael roberts"]["name"], "Michael Roberts")
    check("nickname kept as alias", pp["michael roberts"].get("aliases"),
          ["Mike Roberts"])
    check("other post recorded", [a["department"] for a in
                                  pp["michael roberts"]["also"]], ["ARPA"])
    check("role mailbox not merged", len(merged), 1)

    # --- transcript evidence: the post must sit NEXT TO the surname ----------
    tp = {
        "stephen brogan": {"name": "Stephen Brogan", "title": "Superintendent"},
        "owen wartella": {"name": "Owen Wartella", "title": "City Engineer"},
        "laurel siegel": {"name": "Laurel Siegel", "title": "City Clerk",
                          "history": [{"title": "Assistant City Clerk"}]},
    }
    pats = title_patterns(tp)
    big = re.compile("|".join("(%s)" % p for p in pats), re.I)
    order = list(pats.values())

    def said(text):
        hits = set()
        for m in big.finditer(text):
            if m.lastindex and not preceded_by_modifier(text, m.start()):
                for key, title in order[m.lastindex - 1]:
                    hits.add(tp[key]["name"])
        return sorted(hits)

    check("post beside surname is evidence",
          said("Superintendent Brogan said the cemetery is full"),
          ["Stephen Brogan"])
    check("ASR lowercase still matches", said("superintendent brogan said"),
          ["Stephen Brogan"])
    check("full name matches", said("City Engineer Owen Wartella presented"),
          ["Owen Wartella"])
    # the case the whole adjacency rule exists for: the SCHOOL superintendent
    # must not date the CEMETERY superintendent
    check("another holder of the same post is not evidence",
          said("Superintendent Edouard-Vincent reported"), [])
    check("a bare post is not evidence",
          said("The Superintendent spoke at length"), [])
    check("a bare surname is not evidence",
          said("Brogan said the cemetery is full"), [])
    check("a former post is evidence for that post",
          said("Assistant City Clerk Siegel took the roll"), ["Laurel Siegel"])

    # --- a post must not match as the SUFFIX of a longer post ---------------
    tp2 = {"breanna lungo-koehn": {"name": "Breanna Lungo-Koehn", "title": "Mayor"}}
    rx2 = [re.compile(p, re.I) for p in title_patterns(tp2)]

    def mayor(text):
        return any(not preceded_by_modifier(text, m.start())
                   for r in rx2 for m in r.finditer(text))

    # the real one: a single garbled 2015 roll call dated her five years before
    # she took office, in a meeting that calls her Councilor throughout
    check("'Vice Mayor X' is not 'Mayor X'", mayor("Vice Mayor Lungo-Koehn?"), False)
    check("'former Mayor X' is not evidence",
          mayor("former Mayor Lungo-Koehn attended"), False)
    check("plain 'Mayor X' still counts",
          mayor("Mayor Lungo-Koehn delivered the budget"), True)

    for f in fails:
        print("  FAIL %s" % f)
    print("self-test: %d checks, %d failed" % (38, len(fails)))
    return 1 if fails else 0


def merge_aliases(people):
    """Fold "Mike Roberts" into "Michael Roberts" as an alias. Returns merges.

    The city writes the same person both ways -- Federal Funds Manager appears
    as Michael Roberts under Finance and Mike Roberts under ARPA, both
    mroberts@ -- and two records would have the matcher scoring one name form
    against a corpus that uses the other.

    TWO GUARDS, BECAUSE A WRONG MERGE INVENTS A PERSON. A shared address only
    means one person if the address is personal: cemetery@, creditunion@ and
    mayor@ are role mailboxes that several staff legitimately share, so only
    rows whose email_agrees is True are eligible. And the surnames must match,
    so a household sharing an address is not collapsed.

    The longer name form is canonical because it is the one a formal record
    carries; the nickname survives as an alias, so both still match. (A speaker
    who introduces themselves as Bob is a separate question, settled in the
    transcript and not here.)
    """
    bymail = collections.defaultdict(list)
    for key, v in people.items():
        if v.get("email") and v.get("email_agrees") is True:
            bymail[v["email"]].append(key)
    merges = []
    for mail, keys in bymail.items():
        if len(keys) < 2:
            continue
        surnames = set(k.split()[-1] for k in keys)
        if len(surnames) != 1:
            continue                      # different people, shared mailbox
        keys.sort(key=lambda k: (-len(people[k]["name"]), k))
        keep, rest = keys[0], keys[1:]
        for k in rest:
            gone = people.pop(k)
            people[keep].setdefault("aliases", []).append(gone["name"])
            if gone["title"] != people[keep]["title"] or \
                    gone["department"] != people[keep]["department"]:
                people[keep]["also"].append({"title": gone["title"],
                                             "department": gone["department"]})
            people[keep]["also"].extend(gone.get("also") or [])
            merges.append((people[keep]["name"], gone["name"], mail))
    return merges


def title_patterns(people):
    """{regex: person key} for "<post> <surname>" as a transcript would say it.

    THE ADJACENCY IS THE WHOLE SAFEGUARD. A bare post is useless as evidence --
    "Superintendent" in a School Committee transcript is the school
    superintendent, not the Cemetery Superintendent, and "Director" belongs to
    a dozen people. Requiring the surname next to the post is what makes a hit
    mean something: "Superintendent Brogan" can only be one man.

    Built ONLY from posts already in staff.json. This pass may move a date
    earlier; it may never invent a person or a post. An earlier attempt at a
    title cue in this project reported "0 contradictions" while being 29% wrong,
    because it scored the unverifiable remainder as success -- so the rule here
    is that evidence has to name its source and change nothing else.
    """
    pats = {}
    for key, v in people.items():
        titles = [v.get("title")] + [h.get("title") for h in (v.get("history") or [])]
        parts = v["name"].split()
        surname, first = parts[-1], parts[0]
        if len(surname) < 4:
            continue                      # too short to be evidence on its own
        for t in [x for x in titles if x]:
            # the post as written, then optionally the first name, then surname
            t_pat = r"\s+".join(re.escape(w) for w in t.split())
            pat = r"(?<![A-Za-z])%s,?\s+(?:%s\s+)?%s(?![A-Za-z])" % (
                t_pat, re.escape(first), re.escape(surname))
            pats.setdefault(pat, []).append((key, t))
    return pats


WORD = re.compile(r"[a-z]+")


def surname_words(name):
    return [w for w in WORD.findall(name.split()[-1].lower()) if len(w) >= 4]


def patterns_by_surname(people):
    """{surname word: [(compiled pattern, key, title)]}, see title_patterns.

    GROUPED BECAUSE ONE BIG ALTERNATION IS UNUSABLY SLOW. Scanning every post
    as a single 100-branch regex cost ~2.9s per transcript -- the engine
    retries all branches at every character -- which is 114 minutes for the
    corpus. Gating on surnames first did not help: 169 of 200 transcripts
    contain at least one roster surname, because the roster includes Young,
    Kelly, Evans, Hunt, Moore and White. Running a handful of single-person
    patterns, only for the surnames a file actually contains, is the fix.
    """
    out = collections.defaultdict(list)
    for pat, owners in title_patterns(people).items():
        rx = re.compile(pat, re.I)
        for key, title in owners:
            words = surname_words(people[key]["name"])
            if words:
                out[words[-1]].append((rx, key, title))
    return out


def mine_transcripts(people, limit=0, verbose=False):
    """Push first_seen earlier using the corpus. Returns a stats counter.

    Reads the .srt beside each page -- the srt is the source text, the HTML is
    a rendering of it -- and dates a hit by the MEETING date, not the upload
    date: 23% of Castus titles carry no date and upload can trail the meeting
    by months, so meeting date is the only one that says when the words were
    spoken. video_data carries both.
    """
    import utils
    bysurname = patterns_by_surname(people)
    if not bysurname:
        return collections.Counter()
    surnames = set(bysurname)

    vd = utils.get_video_data()
    stats = collections.Counter()
    hits = {}
    files = []
    for yt, e in vd.items():
        d = "%s_%s" % (e.get("upload_date"), yt)
        srt = os.path.join(d, d + ".srt")
        if os.path.exists(srt):
            files.append((srt, (e.get("date") or "")[:10], yt))
    files.sort(key=lambda x: x[1])
    if limit:
        files = files[:limit]
    for n, (srt, mdate, yt) in enumerate(files, 1):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", mdate or ""):
            stats["skipped: no meeting date"] += 1
            continue
        try:
            text = io.open(srt, encoding="utf-8", errors="replace").read()
        except Exception:
            stats["unreadable"] += 1
            continue
        stats["transcripts read"] += 1
        # one cheap pass: which roster surnames does this transcript contain?
        present = set(WORD.findall(text.lower())) & surnames
        if not present:
            stats["no roster surname present"] += 1
            continue
        for part in present:
            for rx, key, title in bysurname[part]:
                # the file has ONE date, so any clean hit will do -- but walk
                # past hits that are only the tail of a longer post
                m = None
                for cand in rx.finditer(text):
                    if not preceded_by_modifier(text, cand.start()):
                        m = cand
                        break
                    stats["suffix of a longer post"] += 1
                if not m:
                    continue
                hits.setdefault((key, title), []).append(
                    (mdate, yt, clean(m.group(0))))
        if verbose and n % 250 == 0:
            print("    %d/%d transcripts, %d dated" % (n, len(files), len(hits)))

    for (key, title), found in sorted(hits.items()):
        found.sort()
        mdate, yt, quote = found[0]
        # ONE MENTION IN ONE VIDEO IS NOT A DATE. "Mayor Lungo-Koehn" appears
        # seven times in a School Committee roll call the corpus dates
        # 2017-06-24 -- correct reading (the mayor chairs the committee ex
        # officio), wrong date: the 2017 mayor was Stephanie Muccini Burke, and
        # Member Reinfeld did not join until 2022. The video's own title says
        # 06.24.2017, so this is bad source metadata, and no amount of pattern
        # care can see it from inside one file. What CAN be seen is whether any
        # OTHER meeting agrees, so that is recorded and left for a reviewer.
        others = [d for d, y, q in found if y != yt]
        corroborated = any(abs((int(d[:4]) * 12 + int(d[5:7]))
                               - (int(mdate[:4]) * 12 + int(mdate[5:7]))) <= 12
                           for d in others)
        v = people.get(key)
        if not v:
            continue
        if title != v.get("title"):
            stats["evidence for a former post"] += 1
            for h in (v.get("history") or []):
                if h.get("title") == title and (not h.get("first_seen")
                                                or mdate < h["first_seen"]):
                    h["first_seen"] = mdate
                    h["first_seen_source"] = "transcript %s" % yt
            continue
        if v.get("first_seen") and mdate >= v["first_seen"]:
            stats["no earlier than known"] += 1
            continue
        stats["first_seen moved earlier"] += 1
        stats["corroborated" if corroborated else
              "UNCORROBORATED (one video)"] += 1
        v["first_seen"] = mdate
        v["first_seen_source"] = "transcript %s" % yt
        v["first_seen_corroborated"] = corroborated
        v["mentions"] = len({y for d, y, q in found})
        v.setdefault("evidence", []).append(
            {"date": mdate, "video": yt, "said": quote[:90]})
    return stats


def carry_dates(people, today):
    """Give every record observed date bounds, carried across runs.

    A TITLE IS A FACT ABOUT A NAME AT A TIME, which is the same rule
    DATED_REPLACEMENTS follows. One scrape only ever observes "today", so the
    bounds are built by merging into the previous staff.json instead of
    overwriting it:

      first_seen  earliest date this person was observed in THIS post
      last_seen   most recent date, i.e. today for anyone still listed
      history     posts they used to hold, with the bounds we saw them in
      left_site   set when a name disappears from the city's pages

    NOBODY IS DELETED when they drop off the site. A transcript from 2019 still
    needs to know who the City Clerk was in 2019, so a departed employee keeps
    their record and gains left_site; dropping them would discard exactly the
    dated fact this file exists to hold. For the same reason first_seen is only
    ever moved EARLIER, never later.
    """
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = (json.load(io.open(OUT, encoding="utf-8")) or {}).get("people") or {}
        except Exception as e:
            print("  WARNING: could not read %s (%s); dates restart" % (OUT, e))
            prev = {}
    stats = collections.Counter()
    bykey = {k.lower(): k for k in prev}
    for key, v in people.items():
        was = prev.get(bykey.get(key, ""))
        if not was:
            v["first_seen"] = v["last_seen"] = today
            stats["new this run"] += 1
            continue
        v["last_seen"] = today
        v["first_seen"] = min(was.get("first_seen") or today, today)
        v["history"] = list(was.get("history") or [])
        if was.get("title") and was["title"] != v["title"]:
            v["history"].append({"title": was["title"],
                                 "department": was.get("department"),
                                 "first_seen": was.get("first_seen"),
                                 "last_seen": was.get("last_seen")})
            v["first_seen"] = today       # the NEW post starts now
            stats["changed post"] += 1
        else:
            stats["unchanged"] += 1
        # transcript evidence already earned stays put
        for k in ("first_seen_source", "evidence"):
            if was.get(k):
                v[k] = was[k]
        if was.get("first_seen") and v["first_seen"] > was["first_seen"]                 and was["title"] == v["title"]:
            v["first_seen"] = was["first_seen"]
    for name, was in prev.items():
        if name.lower() in people or was.get("left_site"):
            if name.lower() not in people and was.get("left_site"):
                people[name.lower()] = dict(was, name=name)
                stats["still gone"] += 1
            continue
        gone = dict(was, name=name)
        gone["left_site"] = today
        people[name.lower()] = gone
        stats["left the site"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--from-transcripts", action="store_true",
                    help="scan the corpus to push first_seen earlier")
    ap.add_argument("--transcript-limit", type=int, default=0)
    args = ap.parse_args()
    if self_test():
        print("REFUSING to continue: patterns failed their own tests.")
        return 1

    depts = departments(fetch(INDEX))
    print("departments linked: %d" % len(depts))
    people, seen, stats = {}, set(), collections.Counter()
    for i, (slug, label) in enumerate(depts.items(), 1):
        if args.limit and i > args.limit:
            break
        try:
            page = fetch("%s/departments/%s" % (BASE, slug))
        except Exception as e:
            stats["fetch failed"] += 1
            print("  %-40s FETCH FAILED %s" % (label[:40], str(e)[:40]))
            continue
        rows = staff_on(page, label)
        stats["departments read"] += 1
        if rows:
            stats["departments with staff"] += 1
        for row in rows:
            name, title = row["name"], row["title"]
            mail, agrees = row["email"], row["email_agrees"]
            key = name.lower()
            stats["people"] += 1
            if agrees is False:
                stats["email disagrees with name"] += 1
            if key in seen:
                people[key]["also"].append({"title": title, "department": label})
                continue
            seen.add(key)
            people[key] = {"name": name, "title": title, "department": label,
                           "email": mail, "email_agrees": agrees,
                           "url": "%s/departments/%s" % (BASE, slug), "also": []}
            for extra in ("party", "term_expires", "title_source"):
                if row.get(extra):
                    people[key][extra] = row[extra]
        if rows:
            print("  %-40s %d" % (label[:40], len(rows)))
        time.sleep(0.25)

    merges = merge_aliases(people)
    today = time.strftime("%Y-%m-%d")
    datestats = carry_dates(people, today)
    minestats = collections.Counter()
    if getattr(args, "from_transcripts", False):
        print()
        print("mining transcripts for earlier dates ...")
        minestats = mine_transcripts(people, args.transcript_limit, verbose=True)
    print()
    for k, v in stats.most_common():
        print("  %-30s %d" % (k, v))
    print()
    for k in ("new this run", "unchanged", "changed post", "left the site",
              "still gone"):
        if datestats.get(k):
            print("  dates: %-23s %d" % (k, datestats[k]))
    for k, n in minestats.most_common():
        print("  corpus: %-23s %d" % (k, n))
    if merges:
        print()
        print("MERGED AS ALIASES (%d):" % len(merges))
        for keep, alias, mail in merges:
            print("  %-24s <- %-24s %s" % (keep, alias, mail))
    print()
    print("UNIQUE PEOPLE: %d" % len(people))
    for v in sorted(people.values(), key=lambda x: x["department"] + x["name"]):
        flag = "" if v["email_agrees"] is not False else "   <- email disagrees"
        extra = ("  (+%d other post)" % len(v["also"])) if v["also"] else ""
        alias = ("  aka %s" % ", ".join(v["aliases"])) if v.get("aliases") else ""
        print("  %-26s %-34s %s%s%s%s" % (v["name"][:26], v["title"][:34],
                                          v["department"][:22], alias, extra, flag))
    if args.apply:
        out = {"_comment": ["City staff and titles scraped from medfordma.org/departments.",
                            "NOT TRACKED -- gitignored, same handling as addresses.json. "
                            "Every field here is already public on the city's own "
                            "department pages, but one file turns a per-department "
                            "listing into a mailing list for every city employee. "
                            "Re-derive it with scrape_staff.py --apply instead of "
                            "committing it.",
                            "email_agrees is corroboration only -- the city's own pages "
                            "contain at least one wrong mailto."],
               "source": INDEX,
               "scraped": time.strftime("%Y-%m-%d"),
               "people": {v["name"]: {kk: vv for kk, vv in v.items() if kk != "name"}
                          for v in people.values()}}
        io.open(OUT, "w", encoding="utf-8", newline="\n").write(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        print("wrote %s (%d people)" % (OUT, len(people)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
