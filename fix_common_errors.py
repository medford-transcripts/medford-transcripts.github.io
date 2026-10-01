import glob
import shutil
import ipdb
import os
import re


# Contexts where a rule must NOT fire, because the word is genuinely the other
# thing. These are real ambiguities that no amount of boundary anchoring can
# settle -- a school guidance counselor is not a city Councilor.
# Patterns must be FIXED WIDTH -- Python lookbehind requires it, so "\s+" is
# not allowed here. A character class is fine.
RULE_EXCEPTIONS = {
    "counselor": [r"[Gg]uidance "],
    "Counselor": [r"[Gg]uidance "],
    "counsel":   [r"[Gg]uidance "],
    # "lemming" is an English word as well as a mishearing of Councilor Matt
    # Leming's name. One occurrence in the whole corpus is the animal --
    #   "a significant effort not to join the lemmings, not to, as they march
    #    off to the cliff and jump off"                        (2025-06-24)
    # -- against ~2,500 that are the man. It shipped to the live site as "join
    # the Lemings". Rather than weaken a rule that is right 2,500 times, the
    # one phrase that introduces the metaphor is excluded.
    # ALL FOUR KEYS need it, not just the plural ones. compile_rules gives the
    # SINGULAR rule an optional trailing "s" (so "counselors" pluralises for
    # free), which means "\blemming(s?)\b" matches "lemmings" too. Exempting
    # only "lemmings" let the plural rule be blocked and then the singular rule
    # matched the very same text and echoed the "s" back -- "Lemings" again.
    "lemmings": [r"join the "],
    "Lemmings": [r"join the "],
    "lemming":  [r"join the "],
    "Lemming":  [r"join the "],
}


# Rules that only became true on a date, keyed by the first date they hold.
#
# WHY THIS EXISTS. A title is not a fact about a name, it is a fact about a
# name AT A TIME. "Councilor Maloney" -> "Councilor Mullane" is right for 2026
# and wrong for every year before it: there was a real Councilor Maloney who
# served from 1976, and the 2023 and 2024 meetings that memorialise him say
# "Councilor Maloney served the city for over 25 years" and dedicate a meeting
# "in Councilor Maloney's memory". A blanket rule rewrites a dead councilor's
# memorial into a sitting one's name. "Councilor Layne" is the same shape, in
# a 2017 resolution offered with President Caraviello.
#
# The date is taken from the FILENAME, which carries the upload date, not the
# meeting date -- close enough here (the earliest affected 2026 meeting is well
# clear of the boundary) but worth knowing if a rule is ever added whose start
# date falls mid-January.
DATED_REPLACEMENTS = {
    # Liz Mullane was sworn in January 2026. Only the rules that assert she
    # holds the SEAT are gated; the bare-surname ones stay ungated, because she
    # existed before 2026 as a candidate and as a resident at public comment.
    "2026-01-01": {
        # Mullane again, from the roll-call inventory: 116 "Malauulu" and
        # 34 "Malay", both overwhelmingly 2026. "Malay" is also an ordinary
        # word, which is exactly why the title has to be part of the rule.
        "Councilor Malauulu" : "Councilor Mullane",
        "Councilor Malay" : "Councilor Mullane",
        "Council Malauulu" : "Councilor Mullane",
        "Liz Malone" : "Liz Mullane",
        "Council Malone" : "Councilor Mullane",
        "Councilor Malone" : "Councilor Mullane",
        "Councilor Maloney" : "Councilor Mullane",
        "Chair Maloney" : "Chair Mullane",
        "Councilor Millan" : "Councilor Mullane",
        "Councilor Mullen" : "Councilor Mullane",
        "Councilor Milley" : "Councilor Mullane",
        "Councilor Malate" : "Councilor Mullane",
        "Liz Malate" : "Liz Mullane",
        "Councilor Moline" : "Councilor Mullane",
        "Council Moline" : "Councilor Mullane",
        "Chair Moline" : "Chair Mullane",
        "chair Moline" : "Chair Mullane",
        "Councilman Layne" : "Councilor Mullane",
        "Councilor Layne" : "Councilor Mullane",
        "Councilor Mulling" : "Councilor Mullane",
        "Councilor Malaney" : "Councilor Mullane",
        "Councilor Mulaney" : "Councilor Mullane",
        "Councilor Mullan" : "Councilor Mullane",
        "Councilor Millay" : "Councilor Mullane",
        "Councilor Mulley" : "Councilor Mullane",
    },
    # Bears took the gavel in 2024 and Leming and Callahan were seated that
    # January, so these three assert offices that did not exist before then.
    # "President Pierce" is the single biggest unfixed mangling in the
    # corpus at 192 occurrences, and it appears ONLY in 2024-2026 -- which is
    # exactly Bears's presidency, so the gate is corroborated rather than
    # guessed. "Councilor Kelly" is Callahan: in every roll call that calls
    # Kelly, Callahan is absent and Kelly sits in her alphabetical slot
    # (owner). Bare "Kelly" stays untouched -- Kelly Catallo was a real 2021
    # candidate and residents named Kelly speak at public comment.
    "2024-01-01": {
        "President Pierce" : "President Bears",
        "president Pierce" : "President Bears",
        "Councilor Lennon" : "Councilor Leming",
        "Councilor Kelly" : "Councilor Callahan",
        "Council Kelly" : "Councilor Callahan",
    },
}


