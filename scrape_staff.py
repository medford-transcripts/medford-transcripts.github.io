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
    r"also called|www|http|form|apply|download|schedule|notice)\b", re.I)
EMAIL = re.compile(r"[\w.\-]+@[\w.\-]+")
PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
# Capitalised and multi-word, but not a person: "Media Requests" sits where a
# name goes on the mayor's page and "Employee Assistance Program" on benefits.
NOT_A_PERSON = re.compile(
    r"(?<![A-Za-z])(programs|program|departments|department|offices|office|"
    r"committee|commission|association|services|service|center|centre|team|"
    r"fund|requests|inquiries|division|board|council|city|medford|roads|"
    r"group|bureau|unit|hotline|assistance|insurance)(?![a-z])", re.I)
# Where the post stops and the contact block starts. The boundary is a
# lookahead and not \b on purpose: "direct" must not fire on "Director", which
# is how a good third of the real titles start.
FIELD = re.compile(
    r"^\s*(e-?mail|telephone|phone|tel|fax|address|hours|room|mobile|cell|"
    r"direct|website|location)(?![a-z])", re.I)


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


def staff_on(page):
    """[(name, title, email_or_None, email_agrees)] from one department page."""
    out = []
    for block in content_blocks(page):
        for p in block.find_all("p"):
            st = p.find(["strong", "b"])
            # <i> counts: the Prevention & Outreach page sets Matisse Monty's
            # post in <i> while every other block on the site uses <em>, and
            # requiring <em> dropped her.
            em = p.find(["em", "i"])
            if not st or not em:
                continue
            name = strip_credentials(clean(st.get_text(" ")))
            title = title_after(p, st)
            if not name or not title:
                continue
            if clean(st.get_text(" ")) == title:
                continue                      # emphasis, not a name and a post
            if VACANT.search(name) or VACANT.search(title):
                continue
            if not NAME.match(name) or len(name.split()) < 2:
                continue
            if NOT_A_PERSON.search(name):
                continue
            if not TITLE_OK.match(title) or NOT_A_TITLE.search(title):
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
            out.append((name, title, mail, agrees))
    return out


def byname_of(rows):
    return {n: t for n, t, _, _ in rows}


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
        "</div></div>")
    got = staff_on(page)
    names = [n for n, t, m, a in got]
    check("city clerk found", ("Laurel Siegel", "City Clerk") in [(n, t) for n, t, _, _ in got], True)
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
          [a for n, t, m, a in got if n.startswith("MaryAnn")], [True])
    check("count", len(got), 9)

    byname = {n: (t, m, a) for n, t, m, a in got}
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

    for f in fails:
        print("  FAIL %s" % f)
    print("self-test: %d checks, %d failed" % (23, len(fails)))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
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
        rows = staff_on(page)
        stats["departments read"] += 1
        if rows:
            stats["departments with staff"] += 1
        for name, title, mail, agrees in rows:
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
        if rows:
            print("  %-40s %d" % (label[:40], len(rows)))
        time.sleep(0.25)

    merges = merge_aliases(people)
    print()
    for k, v in stats.most_common():
        print("  %-30s %d" % (k, v))
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
