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

        "Councilor San Buenaventura": "Councilor Tseng? President Bears?",

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
        "Carvalho" : "Caraviello",
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
        "Cardillo" : "Caraviello",
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
        "Ferreira" : "Caraviello",
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
        "Urquhart" : "Hurtubise",
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

        "Lemming" : "Leming",
        "lemming" : "Leming",
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
        "Merrill" : "Morell",
        "Murrell" : "Morell",
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
        "Capelli" : "Scarpelli",
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
        "Saeng": " Tseng",
        " Seng" : " Tseng",
        "Hsieng" : "Tseng",
        "Zeng" : "Tseng",
        "Hussain" : "Tseng",
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
    }

    if yt_id == None:
        path = '*/20??-??-??_???????????.srt'
    else:
        path = "*/20??-??-??_" + yt_id + ".srt"

    srtfiles = glob.glob(path)

    patterns = compile_rules(replace_dict)

    for srtfilename in srtfiles:

        # back it up
        if not os.path.exists(srtfilename + '.orig'):
            shutil.copyfile(srtfilename,srtfilename + '.orig')

        # read it
        with open(srtfilename, 'r', encoding="utf-8") as f:
            text = f.read()

        new_text = apply_rules(text, patterns)

        # write it out
        if new_text != text:
            with open(srtfilename, 'w', encoding="utf-8") as f:
                f.write(new_text)

if __name__ == "__main__":
    fix_common_errors()