def compile_rules(replace_dict):
    """Compile the replacement table into anchored, plural-aware patterns.

    THREE things have to be true at once, and the original str.replace() only
    managed the second:

    1. WORD BOUNDARIES. Unanchored substring matching corrupted 935 of 2,273
       transcripts, mangling residents' surnames: Moxley -> Marksley,
       Maxwell -> Markswell, McKernan -> Lungo-Koehnan, Beasley -> Bearsley.

    2. PLURALS. The dict contains NO plural forms -- all 151 single-word rules
       relied on substring matching to pluralise for free, so naive anchoring
       silently stopped correcting "counselors" -> "Councilors". The pattern
       therefore carries an optional trailing "s" which is echoed into the
       replacement.

    3. CONTEXT. "guidance counselors" must stay counselors. Boundaries cannot
       express that, so genuine ambiguities get an explicit negative lookbehind
       from RULE_EXCEPTIONS.

    Boundaries are only added where a key actually begins or ends with a word
    character: several rules depend on surrounding whitespace (" Seng",
    "15 dash ") and a blanket \b would break them.
    """
    out = []
    for key, value in replace_dict.items():
        key = str(key)
        if not key:
            continue

        body = re.escape(key)
        pattern = body
        pluralised = False

        if key[-1].isalnum() or key[-1] == "_":
            # optional plural, echoed through to the replacement
            if key[-1].isalpha() and not key.endswith("s"):
                pattern = pattern + r"(s?)"
                pluralised = True
            pattern = pattern + r"\b"

        if key[0].isalnum() or key[0] == "_":
            pattern = r"\b" + pattern
            for ctx in RULE_EXCEPTIONS.get(key, []):
                pattern = r"(?<!" + ctx + r")" + pattern

        repl = value.replace("\\", "\\\\")
        if pluralised:
            repl = repl + r"\1"
        out.append((re.compile(pattern), repl))
    return out


def apply_rules(text, patterns):
    for rx, value in patterns:
        text = rx.sub(value, text)
    return text


