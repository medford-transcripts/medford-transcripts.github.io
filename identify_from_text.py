"""Identify speakers from what the transcript SAYS, not from how they sound.

WHY. Within one meeting the diarizer already separates confirmed speakers at
98-100% purity, so the corpus-wide label contamination came from cross-meeting
embedding matching, not diarization. And two failures no diarizer can fix are
fixable here: a 0.3-second "Present." carries almost no speaker information, and
492 of the 1,229 named speakers in this corpus appear in exactly ONE meeting, so
they have no cross-meeting voice match by construction. Their own words are the
only route to a name. See plan.txt 12.12 for the measurements behind all of this.

THE ONE RULE THAT MAKES THIS WORK: match against a CLOSED candidate set. Open
vocabulary name extraction from ASR text does not work -- measured at 95.7%
disagreement, inventing 29,342 "distinct speakers" in a city whose meetings have
1,229 named speakers in total. Accuracy as a function of candidate-set size, on
2,260 ground-truth cases:

        2 candidates   81.1% correct   0.0% wrong
       30 candidates   80.9% correct   1.2% wrong
    1,229 candidates   64.8% correct  29.6% wrong

Correctness barely moves; the error rate explodes. Keep the set small.

AND EDIT DISTANCE BEATS PHONETICS, which was a surprise. The mutilation is
TRUNCATION, not sound-alike substitution ("Jocelyn Mc" for Jocelyn McCarthy,
"Mullay" for Mullane), and cutting a surname short changes its consonant
skeleton, so soundex breaks exactly where it is needed: "Mc" codes M200 against
McCarthy's M263. partial_ratio scores that pair at 100. Soundex is kept only as
a tie-breaker.

    python identify_from_text.py --self-test   # pattern assertions, no corpus
    python identify_from_text.py --evaluate    # score against known labels
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import sys

from rapidfuzz import fuzz, process

import utils
import speaker_provenance as SP

# ---------------------------------------------------------------------------
# patterns
#
# EVERY PATTERN IS UNIT-TESTED IN self_test() AND THAT GATE RUNS BEFORE ANY
# CORPUS PASS. Four of five measurement attempts on 2026-09-29 failed silently
# and looked credible: a per-line search that missed introductions spanning
# blocks, a required trigger phrase that missed the dominant bare form, an
# open-vocabulary match that was 95.7% wrong, and a literal BACKSPACE byte
# (0x08) written into a regex by a mangled escape -- invisible to grep, an
# editor and a diff, found only with `cat -A`, after three runs reported
# honest-looking zeros. Assertions on literal strings catch all of that in
# under a second.

# Continuation words allow INTERNAL CAPITALS, which the first draft did not:
# [a-z'\-] cannot match the "V" after the hyphen, so "Marice Edouard-Vincent"
# truncated to "Marice Edouard-" -- the same truncation this module exists to
# repair, introduced by its own pattern. Also needed for McCarthy and O'Brien.
# The FIRST word stays simple; loosening it invites acronyms and sentence starts.
NAME = r"([A-Z][a-z]+(?:\s+[A-Z][A-Za-z'\-]+){1,2})"

# The trigger must be case-insensitive (an introduction starts a sentence) while
# the NAME must not (re.I on the whole pattern lets NAME match ordinary
# lowercase words, which is how the open-vocabulary attempt invented thousands
# of speakers). Scoped inline flag does exactly that.
SELF_INTRO = re.compile(r"(?i:my name is|my name's|i'm|i am|this is)" + r"\s+" + NAME)

# A name on a line by itself, or with an honorific -- the roll call and the
# chair calling on someone.
NAME_ONLY = re.compile(r"^(?:And\s+)?" + NAME + r"\s*[.?,]?$")

# A BARE SURNAME IS ONLY SAFE BEHIND AN HONORIFIC. NAME requires two or more
# words on purpose: allowing one would make NAME_ONLY match any capitalised word
# alone on a line ("Yes.", "Okay."). But "Councilor Caraviello" is the normal
# form of a call-on, so the honorific does the disambiguating and one word is
# fine here. Caught by self_test() -- HONORIFIC originally reused NAME and
# therefore never matched the commonest phrasing in the corpus.
SURNAME = r"([A-Z][a-z]+(?:\s+[A-Z][A-Za-z'\-]+){0,2})"
HONORIFIC = re.compile(r"^(?:councilor|councillor|member|mr\.?|mrs\.?|ms\.?|dr\.?|chair|"
                       r"president|superintendent|director|chief)\s+" + SURNAME +
                       r"\s*[?:.]?$", re.I)
ASSENT = re.compile(r"^(here|yes|present|aye|no|i'm here|yep|absent)\b", re.I)

SPK_LINE = re.compile(r"^\[([^\]]+)\]:\s*(.*)$")

# ---------------------------------------------------------------------------
# address cue, and the private parcel directory it indexes into
#
# A member of the public states a name AND usually an address, and the address is
# the better index: a house number plus a street resolves to one or two people
# (measured 1.30 candidates per building, 98% at two or fewer), where a name
# against the corpus resolves to noise (29.6% wrong at 1,229 candidates).
# Spoken street names need the same fuzzy matching as surnames -- "Playstead",
# "Fellsway", "Capen" -- so they are matched against the 660 real Medford street
# names rather than parsed open-vocabulary.

STREET_TYPE = (r"street|st|road|rd|avenue|ave|lane|ln|drive|dr|place|pl|terrace|ter|"
               r"way|circle|cir|court|ct|park|hill|square|sq|boulevard|blvd|row|path")
ADDRESS = re.compile(r"\b(\d{1,4})\s+([A-Z][A-Za-z'\-]*(?:\s+[A-Z][A-Za-z'\-]*){0,3}"
                     r"\s+(?:" + STREET_TYPE + r"))\b", re.I)

# The parcel keys are the assessor's abbreviations ("BRADLEY RD"); speech is
# "Bradley Road". Canonicalising both sides first means the fuzzy match is doing
# real work on the NAME rather than burning its budget on the suffix.
_ABBREV = {"STREET": "ST", "ROAD": "RD", "AVENUE": "AVE", "LANE": "LN",
           "DRIVE": "DR", "PLACE": "PL", "TERRACE": "TER", "CIRCLE": "CIR",
           "COURT": "CT", "SQUARE": "SQ", "BOULEVARD": "BLVD", "PARKWAY": "PKWY"}
PARCELS_FILE = "street_list_parcels.json"


def canonical_street(s):
    out = re.sub(r"[^A-Za-z'\- ]", " ", (s or "").upper())
    out = re.sub(r"\s+", " ", out).strip()
    parts = out.split()
    if parts and parts[-1] in _ABBREV:
        parts[-1] = _ABBREV[parts[-1]]
    return " ".join(parts)


class Parcels(object):
    """The private address -> owner-name directory. Absent is a valid state.

    NEVER a source of names nobody gave: it only resolves the spelling of a name
    a speaker stated aloud on the public record. Owners, not residents, so it
    misses the ~40% of Medford that rents -- see build_parcel_directory.py.
    """

    def __init__(self, path=PARCELS_FILE):
        self.streets, self.by_building, self.loaded = [], {}, False
        try:
            d = json.load(io.open(path, encoding="utf-8"))
        except Exception:
            return
        self.streets = [canonical_street(s) for s in d.get("streets", [])]
        self.by_building = {canonical_street_key(k): v
                            for k, v in (d.get("by_building") or {}).items()}
        self.loaded = bool(self.by_building)

    def resolve_street(self, spoken):
        """Spoken street -> a real Medford street name, or None."""
        c = canonical_street(spoken)
        if not c or not self.streets:
            return None
        if c in self.streets:
            return c
        r = process.extractOne(c, self.streets, scorer=fuzz.ratio, score_cutoff=85)
        return r[0] if r else None

    def candidates(self, number, spoken_street):
        """Names recorded at that building. [] when unknown."""
        st = self.resolve_street(spoken_street)
        if not st:
            return []
        return list(self.by_building.get("%s %s" % (number, st)) or [])


def canonical_street_key(key):
    """'38 BRADLEY RD' -> '38 BRADLEY RD' with the street half canonicalised."""
    m = re.match(r"^\s*(\d+[A-Za-z]?)\s+(.*)$", key or "")
    if not m:
        return canonical_street(key)
    return "%s %s" % (m.group(1), canonical_street(m.group(2)))

SOUNDEX_MAP = {}
for _chars, _code in (("BFPV", "1"), ("CGJKQSXZ", "2"), ("DT", "3"),
                      ("L", "4"), ("MN", "5"), ("R", "6")):
    for _c in _chars:
        SOUNDEX_MAP[_c] = _code


def soundex(word):
    w = re.sub(r"[^A-Za-z]", "", word or "").upper()
    if not w:
        return ""
    out, last = w[0], SOUNDEX_MAP.get(w[0], "")
    for ch in w[1:]:
        code = SOUNDEX_MAP.get(ch, "")
        if code and code != last:
            out += code
        if ch not in "HW":
            last = code
    return (out + "000")[:4]


# ---------------------------------------------------------------------------
# confidence tiers, mirroring the provenance scheme already in the repo
#
# Measured wrong-answer rates on 2,260 ground-truth cases at a realistic
# candidate-set size. A cue-derived name must OUTRANK an embedding match, which
# is the ordering whose absence let one spurious voice match spread to 800
# clusters.
TIER_EXACT = ("transcript_context", 100)        # exact, closed set
TIER_FUZZY = ("transcript_context_fuzzy", 80)   # 2.9% wrong, overwritable


def is_named(value):
    s = str(value or "")
    return bool(s) and " " in s and not s.startswith("SPEAKER_") \
        and "_SPEAKER_" not in s and s != "Unidentified"


def turns(srt_text):
    """[(speaker_key, [line, ...])] with consecutive blocks from one speaker joined.

    JOINING MATTERS: an introduction is split across SRT blocks ("My name is
    Jane Smith." / "I live at 12 Elm Street."), so a per-line search found
    name-and-address together 42 times across 2,300 meetings instead of 364.
    """
    seq = []
    for block in re.split(r"\n\s*\n", srt_text):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        m = SPK_LINE.match(lines[-1])
        if m:
            seq.append((m.group(1), m.group(2).strip()))
    out = []
    for spk, text in seq:
        if out and out[-1][0] == spk:
            out[-1][1].append(text)
        else:
            out.append((spk, [text]))
    return out, seq


def cues_in(srt_text):
    """Yield (speaker_key, stated_name, cue, address_or_None) per identity cue."""
    turn_list, seq = turns(srt_text)

    # 1. self-introduction, in the OPENING of a turn only. People introduce
    #    themselves when they start speaking; searching the whole turn matches
    #    them naming somebody else later.
    #
    #    The address is looked for over a WIDER window than the name: public
    #    comment runs "Good evening, my name is Jane Smith." / "I live at 12 Elm
    #    Street." across several SRT blocks, so a two-block window found name and
    #    address together only 364 times where a wider one finds far more.
    for spk, parts in turn_list:
        m = SELF_INTRO.search(" ".join(parts[:2]))
        if not m:
            continue
        addr = ADDRESS.search(" ".join(parts[:8]))
        if addr:
            yield spk, m.group(1).strip(), "self_introduction+address", \
                (addr.group(1), addr.group(2))
        else:
            yield spk, m.group(1).strip(), "self_introduction", None

    # 2. a name called out, then a different speaker answers. This is the roll
    #    call and the chair calling on a member.
    for i, (spk, text) in enumerate(seq):
        m = NAME_ONLY.match(text) or HONORIFIC.match(text)
        if not m:
            continue
        for spk2, text2 in seq[i + 1:i + 2]:
            if spk2 == spk:
                continue
            cue = "roll_call" if ASSENT.match(text2) else "called_on"
            yield spk2, m.group(1).strip(), cue, None


def match(stated, candidates):
    """(name, tier, score, method) or None. Closed set only -- never open."""
    if not stated or not candidates:
        return None
    for c in candidates:
        if c.lower() == stated.lower():
            return c, TIER_EXACT[0], 100, "exact"
    r = process.extractOne(stated, candidates, scorer=fuzz.partial_ratio,
                           score_cutoff=TIER_FUZZY[1])
    if r:
        return r[0], TIER_FUZZY[0], int(r[1]), "partial_ratio"
    # last resort: phonetic surname, and only when it is UNAMBIGUOUS. Soundex
    # alone was 6.9% wrong against 2.9% for partial_ratio, so it never overrides.
    key = soundex(stated.split()[-1])
    hits = [c for c in candidates if soundex(c.split()[-1]) == key]
    if len(hits) == 1:
        return hits[0], TIER_FUZZY[0], 0, "soundex"
    return None


def self_test():
    """Assertions on literal strings. Runs before any corpus pass."""
    fails, ran = [], []

    def check(label, got, want):
        ran.append(label)
        if got != want:
            fails.append("%s: got %r want %r" % (label, got, want))

    # self-introduction: trigger is mid-turn, not at position zero
    check("intro after thanks",
          (SELF_INTRO.search("Thank you, Mr. President. My name is Jane Smith.") or [None])
          and SELF_INTRO.search("Thank you, Mr. President. My name is Jane Smith.").group(1),
          "Jane Smith")
    check("intro lowercase trigger",
          SELF_INTRO.search("yes hi, my name is Robert Van Dyke").group(1), "Robert Van Dyke")
    check("intro I am",
          SELF_INTRO.search("I am Marice Edouard-Vincent, superintendent.").group(1),
          "Marice Edouard-Vincent")
    # must NOT fire on ordinary speech
    check("no intro in ordinary speech",
          SELF_INTRO.search("I am very concerned about the 40 Mystic Avenue project"), None)

    # roll call / called on
    check("name only", NAME_ONLY.match("Michael Marks.").group(1), "Michael Marks")
    check("honorific", HONORIFIC.match("Councilor Caraviello?").group(1), "Caraviello")
    check("not a name line", NAME_ONLY.match("I support the motion."), None)
    check("assent", bool(ASSENT.match("Present.")), True)

    # soundex: wins the textbook case, loses on truncation -- documented, not a bug
    check("soundex Smyth/Smith", soundex("Smyth") == soundex("Smith"), True)
    check("soundex truncation fails", soundex("Mc") == soundex("McCarthy"), False)

    # closed-set matching
    cands = ["Jocelyn McCarthy", "Michael Marks", "Zac Bears"]
    check("exact wins", match("Michael Marks", cands)[0], "Michael Marks")
    check("truncation via partial", match("Jocelyn Mc", cands)[0], "Jocelyn McCarthy")
    check("garbled declines", match("Yutori Arashi", cands), None)
    check("empty declines", match("", cands), None)

    # address extraction, as spoken
    m = ADDRESS.search("my name is Jane Smith and I live at 38 Bradley Road")
    check("address number", m and m.group(1), "38")
    check("address street", m and m.group(2), "Bradley Road")
    m2 = ADDRESS.search("I'm at 12 Playstead Rd, Medford")
    check("abbreviated street", m2 and m2.group(2), "Playstead Rd")
    check("no address in plain speech",
          ADDRESS.search("I have lived here for 30 years"), None)

    # canonicalisation must make the assessor's form and the spoken form agree
    check("canon road", canonical_street("Bradley Road"), "BRADLEY RD")
    check("canon already-abbrev", canonical_street("BRADLEY RD"), "BRADLEY RD")
    check("canon avenue", canonical_street("Hicks Avenue"), "HICKS AVE")
    check("canon key", canonical_street_key("38 Bradley Road"), "38 BRADLEY RD")

    # THE BACKSPACE GUARD: a control character in a pattern is invisible and
    # silently matches nothing. Check the patterns are printable.
    for nm, pat in (("SELF_INTRO", SELF_INTRO), ("NAME_ONLY", NAME_ONLY),
                    ("HONORIFIC", HONORIFIC), ("ASSENT", ASSENT),
                    ("ADDRESS", ADDRESS)):
        bad = [c for c in pat.pattern if ord(c) < 32]
        if bad:
            fails.append("%s contains control character(s) %r" % (nm, bad))

    for f in fails:
        print("  FAIL %s" % f)
    # A SHOW TITLE CARRIES A PERSON OR A SUBJECT, and the first version could
    # not tell them apart: it wrote Debt Exclusion, Charter Ballot Question,
    # Trove Green Provisions, Abundant Housing Massachusetts and Beyond Podcast
    # Crossover into the corpus as speakers. These hold with an EMPTY lexicon
    # too, since has_given_name rejects everything without one.
    for subject in ("Debt Exclusion", "Charter Ballot Question",
                    "Trove Green Provisions", "Abundant Housing Massachusetts",
                    "Beyond Podcast Crossover"):
        check("subject rejected: %s" % subject, title_guests(subject), [])

    # The keep side needs the parcel lexicon, which is private and may be
    # absent, so it is asserted only when the lexicon actually loaded.
    if given_names():
        check("guest kept",
              title_guests("Medford Happenings Episode 58 Laura O'Neill"),
              ["Laura O'Neill"])
        check("guest kept after a dash",
              title_guests("Medford Happenings - Chris Oates"), ["Chris Oates"])
        check("guest after 'with'",
              title_guests("Medford Happenings - Charter Study Committee with Ron Giovino"), ["Ron Giovino"])

    # The spoken given name survives; only the surname comes from the record.
    check("nickname preserved", spoken_form("Bob Smyth", "Robert Smith"),
          "Bob Smith")
    check("nickname preserved, one token", spoken_form("Cece", "Cecelia Colombo"),
          "Cece Colombo")
    check("Mc recased", fix_name_case("Christina Mcgorty"), "Christina McGorty")
    check("Mac left alone", fix_name_case("Denis Macdougall"), "Denis Macdougall")

    # COUNTED, not hardcoded: the previous "18 + 8" silently stopped
    # describing the suite the moment a check was added.
    print("self-test: %d checks, %d failed" % (len(ran), len(fails)))
    return 1 if fails else 0


# ---------------------------------------------------------------------------
# interview shows: the title names the guest
#
# Medford Happenings and Medford Bytes are two-or-three-handers, and the title
# carries the non-host participant: "Medford Happenings Episode 58 Laura
# O'Neill", "Chris Oates, Candidate for State Representative". That makes the
# closed set as small as it ever gets -- the host plus one guest -- which is the
# regime where matching measured 0.0% wrong.
#
# THE HOSTS WERE MEASURED, NOT ASSUMED: across the labelled corpus Medford Bytes
# names Danielle Balocca in 149 of 152 episodes and Chelli Keshavan in 100;
# Medford Happenings names John Petrella in 72 of 73.

SHOW_HOSTS = {
    "Medford Bytes": ["Danielle Balocca", "Chelli Keshavan"],
    "Medford Happenings": ["John Petrella"],
}

SHOW_PREFIX = re.compile(
    r"^\s*(?:medford\s+happenings|medford\s+bytes)\s*[-:–]*\s*"
    r"(?:episode\s*\d+\s*[-:–]*\s*)?", re.I)
TITLE_TRAILER = re.compile(
    r"\s*(?:,\s*)?\b(?:candidate\s+)?for\s+\w+.*$", re.I)
TITLE_HONORIFIC = re.compile(
    r"^(?:mayor|councillor|councilor|city\s+councilor|dr|rev|prof|chief|"
    r"president|superintendent)\.?\s+", re.I)
# Words that mark the title as a SUBJECT rather than a person. "Medford
# Composts!" and "Stand Up for Marginalized Communities" are episodes about
# something; naming a speaker from them would be inventing one.
TITLE_NOT_NAME = re.compile(
    r"\b(update|updates|campaign|committee|commission|board|council|community|"
    r"school|city|medford|palestine|composts?|communities|rights|stand|support|"
    r"meeting|forum|panel|special|episode|part|interview|show)\b", re.I)
TITLE_NAME_SHAPE = re.compile(r"^[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-\.]+){1,2}$")


_GIVEN_NAMES = None


def given_names():
    """Lower-cased given names seen in the parcel directory, loaded once.

    WHY THIS IS THE GATE ON TITLE GUESTS. A show title carries a person
    ("Medford Happenings Episode 58 Laura O'Neill") or a subject ("Debt
    Exclusion", "Charter Ballot Question", "Trove Green Provisions", "Abundant
    Housing Massachusetts"), and both are capitalised multi-word phrases. The
    first version could not tell them apart and wrote five organisations into
    the corpus as speakers -- 29% of what that cue produced.

    A WORD BLOCKLIST WOULD BE ENDLESS, and the obvious alternative is worse:
    requiring the guest to be a person already known elsewhere in the corpus
    rejects almost every real guest, because show guests are exactly the people
    who do NOT speak at council meetings. Measured with the show meetings held
    out, that test kept 1 of 11 real guests, and its near-misses were actively
    dangerous -- "Chris Oates" matched "Christy Stone" at 66 and "Nichole
    Mossalam" matched "Nicole Morell" at 68, so loosening it would have mapped
    real guests onto DIFFERENT REAL PEOPLE.

    What separates them is the FIRST TOKEN: given names are a closed vocabulary
    and the parcel directory is a large local sample of it (3,734 distinct).
    Measured on the 16 names the first version produced: 5 of 5 organisations
    rejected, 10 of 11 people kept. The prefix rule carries nicknames the
    records do not hold -- "Kat" is no one's legal name but prefixes Katherine.

    The lexicon is read, never published: only the boolean leaves this function.
    With no parcel directory the show cue writes NOTHING, which is the right
    default given it was 29% wrong without this gate.
    """
    global _GIVEN_NAMES
    if _GIVEN_NAMES is None:
        out = set()
        try:
            for names in Parcels().by_building.values():
                for n in names:
                    parts = str(n).split()
                    if parts:
                        out.add(parts[0].lower())
        except Exception:
            out = set()
        _GIVEN_NAMES = out
    return _GIVEN_NAMES


def has_given_name(name):
    """True when the first token is a plausible given name."""
    parts = (name or "").split()
    if not parts:
        return False
    first = parts[0].lower()
    pool = given_names()
    if not pool:
        return False
    if first in pool:
        return True
    return len(first) >= 3 and any(g.startswith(first) for g in pool)


def title_guests(title):
    """Non-host participants named in an interview show's title. [] if unsure."""
    t = re.sub(r"\s+", " ", title or "").strip()
    t = SHOW_PREFIX.sub("", t)
    m = re.search(r"\bwith\s+(.+)$", t, re.I)
    if m:                                  # "... Committee with Ron Giovino"
        t = m.group(1)
    t = re.sub(r"['’]s\b.*$", "", t)  # "Christine Barber's Campaign"
    t = TITLE_TRAILER.sub("", t)
    t = TITLE_HONORIFIC.sub("", t)
    out = []
    for part in re.split(r"\s*(?:,| and | & )\s*", t.strip(" -:–!,.")):
        part = part.strip(" -:–!,.")
        if (part and not TITLE_NOT_NAME.search(part) and TITLE_NAME_SHAPE.match(part)
                and has_given_name(part)):
            out.append(part)
    return out


def show_candidates(entry):
    """Host(s) + titled guest(s) for an interview show, else []."""
    hosts = SHOW_HOSTS.get(entry.get("meeting_type") or "")
    if hosts is None:
        return []
    return sorted(set(hosts) | set(title_guests(entry.get("title") or "")))


# "MCGORTY".title() is "Mcgorty". The assessors' records are upper case and
# build_parcel_directory title-cases them, which flattens the internal capital
# in every Mc- surname -- and these names get PUBLISHED, so a speaker's own
# name would be printed wrong on the public record of a meeting they spoke at.
#
# Mc is the only prefix fixed here because it is the only unambiguous one: no
# surname is Mc followed by a lower-case stem. Mac is deliberately left alone
# (Macy, Mack, Machado are not Mac + a name), as are the van/de/della
# particles, where the city's own roster is itself inconsistent
# ("Van der Kloot").
MC = re.compile(r"\bMc([a-z])")


def fix_name_case(name):
    return MC.sub(lambda m: "Mc" + m.group(1).upper(), name or "")


def spoken_form(stated, record_name):
    """The name to publish when a parcel record corroborated a spoken one.

    THE SPOKEN GIVEN NAME WINS. If someone introduces themselves as Bob, the
    transcript says Bob, even where the assessors' record says Robert -- the
    record is being consulted to fix the SPELLING OF A SURNAME that ASR
    mangled, not to replace what the person called themselves. Publishing the
    legal given name over the spoken one would be asserting something the
    speaker did not say, on the authority of a file that is not about names at
    all, and it would read as a correction of the person by their own
    government.

    So: given name(s) from what was said, surname from the record.
    """
    said = [w for w in re.split(r"\s+", (stated or "").strip()) if w]
    rec = [w for w in re.split(r"\s+", (record_name or "").strip()) if w]
    if not rec:
        return stated
    if not said:
        return record_name
    surname = fix_name_case(rec[-1])
    if len(said) > 1:
        return " ".join(said[:-1] + [surname])
    return " ".join([said[0], surname])


def show_inference(ids, entry):
    """{speaker_key: guest} for an interview show, by elimination.

    NOT A TRANSCRIPT CUE. The guest of Medford Happenings is rarely made to say
    their own name -- the host introduces them, and "the chair names somebody,
    the next voice answers" is the called_on cue that measured 61.4% and is not
    written. What identifies them is the SHAPE of the show: two or three
    participants, the host already known in 72 of 73 labelled episodes, and the
    title naming everyone else.

    So this is elimination, and it is only sound when the elimination is
    complete. It fires when the unnamed clusters and the titled guests are the
    same count AND that count is 1 -- one empty chair, one name for it. Two
    unnamed clusters and two guests would leave which-is-which unresolved, and
    guessing would be the cluster-level roll_call error (32.7% wrong) wearing a
    different hat.

    It also requires a host to be ALREADY NAMED in the meeting. Without that the
    unnamed cluster could be the host rather than the guest, and the show would
    be handing its guest's name to its own presenter.
    """
    hosts = SHOW_HOSTS.get(entry.get("meeting_type") or "")
    if not hosts:
        return {}
    guests = title_guests(entry.get("title") or "")
    if len(guests) != 1:
        return {}

    named = {str(v) for v in ids.values() if is_named(v)}
    if not any(h in named for h in hosts):
        return {}                      # no anchor: the empty chair may be the host
    if guests[0] in named or any(
            fuzz.ratio(guests[0].lower(), n.lower()) >= 80 or
            fuzz.partial_ratio(guests[0].lower(), n.lower()) >= 90
            for n in named):
        # Already identified, possibly under a different spelling of the
        # same name. Treating that as a vacancy would hand this guest's
        # name to whoever else happens to be unnamed.
        return {}

    open_keys = [k for k, v in ids.items() if not is_named(v)]
    if len(open_keys) != 1:
        return {}
    return {open_keys[0]: guests[0]}


def candidates_for(meeting_dir, ids, roster):
    """The closed set: names already known in this meeting, plus the roster.

    Deliberately small. Once the registry of 12.3 exists this becomes "people
    whose term covers this meeting's date", which is smaller still and is the
    single biggest lever on the error rate.
    """
    here = {str(v) for v in ids.values() if is_named(v)}
    return sorted(here | set(roster))


def evaluate(limit=0):
    """Score cues against clusters a human already named -- free ground truth."""
    vd = utils.get_video_data()
    roster = []
    try:
        roster = [str(n) for n in json.load(io.open("councilors.json", encoding="utf-8"))]
    except Exception:
        pass

    parcels = Parcels()
    print("parcel directory: %s (%s buildings, %s streets)"
          % ("loaded" if parcels.loaded else "ABSENT -- public speakers unresolvable",
             format(len(parcels.by_building), ","), format(len(parcels.streets), ",")))
    print()
    per_cue = collections.defaultdict(collections.Counter)
    n_meetings = 0
    for p in sorted(glob.glob("*/20??-??-??_*.srt")):
        d = os.path.dirname(p)
        yt = d.split("_", 1)[1]
        e = vd.get(yt) or {}
        if e.get("skip"):
            continue
        try:
            ids = json.load(io.open(os.path.join(d, "speaker_ids.json"), encoding="utf-8"))
            txt = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        n_meetings += 1
        cands = candidates_for(d, ids, roster)
        for spk, stated, cue, addr in cues_in(txt):
            truth = str(ids.get(spk) or "")
            # THE ADDRESS LOOKUP IS THE POINT: it supplies a candidate set for
            # someone in no roster, which is the case the officials-only set
            # could never serve. Parcel names are tried FIRST because a
            # household of one or two was measured at 0.0% wrong.
            local = list(cands)
            if addr and parcels.loaded:
                near = parcels.candidates(addr[0], addr[1])
                if near:
                    per_cue[cue]["address_resolved"] += 1
                    local = near + [c for c in cands if c not in near]
                else:
                    per_cue[cue]["address_unknown"] += 1
            if not is_named(truth):
                per_cue[cue]["unnamed_cluster"] += 1
                if addr and parcels.loaded and parcels.candidates(addr[0], addr[1]):
                    per_cue[cue]["unnamed_but_address_resolved"] += 1
                continue
            got = match(stated, local)
            if got is None:
                per_cue[cue]["declined"] += 1
            elif got[0].lower() == truth.lower():
                per_cue[cue]["correct"] += 1
                per_cue[cue]["correct_" + got[1]] += 1
            else:
                per_cue[cue]["wrong"] += 1
                per_cue[cue]["wrong_" + got[1]] += 1
        if limit and n_meetings >= limit:
            break

    print("meetings scanned: %s" % format(n_meetings, ","))
    print()
    print("%-18s %8s %8s %8s %9s %10s" % ("cue", "correct", "wrong", "declined",
                                          "accuracy", "unnamed"))
    for cue in sorted(per_cue):
        c = per_cue[cue]
        judged = c["correct"] + c["wrong"] + c["declined"]
        acc = 100.0 * c["correct"] / judged if judged else 0.0
        err = 100.0 * c["wrong"] / judged if judged else 0.0
        print("%-18s %8d %8d %8d %8.1f%% %10d" % (cue, c["correct"], c["wrong"],
                                                  c["declined"], acc, c["unnamed_cluster"]))
        print("%-18s   high-confidence tier: %d right / %d wrong"
              % ("", c["correct_backfill_high_confidence"], c["wrong_backfill_high_confidence"]))
        print("%-18s   fuzzy tier          : %d right / %d wrong  (err %.1f%%)"
              % ("", c["correct_embedding_match"], c["wrong_embedding_match"], err))
        if c["address_resolved"] or c["address_unknown"]:
            print("%-18s   address -> building : %d resolved / %d unknown"
                  % ("", c["address_resolved"], c["address_unknown"]))
        if c["unnamed_but_address_resolved"]:
            print("%-18s   UNNAMED clusters whose address resolves: %d"
                  % ("", c["unnamed_but_address_resolved"]))
    print()
    print("'unnamed' counts cues landing on clusters with NO name yet -- the")
    print("identifications this would ADD. Nothing is written by --evaluate.")
    return 0


def apply_to_meeting(meeting_dir, entry, apply=False, parcels=None):
    """Name unnamed clusters in one meeting from the words spoken in it.

    WHAT IT WILL NOT DO, which is most of the design:

      It never names a cluster that already has a name. Every existing value is
      left exactly as it is -- this only fills blanks and raw SPEAKER_nn keys.
      Nothing here can overwrite a human, an embedding match or a propagation.

      It never matches against an open vocabulary. A stated name is resolved
      only inside a closed set assembled for THIS meeting: the people already
      named in it, the city's roster for the body that met, and for an
      interview show the host plus the guest named in the title. Open-vocabulary
      extraction was measured at 95.7% wrong, inventing 29,342 speakers.

      It never writes a roll-call identity. Per CLUSTER, roll_call measured
      44.0% right with 32.7% of the fuzzy matches wrong -- the name called and
      the voice that answers are adjacent in the transcript but the cluster
      spans the whole meeting, so the cue identifies a TURN and not a speaker.
      Fixing that needs per-utterance labels, which speaker_ids.json cannot
      express today, so roll_call and called_on are collected and dropped here.

    Returns {speaker_key: (name, source, score, cue)} for what it would write.
    """
    ids = _read_ids(meeting_dir)
    if not ids:
        return {}
    srt = _read_srt(meeting_dir)
    if not srt:
        return {}

    roster = utils.body_roster(entry.get("meeting_type"))
    cands = sorted(set(candidates_for(meeting_dir, ids, roster))
                   | set(show_candidates(entry)))
    if len(cands) < 2:
        return {}

    open_keys = {k for k, v in ids.items() if not is_named(v)}
    if not open_keys:
        return {}

    # The parcel directory supplies candidates for someone in NO roster,
    # which is the case a roster can never serve. It stays private: it is
    # read here, never printed and never published -- what reaches the
    # transcript is the name the speaker said, with the surname spelled as
    # the assessors' record spells it. See spoken_form for the given name.
    if parcels is None:
        parcels = Parcels()
    prov = SP.load_provenance(meeting_dir)
    out = {}

    # Elimination on an interview show, which no spoken cue can supply:
    # the guest is named by the title, not by themselves.
    for spk, name in show_inference(ids, entry).items():
        if spk in open_keys and not SP.is_protected(prov, spk):
            out[spk] = (name, TIER_EXACT[0], 100, 'show_title/elimination')
    for spk, stated, cue, addr in cues_in(srt):
        if cue in ("roll_call", "called_on"):
            continue                      # per-turn cue, per-meeting store
        if spk not in open_keys or spk in out:
            continue
        if SP.is_protected(prov, spk):
            continue
        household = []
        if addr and parcels.loaded:
            household = parcels.candidates(addr[0], addr[1])
        hit = match(stated, sorted(set(cands) | set(household)))
        if not hit:
            continue
        name, tier, score, method = hit
        if name in household and name not in cands:
            name = spoken_form(stated, name)
        if method == "soundex":
            # 6.9% wrong against 2.9% for partial_ratio. It earns its place
            # as a last resort when a human is reading the output; it does
            # not earn the right to write a name nobody checks.
            continue
        if tier == TIER_FUZZY[0] and cue == "self_introduction":
            # The weakest pairing: a fuzzy match on a bare self-introduction,
            # with no address to corroborate it. 2.9% wrong on its own, and
            # unlike the exact tier it would be writing a name nobody said in
            # those words. Left for a human.
            continue
        out[spk] = (name, tier, score, "%s/%s" % (cue, method))

    if apply:
        for spk, (name, tier, score, how) in out.items():
            SP.record(meeting_dir, spk, name, tier, score=score,
                      from_="identify_from_text:%s" % how, provenance=prov)
            ids[spk] = name
        # record() with provenance= mutates IN MEMORY ONLY and leaves saving
        # to the caller (that is what propagate's collect-then-commit needs).
        # Without this line the names landed in speaker_ids.json while their
        # provenance still read embedding_match -- a value that keeps looking
        # authoritative after its basis is gone, which is the exact failure
        # speaker_provenance exists to prevent.
        SP.save_provenance(meeting_dir, prov)
        SP.atomic_write_json(SP.speaker_ids_path(meeting_dir), ids)
    return out


def _read_ids(meeting_dir):
    try:
        return json.load(io.open(os.path.join(meeting_dir, "speaker_ids.json"),
                                 encoding="utf-8"))
    except Exception:
        return {}


def _read_srt(meeting_dir):
    hits = glob.glob(os.path.join(meeting_dir, "20??-??-??_*.srt"))
    hits = [h for h in hits if not h.endswith(("_basic.srt", "_aligned.srt",
                                               ".srt.orig"))]
    if not hits:
        return ""
    try:
        return io.open(hits[0], encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def apply_all(apply=False, limit=0, quiet=False):
    """Run apply_to_meeting across the corpus. Returns the per-meeting counts."""
    vd = utils.get_video_data()
    total, meetings = 0, 0
    by_cue = collections.Counter()
    seen_dirs = set()
    for p in sorted(glob.glob("*/20??-??-??_*.srt")):
        d = os.path.dirname(p)
        # ONE VISIT PER MEETING: the glob also matches _basic.srt and
        # _aligned.srt, so every meeting was being processed three times.
        if d in seen_dirs:
            continue
        seen_dirs.add(d)
        yt = d.split("_", 1)[1]
        entry = vd.get(yt) or {}
        if entry.get("skip") or not entry:
            continue
        got = apply_to_meeting(d, entry, apply=apply)
        if not got:
            continue
        meetings += 1
        total += len(got)
        for _, (_, tier, _, how) in got.items():
            by_cue[how.split("/")[0] + " " + tier] += 1
        if not quiet:
            for spk, (name, tier, score, how) in sorted(got.items()):
                print("  %-34s %-14s %-24s %s" % (d[:34], spk, name[:24], how))
        if limit and meetings >= limit:
            break
    print()
    print("%s %d names across %d meetings"
          % ("WROTE" if apply else "would write", total, meetings))
    for k, n in by_cue.most_common():
        print("    %-46s %d" % (k, n))
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="write the high-confidence names")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what --apply would write")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rc = self_test()
    if rc:
        print("REFUSING to continue: patterns failed their own tests.")
        return rc
    if args.self_test and not args.evaluate:
        return 0
    if args.evaluate:
        return evaluate(args.limit)
    if args.apply or args.dry_run:
        return 0 if apply_all(apply=args.apply, limit=args.limit) >= 0 else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
