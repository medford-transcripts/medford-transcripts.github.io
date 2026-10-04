"""Resolve the role to show beside a speaker's name, AS OF THE MEETING DATE.

A TITLE IS A FACT ABOUT A NAME AT A TIME, which is the rule DATED_REPLACEMENTS
follows and the reason this takes a date rather than answering "currently".
Breanna Lungo-Koehn is Mayor in a 2026 transcript and Councilor in a 2015 one,
and the 2015 page must not say Mayor.

THREE SOURCES, most authoritative first:
    councilors.json      elected office, by year
    rosters.json         boards and commissions, with term end dates
    staff_titles.json    appointed city staff, with observed date bounds

MOST SPECIFIC OFFICE WINS. A council president is "President", not "Councilor";
both are true and only one is worth printing.

BODY-QUALIFIED ONLY WHEN IT IS NOT THIS BODY'S MEETING. "President Bears" at a
council meeting is unambiguous. The same man at a School Committee meeting is
"CC President Bears", because that committee has its own chair and an
unqualified "President" would read as though he chaired it.

FULL NAMES ONLY, WHICH IS THE WHOLE SAFETY STORY. 632 of 1,954 speaker labels
in the corpus are a single word, and 228 of those are the literal string
"Clerk" -- a role, not a person. Matching on a surname would attach Darsy
Rodriguez's post to Councilor Rodriguez, and the Retirement Board's Retiree
Analyst Jennifer Intoppa's post to Councilor Intoppa. A role printed against
the wrong person is a false claim about a real public official, which is worse
than printing nothing, so a label that is not a full name gets no role.

ROLES ARE NOT PRINTED FOR BOARD MEMBERSHIP AS SUCH. "Member" and "Full Member"
say nothing a reader does not already know from the page they are on.
"""

import io
import json
import os
import re

COUNCILORS_FILE = "councilors.json"
ROSTERS_FILE = "rosters.json"
STAFF_FILE = "staff_titles.json"