def fix_common_errors(yt_id=None):

    replace_dict = {
        # SURNAME SPELLINGS, ungated: these fix how a name is SPELLED, not
        # which office someone holds, so they are true whenever the name
        # appears -- as a member, a candidate or a resident at public comment.
        # Same reasoning the Mullane block records for its bare-surname rules.
        #
        # MASTROBUONI IS SPELLED OUT IN OUR OWN CORPUS by the man himself:
        #   "Best way to reach me is MikeMastroboni.com, M-I-K-E, and then
        #    Mastroboni is M-A-S-T-R-O-B-U-O-N-I."
        # The correct spelling appears ZERO times in the transcripts; 318 say
        # "Mastroboni". councilors.json had it wrong too ("Mastrobouni") and is
        # corrected in the same commit. His website is one word, so the word
        # boundary leaves "MikeMastroboni.com" alone.
        "Mastroboni" : "Mastrobuoni",
        "Mastrobone" : "Mastrobuoni",
        "Mastrobonni" : "Mastrobuoni",
        "Mastrobrioni" : "Mastrobuoni",
        "Mastrobianni" : "Mastrobuoni",
        "Mastraboni" : "Mastrobuoni",
        "Mastromoni" : "Mastrobuoni",
        "Master Boney" : "Mastrobuoni",
        # NOT "Mastone" -> Mastrobuoni: it is a real surname, MUSTONE, which
        # ASR also mangles. Mea Quinn Mustone sat on the School Committee
        # 2015-2023 and is named 1,392 times correctly against 274 as
        # "Mastone", so the surname gets its own rule below rather than
        # being folded into a name it has nothing to do with.
        "Mastone" : "Mustone",
        "Mastones" : "Mustones",
        # Her given name is MEA, rendered "Mia" 130 times. Only the forms
        # carrying her middle name are corrected: "Mia Quinn Mustone" can
        # only be her. A bare "Mia Mustone" is left alone, because TEGAN
        # MUSTONE is a different person -- "our Medford High School
        # freshman, Tegan Mustone" -- and a family shares a surname.
        "Mia Quinn Mustone" : "Mea Quinn Mustone",
        "Mia Quinn Mastone" : "Mea Quinn Mustone",
        #
        # Lungo-Koehn, whose hyphenated name ASR splits into two words.
        "Long and Kern" : "Lungo-Koehn",
        "Lowell-Kern" : "Lungo-Koehn",
        # Scarpelli, a third variant alongside the existing ones.
        "Scott Felly" : "Scarpelli",
        "Scalpelli" : "Scarpelli",
        "Scapelli" : "Scarpelli",
        "Councillor" : "Councilor",
        "Counselor" : "Councilor",
        "counselor" : "Councilor", 
        "Membo" : "Member",
        "Mr " : "Mr. ",
        "Mrs " : "Mrs. ",

        "Memphis" : "Medford",
        "Medfitt" : "Medford",
        "Medfit" : "Medford",
        "Medfin" : "Medford",
        "Meffitt" : "Medford",
        "city of Method": "city of Medford",

        "Missituck" : "Missituk",
        "Misituk" : "Missituk",
        "Mistituck" : "Missituk",

        "Felsway":"Fellsway",

        "Car Park" : "Carr Park",

        "Innis Associates": "Innes Associates",
        "Innis associates": "Innes Associates",
        "Ennis Associates": "Innes Associates",
        "Ennis associates": "Innes Associates",

        "15 dash ": "15-",
        "16 dash ": "16-",
        "17 dash ": "17-",
        "18 dash ": "18-",
        "19 dash ": "19-",
        "20 dash ": "20-",
        "21 dash ": "21-",
        "22 dash ": "22-",
        "23 dash ": "23-",
        "24 dash ": "24-",
        "25 dash ": "25-",


        "Behrs" : "Bears",
        "Council bears" : "Councilor Bears",
        "Councilor Beers" : "Councilor Bears",
        "Councilor beers" : "Councilor Bears",
        "Councilor Piers" : "Councilor Bears",
        "Counsel Pierce" : "Councilor Bears",
        "Councilor Beas" : "Councilor Bears",
        "Councilor Baird" : "Councilor Bears",
        "Councilor Baez" : "Councilor Bears",
        "Councilor Bares" : "Councilor Bears",
        "Counsel Bears" : "Councilor Bears",
        "Council Beers" : "Councilor Bears",
        "Councilor Pierce" : "Councilor Bears",
        "Councilor Barrett" : "Councilor Bears",
        "president Ferris" : "President Bears",
        "President Barish" : "President Bears",
        "President Beers" : "President Bears",
        "President bears" : "President Bears",
        "President Behr" : "President Bears",
        "President Bares" : "President Bears",
        "President Bex" : "President Bears",
        "President Perrs" : "President Bears",
        "President Barrett" : "President Bears",
        "President Baird" : "President Bears",
        "President Burris" : "President Bears",
        "President Rivers" : "President Bears",
        "President Abiris" : "President Bears",
        "President Barris" : "President Bears",
        "President Baer" : "President Bears",
        "President Beres" : "President Bears",
        "President Farris" : "President Bears",
        "President Barras" : "President Bears",
        "President Barrows" : "President Bears",

        "Baldini":"Buldini",
        "Boldini":"Buldini",
        "Valdini":"Buldini",
        "Paige Buldini":"Page Buldini",

        "Brantley" : "Branley",
        "Brandley" : "Branley",

        "Councilor Kellyanne" : "Councilor Callahan",
        "Kallian" : "Callahan",

        "counsel Camuso": "Councilor Camuso",

        "Caviello" : "Caraviello",
        "Caravaglia" : "Caraviello",
        "Caviel" : "Caraviello",
        "Caviello" : "Caraviello",
        "Carabiello" : "Caraviello",
        "Karabiello" : "Caraviello",
        "Caravaglio" : "Caraviello",
        "Carvillo" : "Caraviello",
        "Caravello" : "Caraviello",
        "Caraballo" : "Caraviello",
        "Carviello" : "Caraviello",
        "Carvio" : "Caraviello",
        "Carvajal" : "Caraviello",
        "Carriello" : "Caraviello",
        "Carviela" : "Caraviello",
        "Cardiola" : "Caraviello",
        "Caravella" : "Caraviello",
        "Carriella" : "Caraviello",
        "Carpiollo" : "Caraviello",
        "Carriella" : "Caraviello",
        "Carbiello" : "Caraviello",
        "Carville" : "Caraviello",
        "Carrillo" : "Caraviello",
        "Carigano" : "Caraviello",
        "Carbielo" : "Caraviello",
        "Carriillo" : "Caraviello",
        "Caravaggio" : "Caraviello",
        "Carabino" : "Caraviello",
        "President Caribbean" : "President Caraviello",
        "Carribello" : "Caraviello",
        "Carabino" : "Caraviello",
        "Caravaggio" : "Caraviello",
        "Carbielo" : "Caraviello",
        "Carvello" : "Caraviello",
        "Caravagno" : "Caraviello",
        "Councilor Carvel" : "Councilor Caraviello",
        "Carvilla" : "Caraviello",
        "Carbiel" : "Caraviello",
        "Carviel" : "Caraviello",
        "Carvialho" : "Caraviello",
        "Cardiello" : "Caraviello",
        "Carrivello" : "Caraviello",
        "Cara V yellow" : "Caraviello",
        "Caravigliano" : "Caraviello",
        "carving yellow" : "Caraviello",
        "Cabrillo" : "Caraviello",
        "Gargielo" : "Caraviello",
        "Kerrio-Viejo" : "Caraviello",
        "Karviela" : "Caraviello",
        "Kerrio" : "Caraviello",
        "Karaviello" : "Caraviello",
        "Cabello" : "Caraviello",
        "Caviola": "Caraviello",
        "counsel Caraviello": "Councilor Caraviello",
        "Faviello" : "Caraviello",

        "Castaneda" : "Castagnetti",
        "Castanetti" : "Castagnetti",
        "Castanete" : "Castagnetti",

        "Cuneo" : "Cugno",
        "Kunio" : "Cugno",

        "De La Russo" : "Dello Russo",
        "DelaRusso" : "Dello Russo",
        "Dela Russo" : "Dello Russo",
        "Della Russo" : "Dello Russo",
        "Counsel Del Rosso" : "Councilor Dello Russo",
        "Del Rosso" : "Dello Russo",

        "Edward Vincent": "Edouard-Vincent",
        "Edward Vinson": "Edouard-Vincent",
        "Maurice Edouard-Vincent": "Marice Edouard-Vincent",

        "Falcone" : "Falco",
        "Felco" : "Falco",
        "Fevella" : "Falco",

        "Fibber Carrie" : "Fidler-Carey",
        "Fidler, Carrie" : "Fidler-Carey",
        "Fidler Carey" : "Fidler-Carey",
        "Fidler-Carrie" : "Fidler-Carey",

        "Gaston Fury" : "Gaston Fiore",

        "Galluzzi" : "Galusi",

        "Member Hayes" : "Member Hays",
        "member Hayes" : "member Hays",

        "Urtubis" : "Hurtubise",
        "Carter-Bees" : "Hurtubise",
        "Carter-Viz" : "Hurtubise",
        "Hurtabee" : "Hurtubise",
        "Urnaby" : "Hurtubise",
        "Urnaby" : "Hurtubise",
        "Hertoghez" : "Hurtubise",
        "Bernabez" : "Hurtubise",
        "Hertoghez" : "Hurtubise",
        "Herterby" : "Hurtubise",
        "Hutterby" : "Hurtubise",
        "Urdobez" : "Hurtubise",
        "Urneby" : "Hurtubise",
        "Hertoghese" : "Hurtubise",
        "Clerk Hernandez" : "Clerk Hurtubise",
        "Clerk Artemis" : "Clerk Hurtubise",
        "Clerk Curtis" : "Clerk Hurtubise",
        "Arnabis" : "Hurtubise",
        "Herderby" : "Hurtubise",
        "Kurtabeas" : "Hurtubise",
        "Harnaby" : "Hurtubise",
        "Hurnaby" : "Hurtubise",
        "Bernabease" : "Hurtubise",
        "Urdovich" : "Hurtubise",
        "Herterbeast" : "Hurtubise",
        "Hurnaby" : "Hurtubise",
        "Urtubez" : "Hurtubise",
        "Hurtabish" : "Hurtubise",
        "Herterbe" : "Hurtubise",
        "Kernanby" : "Hurtubise",

        "Antapa" : "Intoppa",
        "Antoppa" : "Intoppa",
        "Ntopa" : "Intoppa",
        "Ntopper" : "Intoppa",
        "Ntapa" : "Intoppa",

        "Councilor night" : "Councilor Knight",
        "Councilor Night" : "Councilor Knight",
        "Councilor Nye" : "Councilor Knight",
        "Council Light" : "Councilor Knight",
        "Council Night" : "Councilor Knight",
        "Counsel Knight" : "Councilor Knight",
        "Neidt" : "Knight",
        "Councilor Councilor Knight" : "Councilor Knight",
        "council a night": "Councilor Knight",

        "Kretz" : "Kreatz",
        "Kraetz" : "Kreatz",
        "Kratz" : "Kreatz",

        " Zaro" : " Lazzaro",
        "Lazaro" : "Lazzaro",
        "Lazarro" : "Lazzaro",
        "Lozaro" : "Lazzaro",
        "Lozano" : "Lazzaro",
        "Lozzaro" : "Lazzaro",
        "Lizaro" : "Lazzaro",
        "Lizarra": "Lazzaro",
        "Lazarro" : "Lazzaro",
        "Lazarus" : "Lazzaro",
        "Lozero" : "Lazzaro",
        "Lazzaroo" : "Lazzaro",
        "Lizardo" : "Lazzaro",
        "Councilor Lazar" : "Councilor Lazzaro",
        "Councilor Zahra" : "Councilor Lazzaro",
        "Councilor Zara" : "Councilor Lazzaro",
        "Council Lizard" : "Councilor Lazzaro",
        "Council Lazzaro" : "Councilor Lazzaro",

        # ------------------------------------------- Councilor Liz Mullane
        # Seated January 2026, so she post-dates every earlier pass over this
        # file and NOTHING here covered her. Measured over the 210 canonical
        # 2026 transcripts: 164 mentions spelled right against ~356 mangled --
        # about 68% wrong, the worst ratio of any sitting councilor.
        #
        # SPLIT IN TWO, because the risk is not uniform.
        #
        # First, spellings that are not words and not anyone else's name. A
        # bare rule is safe and catches every honorific at once ("Councilor",
        # "Chair", "Liz", "Councilors"), including the possessive: the trailing
        # \b that compile_rules adds sits happily before the apostrophe, so
        # "Malayne's" becomes "Mullane's".
        "Malayne" : "Mullane",
        "Millane" : "Mullane",
        "Mulane" : "Mullane",
        "Mullain" : "Mullane",
        "Mlayne" : "Mullane",
        "Mallain" : "Mullane",
        "Molayne" : "Mullane",
        "Malaine" : "Mullane",
        "Milane" : "Mullane",
        "Mulvane" : "Mullane",
        # From her CANDIDACY, not the seat: "I'd like to call Liz Mullay to the
        # podium", 2025-10-16 candidate forum. The 2026 rules above were mined
        # from 2026 transcripts, where "Councilor" primes the recogniser; the
        # pre-election recordings mishear her differently, and those are worth
        # catching -- it is the same person speaking before she held office.
        # Keyed on the first name because "Mullay" alone is a real surname.
        "Liz Mullay" : "Liz Mullane",

        # Second, spellings that ARE real surnames or real words, where a bare
        # rule would corrupt somebody. Those are keyed on the honorific AND
        # gated to 2026 onward -- see DATED_REPLACEMENTS at the top of this
        # file, and the Councilor Maloney memorial it exists to protect.
        #
        # "Malone" is the sharp case even so: PAUL MALONE is a real person with
        # 117 mentions in the 2026 files alone, so only the councilor-shaped
        # and first-name-shaped forms may be touched. "Lisa Malone" is left
        # alone -- one occurrence, and it is not clear it is her.
        #
        # NOT "Milne" at all: its single occurrence in the corpus is
        # "Andrew Milne", a real 2021 school committee candidate, and there is
        # no "Councilor Milne" anywhere. A rule would only ever be wrong.

        # ------------------------------------------------ Councilor Matt Leming
        # "lemming" IS AN ENGLISH WORD, and the bare rule that used to be here
        # rewrote it. Published, on the live site, from 2025-06-24:
        #     "a significant effort not to join the Lemings, not to, as they
        #      march off to the cliff and jump off"
        # The speaker said "lemmings". compile_rules adds an optional trailing
        # "s" and echoes it into the replacement, so the plural was carried
        # through and a sitting councilor's name was spliced into a metaphor.
        #
        # Measured over the .srt.orig snapshots: ~2,500 uses follow a title or
        # first name (Councilor 2067, Councillor 246, Matt 58, Chair 50,
        # Council 21) and 6 are the animal ("a lemming" x3, "the lemming" x2,
        # "the lemmings" x1). Anchoring keeps the 2,500 and protects the 6.
        #
        # THE RULE STAYS BARE, WITH ONE EXCEPTION. Anchoring it to titles was
        # tried and is worse: "this is about the lemming motion" and "I
        # completely heard lemming as Lazzaro" are the councilor with no title
        # attached, and anchored rules silently stop correcting them. Measured
        # across the .orig snapshots, exactly ONE occurrence is the animal --
        # the cliff metaphor above -- against ~2,500 that are the man. So the
        # bare rule is right, and the single counter-example is handled by a
        # negative lookbehind in RULE_EXCEPTIONS.
        #
        # THE TRAILING-S FORMS COME FIRST, because the singular rule's
        # optional-plural group echoes the "s" through and yields "Lemings".
        # They map to a bare "Leming": of the three, one is possessive
        # ("Councilor lemmings motion") and two are plain ("go back to
        # counselor lemmings", "what counselor lemmings mentioned"), so
        # dropping the "s" gets the NAME right in all three.
        "Lemmings" : "Leming",
        "lemmings" : "Leming",
        "Lemming" : "Leming",
        "lemming" : "Leming",
        # REPAIR RULES, keyed on the CORRUPTED output the old bare rule left
        # behind. Six files on the live site carry "Lemings", and the fixed
        # rules above cannot reach them: the damage is already written, and
        # "Lemings" is not a key. Same pattern as the "guidance Councilors"
        # repairs further down -- correcting a rule does not correct what it
        # already produced, so the old output needs its own rule.
        # The metaphor is restored exactly (lowercase, plural); the rest are
        # the councilor with a spurious "s" the plural echo carried through.
        "join the Lemings" : "join the lemmings",
        "Councilor Lemings" : "Councilor Leming",
        "from Lemings" : "from Leming",
        "Lemingston" : "Leming",
        "Lemmon" : "Leming",
        "Leving" : "Leming",
        "Councilor Lemingng" : "Councilor Leming",
        "Councilor Lemmick" : "Councilor Leming",

        "Lungo Kern" : "Lungo-Koehn",
        "Lungo-Kern" : "Lungo-Koehn",
        "Lugo-Kern" : "Lungo-Koehn",
        "Longo Kern" : "Lungo-Koehn",
        "Lungokern" : "Lungo-Koehn",
        "Longa Kern" : "Lungo-Koehn",
        "logo current" : "Lungo-Koehn",
        "Longo, current" : "Lungo-Koehn",
        "Longo-Kern" : "Lungo-Koehn",
        "Locurne" : "Lungo-Koehn",
        "Lingo-Kern" : "Lungo-Koehn",
        "Longocurn" : "Lungo-Koehn",
        "Legault Kern" : "Lungo-Koehn",
        "Lugo-Curran" : "Lungo-Koehn",
        "Lunga-Karn" : "Lungo-Koehn",
        "Luongo-Kern" : "Lungo-Koehn",
        "Langel-Kern" : "Lungo-Koehn",
        "Longo, Kern" : "Lungo-Koehn",
        "Long-Kern" : "Lungo-Koehn",
        "Luongo Kern" : "Lungo-Koehn",
        "Alongo Kern" : "Lungo-Koehn",
        "Lincoln-Kern" : "Lungo-Koehn",
        "Malango-Kern" : "Lungo-Koehn",
        "Lego-Kern" : "Lungo-Koehn",
        "Brianna Lungo-Koehn" : "Breanna Lungo-Koehn",
        "McKern" : "Lungo-Koehn",
        "Council Member Kern" : "Councilor Lungo-Koehn",
        "Langer-Cohen" : "Lungo-Koehn",

        "Counsel Mox": "Councilor Marks",
        "Counsel Marx": "Councilor Marks",
        "Councilor marks": "Councilor Marks",
        "Councilor Max": "Councilor Marks",
        "council marks": "Councilor Marks",
        "council Mox": "Councilor Marks",
        "Council Mox": "Councilor Marks",

        "Jerry McHugh": "Gerry McCue",

        "Morrell" : "Morell",
        "Councilor morale" : "Councilor Morell",

        "McStone" : "Mustone",
        "Mrs stone" : "Mrs. Mustone",
        "Member Stone" : "Member Mustone",

        "Navarro" : "Navarre",
        "Navar," : "Navarre,",

        "Alicia Nunley": "Aleesha Nunley",
        "Alicia Donnelly Benjamin": "Aleesha Nunley Benjamin",

        "Olopade" : "Olapade",
        "Olapode" : "Olapade",

        "Councilor Pinto" : "Councilor Penta",
        "council Penta" : "Councilor Penta",

        "Tony Ray": "Toni Wray",
        "Tony Wray": "Toni Wray",
        "Miss Tony Ray": "Miss Toni Wray",

        "Reinfeldt" : "Reinfeld",
        "Rheinfeld" : "Reinfeld",

        "Member Russo" : "Member Ruseau",
        "member Russo" : "member Ruseau",
        "Roussel" : "Ruseau",
        "Member Rousseau" : "Member Ruseau",
        "Member Ruseaul" : "Member Ruseau",

        "Scott Pelley" : "Scarpelli",
        "Scarfelli" : "Scarpelli",
        "Scarbelli" : "Scarpelli",
        "Carpelli" : "Scarpelli",
        "Scott Pelli" : "Scarpelli",
        "Scott Pelly" : "Scarpelli",
        "Scott Kelly" : "Scarpelli",
        "Starkelli" : "Scarpelli",
        "Skarpel" : "Scarpelli",
        "Scott Pele" : "Scarpelli",
        "Spadafore" : "Scarpelli",
        "Scavoli" : "Scarpelli",
        "Scarpa" : "Scarpelli",
        "Scott Riley" : "Scarpelli",

        "Mr. Scarry" : "Mr. Skerry",
        "Mr. Scary" : "Mr. Skerry",
        "Mr. scurry" : "Mr. Skerry",

        "Councilor Sang" : "Councilor Tseng",
        "Councilor saying" : "Councilor Tseng",
        "councilor saying" : "Councilor Tseng",
        "Councilor Tsang" : "Councilor Tseng",
        "Councilor Say" : "Councilor Tseng",
        "Councilor Singh" : "Councilor Tseng",
        "Councilor Stang" : "Councilor Tseng",
        "Councilor Sank" : "Councilor Tseng",
        "Councilor Sanz" : "Councilor Tseng",
        "Councilor Sanchez" : "Councilor Tseng",
        "Councilor Sands" : "Councilor Tseng",
        "Justin Sang" : "Justin Tseng",
        "Saeng": "Tseng",
        " Seng" : " Tseng",
        "Hsieng" : "Tseng",
        "Zeng" : "Tseng",
        "Sviggum" : "Tseng",

        "Van de Kloet" : "Van der Kloot",
        "Van de Kloot" : "Van der Kloot",
        "Van De Kloot" : "Van der Kloot",
        "Vanderkloof" : "Van der Kloot",
        "Van de Groot" : "Van der Kloot",
        "Vander Kloot" : "Van der Kloot",

        "Vardabedian" : "Vartabedian",
        "Vardabedi" : "Vartabedian",
        "Bartabedian" : "Vartabedian",
        "Bardabedian" : "Vartabedian",

        "Councilor Mox" : "Councilor Marks",
        "Council Meeks" : "Councilor Marks",


        # ---- CONTEXTUAL NAME RULES (generated by propose_name_rules.py)
        # Whisper mis-hears councilor surnames constantly, and the old
        # UNANCHORED matching caught the inflected forms by accident:
        # "Mox" fired inside "Moxley". Anchoring stopped the damage
        # ("guidance counselors") but also stopped that help, so the
        # inflected forms are now explicit.
        #
        # They are CONTEXTUAL on purpose -- keyed on "Councilor Moxley",
        # never bare "Moxley". A bare-surname rule would rename real
        # people: "Fiona Maxwell", "the 2019 Maxwell Teacher of the
        # Year", "Walter Beasley" the musician, "Brianna Scholl".
        # Only 38 of 111 "Maxwell" uses follow an honorific.
        #
        # The target is the bare surname: the trailing garbage is a word
        # Whisper swallowed and cannot be recovered, so "Councilor
        # Marksley" was never right either.
        "Councilor Moxley" : "Councilor Marks",   # 119
        "Councilor Maxwell" : "Councilor Marks",   # 35
        "Councilor Scarpalli" : "Councilor Scarpelli",   # 25
        "Councilor McKernan" : "Councilor Lungo-Koehn",   # 22
        "Councilor Beasley" : "Councilor Bears",   # 16
        "Councilor Moxon" : "Councilor Marks",   # 15
        "Councilor Sangh" : "Councilor Tseng",   # 11
        "Councilor Carvell" : "Councilor Caraviello",   # 10
        "Councilor Moxley's" : "Councilor Marks",   # 10
        "Councilman Moxley" : "Councilman Marks",   # 8
        "President Bereson" : "President Bears",   # 8
        "President Bexar" : "President Bears",   # 8
        "Councillor Maxx" : "Councillor Marks",   # 7
        "Councilor Lungo-Kernan" : "Councilor Lungo-Koehn",   # 7
        "Councilor Scarpallo" : "Councilor Scarpelli",   # 7
        "Councilor Langel-Kernan" : "Councilor Lungo-Koehn",   # 6
        "Councilor Moxwell" : "Councilor Marks",   # 6
        "Councilor Nyeth" : "Councilor Knight",   # 6
        "Councilor Sayeed" : "Councilor Tseng",   # 6
        "President Beresford" : "President Bears",   # 6
        "Councilor Caviella" : "Councilor Caraviello",   # 4
        "Councilor Moxby" : "Councilor Marks",   # 4
        "Councilor Nighton" : "Councilor Knight",   # 4
        "President Beasley" : "President Bears",   # 4
        "Vice President Moxley" : "Vice President Marks",   # 4
        "Councillor Maxwell" : "Councillor Marks",   # 3
        "Councilor Beast" : "Councilor Bears",   # 3
        "Councilor Beresford" : "Councilor Bears",   # 3
        "Councilor Carvella" : "Councilor Caraviello",   # 3
        "Councilor Carviella" : "Councilor Caraviello",   # 3
        "Councilor Carviolo" : "Councilor Caraviello",   # 3
        "Councilor Cavielli" : "Councilor Caraviello",   # 3
        "Councilor Kerriolo" : "Councilor Caraviello",   # 3
        "Councilor Maxx" : "Councilor Marks",   # 3
        "Councilor Moxx" : "Councilor Marks",   # 3
        "Councilor Sangin" : "Councilor Tseng",   # 3
        "Counselor Moxley" : "Counselor Marks",   # 3
        "President Bexar's" : "President Bears",   # 3
        "Vice President Bexar" : "Vice President Bears",   # 3
        "Councillor Sangh" : "Councillor Tseng",   # 2
        "Councillor Sayng" : "Councillor Tseng",   # 2
        "Councilman Moxley's" : "Councilman Marks",   # 2
        "Councilor Bereson" : "Councilor Bears",   # 2
        "Councilor Carvelo" : "Councilor Caraviello",   # 2
        "Councilor Carviollo" : "Councilor Caraviello",   # 2
        "Councilor Cavielles" : "Councilor Caraviello",   # 2
        "Councilor Lazara" : "Councilor Lazzaro",   # 2
        "Councilor Levingston" : "Councilor Leming",   # 2
        "Councilor Moxton" : "Councilor Marks",   # 2
        "Councilor Nightson" : "Councilor Knight",   # 2
        "Councilor Scarpale" : "Councilor Scarpelli",   # 2
        "Councilor Scarpalli's" : "Councilor Scarpelli",   # 2
        "Councilor Skarpelic" : "Councilor Scarpelli",   # 2
        "Counselor Carvella" : "Counselor Caraviello",   # 2
        "President Behrens" : "President Bears",   # 2
        "President Cavielli" : "President Caraviello",   # 2
        "Vice President Moxby" : "Vice President Marks",   # 2
        "Council President Beresford" : "Council President Bears",   # 1
        "Council President Berest" : "Council President Bears",   # 1
        "Council President Carvell" : "Council President Caraviello",   # 1
        "Councillor Cavielle" : "Councillor Caraviello",   # 1
        "Councillor Lingo-Kernan" : "Councillor Lungo-Koehn",   # 1
        "Councillor Maxwell's" : "Councillor Marks",   # 1
        "Councillor McKernan" : "Councillor Lungo-Koehn",   # 1
        "Councillor Moxley" : "Councillor Marks",   # 1
        "Councillor Moxon" : "Councillor Marks",   # 1
        "Councillor Moxwell" : "Councillor Marks",   # 1
        "Councillor Nighton" : "Councillor Knight",   # 1
        "Councillor Sangha's" : "Councillor Tseng",   # 1
        "Councillor Sangivarius" : "Councillor Tseng",   # 1
        "Councillor Sanglin" : "Councillor Tseng",   # 1
        "Councillor Sayeed" : "Councillor Tseng",   # 1
        "Councillor Scarpaoli's" : "Councillor Scarpelli",   # 1
        "Councillor Senghap" : "Councillor Tseng",   # 1
        "Councillor Zaroff" : "Councillor Lazzaro",   # 1
        "Councilman Maxwell" : "Councilman Marks",   # 1
        "Councilor Beasley's" : "Councilor Bears",   # 1
        "Councilor Beerson" : "Councilor Bears",   # 1
        "Councilor Carbiela" : "Councilor Caraviello",   # 1
        "Councilor Carvela" : "Councilor Caraviello",   # 1
        "Councilor Carviella's" : "Councilor Caraviello",   # 1
        "Councilor Carvillalo" : "Councilor Caraviello",   # 1
        "Councilor Carviola" : "Councilor Caraviello",   # 1
        "Councilor Cavielle" : "Councilor Caraviello",   # 1
        "Councilor Felcome" : "Councilor Falco",   # 1
        "Councilor Kerrioville" : "Councilor Caraviello",   # 1
        "Councilor Lazardo" : "Councilor Lazzaro",   # 1
        "Councilor Maxson" : "Councilor Marks",   # 1
        "Councilor Maxwell's" : "Councilor Marks",   # 1
        "Councilor Morrelle" : "Councilor Morell",   # 1
        "Councilor Moxhead" : "Councilor Marks",   # 1
        "Councilor Moxon's" : "Councilor Marks",   # 1
        "Councilor Moxson" : "Councilor Marks",   # 1
        "Councilor Nighthill" : "Councilor Knight",   # 1
        "Councilor Nightingale" : "Councilor Knight",   # 1
        "Councilor Nightingdall" : "Councilor Knight",   # 1
        "Councilor Nighton-Falco" : "Councilor Knight",   # 1
        "Councilor Pierson" : "Councilor Bears",   # 1
        "Councilor Sanga" : "Councilor Tseng",   # 1
        "Councilor Sangalo" : "Councilor Tseng",   # 1
        "Councilor Sangam" : "Councilor Tseng",   # 1
        "Councilor Sangamon" : "Councilor Tseng",   # 1
        "Councilor Sangano" : "Councilor Tseng",   # 1
        "Councilor Sanger" : "Councilor Tseng",   # 1
        "Councilor Sangford" : "Councilor Tseng",   # 1
        "Councilor Sanghia" : "Councilor Tseng",   # 1
        "Councilor Sangley" : "Councilor Tseng",   # 1
        "Councilor Sanglin" : "Councilor Tseng",   # 1
        "Councilor Sangmin" : "Councilor Tseng",   # 1
        "Councilor Sankto" : "Councilor Tseng",   # 1
        "Councilor Sayegh" : "Councilor Tseng",   # 1
        "Councilor Sayre" : "Councilor Tseng",   # 1
        "Councilor Scarpaio" : "Councilor Scarpelli",   # 1
        "Councilor Scarpalla" : "Councilor Scarpelli",   # 1
        "Councilor Scarpaolo" : "Councilor Scarpelli",   # 1
        "Councilor Scarparalee" : "Councilor Scarpelli",   # 1
        "Councilor Scarparilli" : "Councilor Scarpelli",   # 1
        "Councilor Skarpelian-Seng" : "Councilor Scarpelli",   # 1
        "Councilor Skarpelos" : "Councilor Scarpelli",   # 1
        "Councilor Stangley" : "Councilor Tseng",   # 1
        "Councilor Zahraro" : "Councilor Lazzaro",   # 1
        "Counselor Caviell" : "Counselor Caraviello",   # 1
        "Counselor Moxley's" : "Counselor Marks",   # 1
        "President Baresky" : "President Bears",   # 1
        "President Bareson" : "President Bears",   # 1
        "President Barrison" : "President Bears",   # 1
        "President Beerson" : "President Bears",   # 1
        "President Beresey's" : "President Bears",   # 1
        "President Beresia" : "President Bears",   # 1
        "President Pierson" : "President Bears",   # 1
        "Vice President Bareson" : "Vice President Bears",   # 1
        "Vice President Beresford" : "Vice President Bears",   # 1
        "Vice President Carviella" : "Vice President Caraviello",   # 1
        "Vice President Caviella" : "Vice President Caraviello",   # 1
        "Vice President Moxon" : "Vice President Marks",   # 1
        "Vice-President Moxx" : "Vice-President Marks",   # 1
        "Vice-President Nightingale" : "Vice-President Knight",   # 1

        # both spellings are mis-hearings of School Committee member
        # Erika Reinfeld; the old rules produced "Reinfeldt", also wrong
        "Rheinfeldt" : "Reinfeld",
        "Reinfeldt" : "Reinfeld",

        # School Committee member Paul Ruseau, mis-heard as "Roussell".
        # Contextual because the honorific is what makes it unambiguous --
        # and note the SIBLING rule "Russo" -> "Ruseau" is deliberately NOT
        # restored: "Russo" in the originals is "Mr. Del Russo" / "Vice
        # President Del Russo", i.e. Fred Dello Russo, a DIFFERENT sitting
        # official. That rule was renaming one official as another, which
        # word-boundary anchoring now prevents.
        "Member Roussell" : "Member Ruseau",
        "Mr. Roussell" : "Mr. Ruseau",
        "Mr Roussell" : "Mr. Ruseau",

        # School Committee member Paula Van der Kloot. The bare "de" -> "der"
        # rule this replaces was far too broad -- it fired on any standalone
        # "de", including inside a segment Whisper mis-detected as Welsh
        # ("Yn ymwneud ag Ysgrifennydd Van der Klooth").
        "Van de Kloot" : "Van der Kloot",
        "Van de Klooth" : "Van der Kloot",
        "Van der Klooth" : "Van der Kloot",

        # ---- REMAINDER: rules keyed on the OLD GARBLED OUTPUT ---------
        # The bulk of these were fixed by rebuilding .srt from .srt.orig
        # with the corrected rules. 28 files could not be rebuilt safely
        # -- 11 carry hand corrections, 17 failed the safety check that
        # the published text is exactly old_rules(.orig). Those still hold
        # the garbled forms, and the rules above cannot help because they
        # key on what Whisper HEARD ("Councilor Moxley"), which no longer
        # appears in that text.
        #
        # So these key on the garbled form instead. Contextual for the
        # same reason as the others, and safe to apply in place, which
        # means the hand-corrected files keep their edits.
        "Councilman Markson" : "Councilman Marks",
        "Councilor Bearsley" : "Councilor Bears",
        "Councilor Knightth" : "Councilor Knight",
        "Councilor Lungo-Koehnan" : "Councilor Lungo-Koehn",
        "Councilor Marksley" : "Councilor Marks",
        # Converted from BARE surname rules 2026-09-18. Bare forms renamed real
        # people: a project engineer (Carlos Ferreira), a resident giving her name
        # and address for the record (Eliane Ferreira), a budget director
        # (Courtney Cardillo), an attorney (Ian Urquhart), a DEP official (Pam
        # Merrill), an obituary (Piso Cardillo) -- all published as councilors.
        # After a council honorific the same words are mis-hearings of officials.
        "Councilor Ferreira" : "Councilor Caraviello",
        "President Ferreira" : "President Caraviello",
        "Vice President Ferreira" : "Vice President Caraviello",
        "Councilor Cardillo" : "Councilor Caraviello",
        "President Cardillo" : "President Caraviello",
        "Vice President Cardillo" : "Vice President Caraviello",
        "Councilor Carvalho" : "Councilor Caraviello",
        "President Carvalho" : "President Caraviello",
        "Vice President Carvalho" : "Vice President Caraviello",
        "Councilor Capelli" : "Councilor Scarpelli",
        "President Capelli" : "President Scarpelli",
        "Vice President Capelli" : "Vice President Scarpelli",
        "Councilor Merrill" : "Councilor Morell",
        "President Merrill" : "President Morell",
        "Vice President Merrill" : "Vice President Morell",
        "Councilor Murrell" : "Councilor Morell",
        "President Murrell" : "President Morell",
        "Vice President Murrell" : "Vice President Morell",
        "Councilor Hussain" : "Councilor Tseng",
        "President Hussain" : "President Tseng",
        "Vice President Hussain" : "Vice President Tseng",
        "Clerk Urquhart" : "Clerk Hurtubise",
        "Councilor Markson" : "Councilor Marks",
        "Councilor Markswell" : "Councilor Marks",
        "Councilor Marksx" : "Councilor Marks",
        "Councilor Scarpellilli" : "Councilor Scarpelli",
        "President Bearson" : "President Bears",
        "Vice President Bearsar" : "Vice President Bears",

        # ---- last three stragglers, each a shape the generated rules missed
        # (858 substitutions -> 3). Kept specific rather than generalised:
        # a bare "Markson" -> "Marks" could rename a real Mr. Markson, and
        # these are one-off occurrences, not a pattern worth widening for.
        "President Caravielloli" : "President Caraviello",
        "Mr. Markson" : "Mr. Marks",
        # a plural honorific followed by a LIST -- the name is not adjacent to
        # the honorific, so the contextual rules cannot reach it
        "Falco, Markson" : "Falco, Marks",

        # The guidance-counselor case, keyed on the CORRUPTED form. The
        # lookbehind in RULE_EXCEPTIONS prevents NEW corruption, but files the
        # rebuild could not touch (hand-corrected ones) still contain the old
        # output, and no rule above matches it.
        "guidance Councilors" : "guidance counselors",
        "guidance Councilor" : "guidance counselor",
        "Guidance Councilors" : "Guidance counselors",
        "Guidance Councilor" : "Guidance counselor",
    }

    if yt_id == None:
        path = '*/20??-??-??_???????????.srt'
    else:
        path = "*/20??-??-??_" + yt_id + ".srt"

    srtfiles = glob.glob(path)

    patterns = compile_rules(replace_dict)
    dated = [(start, compile_rules(rules))
             for start, rules in sorted(DATED_REPLACEMENTS.items())]

    for srtfilename in srtfiles:
        # Rules that only hold from a date onward. The filename carries the
        # date, so this costs a regex and no metadata lookup.
        m = re.search(r"(20\d\d-\d\d-\d\d)_", os.path.basename(srtfilename))
        file_date = m.group(1) if m else "9999-99-99"
        rules_here = list(patterns)
        for start, pats in dated:
            if file_date >= start:
                rules_here.extend(pats)

        # back it up
        if not os.path.exists(srtfilename + '.orig'):
            shutil.copyfile(srtfilename,srtfilename + '.orig')

        # read it
        with open(srtfilename, 'r', encoding="utf-8") as f:
            text = f.read()

        new_text = apply_rules(text, rules_here)

        # write it out
        if new_text != text:
            with open(srtfilename, 'w', encoding="utf-8") as f:
                f.write(new_text)

if __name__ == "__main__":
    fix_common_errors()