YEAR = re.compile(r"^(19|20)\d\d$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# How an elected position is spoken, most specific first.
ELECTED = (
    ("mayor",                  "Mayor",          "City"),
    ("city_council_president", "President",      "CC"),
    ("city_council_vice",      "Vice President", "CC"),
    ("city_council",           "Councilor",      "CC"),
    ("school_committee_chair", "Chair",          "MPS"),
    ("school_committee_vice",  "Vice Chair",     "MPS"),
    ("school_committee",       "Member",         "MPS"),
)
# Plain membership adds nothing beside a name on that body's own page.
BOARD_SKIP = {"member", "full member", "associate member", "alternate",
              "staff liaison"}
# A post this long crowds the name it is meant to annotate.
MAX_TITLE = 34

_cache = {}


def _load(path):
    if path not in _cache:
        try:
            with io.open(path, encoding="utf-8") as fp:
                _cache[path] = json.load(fp)
        except Exception:
            _cache[path] = {}
    return _cache[path]


def is_full_name(name):
    """Two or more words, no role words. See the module docstring."""
    n = (name or "").strip()
    if len(n.split()) < 2:
        return False
    if "SPEAKER_" in n or n.lower() in ("unidentified", "none"):
        return False
    return True


def elected_title(name, year, councilors=None):
    """(spoken title, body) held that year, most specific office first."""
    c = councilors if councilors is not None else _load(COUNCILORS_FILE)
    rec = (c.get(name) or {}).get(str(year))
    if not isinstance(rec, dict):
        return None, None
    held = set(rec.get("position") or [])
    for key, spoken, body in ELECTED:
        if key in held:
            return spoken, body
    return None, None


def board_title(name, meeting_type, rosters=None):
    """A role ON the body that is meeting, e.g. Chair of the Historical Commission.

    Only that body's own roster is consulted. Someone who chairs one commission
    and sits on another is "Chair" at the first and unannotated at the second,
    which is the honest reading of either page.
    """
    import utils
    r = rosters if rosters is not None else _load(ROSTERS_FILE).get("bodies") or {}
    want = utils._body_key(meeting_type or "")
    if not want:
        return None
    for bname, cfg in r.items():
        if utils._body_key(bname) != want:
            continue
        for m in (cfg.get("members") or []):
            if m.get("name") != name:
                continue
            roles = [x for x in (m.get("roles") or [])
                     if x.lower() not in BOARD_SKIP]
            return roles[0] if roles else None
    return None


def staff_title(name, date, staff=None):
    """An appointed post, if we observed them holding it at or before `date`.

    THE BOUNDS ARE OBSERVATIONS, NOT TERMS. first_seen is the earliest meeting
    or scrape that showed the post, so it is an upper bound on when the post
    began, never the start date itself. Printing a post for a meeting EARLIER
    than anything we observed would be asserting a start we do not know, so
    that is refused; a meeting after last_seen is fine unless they have since
    left the city's pages.
    """
    s = staff if staff is not None else _load(STAFF_FILE).get("people") or {}
    rec = s.get(name)
    if not rec:
        return None
    first, left = rec.get("first_seen"), rec.get("left_site")
    if first and DATE.match(date or "") and date < first:
        return None
    if left and DATE.match(date or "") and date > left:
        return None
    t = (rec.get("title") or "").strip()
    return t or None


def title_for(name, meeting_type, date, councilors=None, rosters=None,
              staff=None):
    """The role to print before a name, or None."""
    if not is_full_name(name):
        return None
    date = (date or "")[:10]
    mt = meeting_type or ""

    role = board_title(name, mt, rosters)
    if role:
        return role if len(role) <= MAX_TITLE else None

    year = date[:4]
    if YEAR.match(year):
        spoken, body = elected_title(name, year, councilors)
        if spoken:
            if body == "City":
                return spoken                   # the mayor is the mayor anywhere
            here = ("CC" if mt.startswith("CC")
                    else "MPS" if mt.startswith(("MPS", "SC", "MSC")) else "")
            out = spoken if here == body else "%s %s" % (body, spoken)
            return out if len(out) <= MAX_TITLE else None

    t = staff_title(name, date, staff)
    if t and len(t) <= MAX_TITLE:
        return t
    return None


def label(name, meeting_type, date, **kw):
    """"Chief of Staff Nina Nazarian", or just the name."""
    t = title_for(name, meeting_type, date, **kw)
    return "%s %s" % (t, name) if t else name


def known_roles(councilors=None, rosters=None, staff=None):
    """Every role string this module can print. Used to undo a printed role."""
    out = set()
    for _, spoken, body in ELECTED:
        out.add(spoken)
        out.add("CC " + spoken)
        out.add("MPS " + spoken)
    r = rosters if rosters is not None else _load(ROSTERS_FILE).get("bodies") or {}
    for cfg in r.values():
        for m in (cfg.get("members") or []):
            for role in (m.get("roles") or []):
                if role.lower() not in BOARD_SKIP:
                    out.add(role)
    s = staff if staff is not None else _load(STAFF_FILE).get("people") or {}
    for rec in s.values():
        if rec.get("title"):
            out.add(rec["title"])
        for h in (rec.get("history") or []):
            if h.get("title"):
                out.add(h["title"])
    return out


def strip_role(label, known, roles=None):
    """Undo a printed role: "Councilor Anna Callahan" -> "Anna Callahan".

    AN INDEPENDENT GUARD, not a substitute for the client doing this. The
    correction form sends a line's whole text, label included, and that text
    REPLACES the paragraph in the .srt -- so a reader whose browser has a
    cached copy of the old transcript-player.js can submit a label with the
    role still in it, and nothing on the page can stop that. Written back
    unchecked it becomes a speaker named "Councilor Anna Callahan" in
    speaker_ids, and from there in the stats, the supercuts and every closed
    candidate set built from them.

    Only strips when the PREFIX is a role we actually print AND the remainder
    is a name this video already knows, so an unfamiliar name is never
    truncated into a familiar one.
    """
    lab = (label or "").strip()
    if not lab or lab in known:
        return lab
    roles = roles if roles is not None else known_roles()
    parts = lab.split()
    for i in range(1, len(parts)):
        if " ".join(parts[:i]) in roles and " ".join(parts[i:]) in known:
            return " ".join(parts[i:])
    return lab


_memo = {}


def label_cached(name, meeting_type, date):
    """label() memoised on (name, body, date).

    finish_speaker runs once per TURN -- 27,351 speaker/meeting pairs across
    the corpus but millions of turns -- and board_title walks the roster of
    every body looking for a key match, so resolving per turn is wasted work
    on a sweep that already takes hours.
    """
    key = (name, meeting_type, (date or "")[:10])
    if key not in _memo:
        _memo[key] = label(*key)
    return _memo[key]


def self_test():
    fails = []

    def ck(lbl, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (lbl, got, want))

    C = {"Zac Bears": {"2024": {"position": ["city_council_president",
                                             "city_council"]},
                       "2015": {"position": ["city_council"]}},
         "Breanna Lungo-Koehn": {"2026": {"position": ["mayor"]},
                                 "2015": {"position": ["city_council_vice",
                                                       "city_council"]}}}
    R = {"Historical Commission": {"members": [
            {"name": "Eleni Glekas", "roles": ["Chair", "Full Member"]},
            {"name": "John Anderson", "roles": ["Full Member"]}]}}
    S = {"Nina Nazarian": {"title": "Chief of Staff", "first_seen": "2022-01-04",
                           "last_seen": "2026-10-03"},
         "Laurel Siegel": {"title": "City Clerk", "first_seen": "2024-01-01",
                           "last_seen": "2026-10-03"},
         "Owen Wartella": {"title": "City Engineer", "first_seen": "2022-05-04",
                           "last_seen": "2025-01-01",
                           "left_site": "2025-06-01"}}
    kw = dict(councilors=C, rosters=R, staff=S)

    # most specific office wins
    ck("president not councilor",
       title_for("Zac Bears", "CC City Council", "2024-03-01", **kw), "President")
    # ... and the same person earlier is only a councilor
    ck("same man in 2015",
       title_for("Zac Bears", "CC City Council", "2015-03-01", **kw), "Councilor")
    # body-qualified away from home
    ck("qualified at another body",
       title_for("Zac Bears", "MPS School Committee", "2024-03-01", **kw),
       "CC President")
    # the mayor is the mayor anywhere
    ck("mayor unqualified at school committee",
       title_for("Breanna Lungo-Koehn", "MPS School Committee", "2026-03-01", **kw),
       "Mayor")
    # A TITLE IS A FACT AT A TIME: she is not Mayor in 2015
    ck("not mayor in 2015",
       title_for("Breanna Lungo-Koehn", "CC City Council", "2015-06-09", **kw),
       "Vice President")
    # a role on the body that is meeting
    ck("chair of this body",
       title_for("Eleni Glekas", "CC Historical Commission", "2026-01-01", **kw),
       "Chair")
    # plain membership says nothing
    ck("full member is not a role",
       title_for("John Anderson", "CC Historical Commission", "2026-01-01", **kw),
       None)
    # appointed staff
    ck("staff post", title_for("Nina Nazarian", "CC City Council",
                               "2026-03-01", **kw), "Chief of Staff")
    # never assert a post before the earliest date we observed it
    ck("no post before first_seen",
       title_for("Nina Nazarian", "CC City Council", "2019-03-01", **kw), None)
    # ... nor after they left the city's pages
    ck("no post after left_site",
       title_for("Owen Wartella", "CC City Council", "2026-03-01", **kw), None)
    ck("post while still listed",
       title_for("Owen Wartella", "CC City Council", "2024-03-01", **kw),
       "City Engineer")

    # THE SAFETY RULE: a label that is not a full name gets no role.
    ck("surname alone", title_for("Nazarian", "CC City Council",
                                  "2026-03-01", **kw), None)
    ck("the literal label Clerk", title_for("Clerk", "CC City Council",
                                            "2026-03-01", **kw), None)
    ck("a diarization id", title_for("SPEAKER_07", "CC City Council",
                                     "2026-03-01", **kw), None)
    ck("unidentified", title_for("Unidentified", "CC City Council",
                                 "2026-03-01", **kw), None)
    ck("is_full_name rejects one word", is_full_name("Rodriguez"), False)
    ck("is_full_name accepts two", is_full_name("Darsy Rodriguez"), True)

    # no date, no elected or staff claim
    ck("undated meeting", title_for("Zac Bears", "CC City Council", "", **kw),
       None)
    # the rendered label
    ck("label with a role", label("Nina Nazarian", "CC City Council",
                                  "2026-03-01", **kw),
       "Chief of Staff Nina Nazarian")
    ck("label without one", label("Some Resident", "CC City Council",
                                  "2026-03-01", **kw), "Some Resident")

    # --- undoing a printed role on the way back in ---------------------------
    roles = known_roles(rosters=R, staff=S)
    known = {"Anna Callahan", "Nina Nazarian", "Zac Bears", "Marie Izzo",
             "SPEAKER_04", "Eleni Glekas"}
    ck("elected role stripped",
       strip_role("Councilor Anna Callahan", known, roles), "Anna Callahan")
    ck("staff role stripped",
       strip_role("Chief of Staff Nina Nazarian", known, roles), "Nina Nazarian")
    ck("body-qualified role stripped",
       strip_role("CC President Zac Bears", known, roles), "Zac Bears")
    ck("board role stripped",
       strip_role("Chair Eleni Glekas", known, roles), "Eleni Glekas")
    ck("a plain known name is untouched",
       strip_role("Marie Izzo", known, roles), "Marie Izzo")
    ck("a diarization id is untouched",
       strip_role("SPEAKER_04", known, roles), "SPEAKER_04")
    # an unknown name must never be truncated into a known one
    ck("unknown name kept whole",
       strip_role("Some Other Person", known, roles), "Some Other Person")
    ck("role-looking prefix but unknown remainder",
       strip_role("Councilor Nobody Here", known, roles), "Councilor Nobody Here")

    for f in fails:
        print("  FAIL %s" % f)
    print("titles self-test: %d checks, %d failed" % (28, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(self_test())
