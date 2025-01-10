import glob
import shutil
import ipdb
import os

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
        "city of Medford": "city of Method",

        "Missituck" : "Missituk",
        "Misituk" : "Missituk",
        "Mistituck" : "Missituk",

        "Car Park" : "Carr Park",

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
        "Lazarro" : "Lazzaro",
        "Lazarus" : "Lazzaro",
        "Lozero" : "Lazzaro",
        "Lazzaroo" : "Lazzaro",
        "Councilor Lazar" : "Councilor Lazzaro",
        "Councilor Zahra" : "Councilor Lazzaro",
        "Councilor Zara" : "Councilor Lazzaro",

        "Lemming" : "Leming",
        "lemming" : "Leming",
        "Lemmon" : "Leming",
        "Councilor Lemi " : "Councilor Leming ",
        "Councilor Lemingng" : "Councilor Leming",

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

    }

    if yt_id == None:
        path = '*/20??-??-??_???????????.srt'
    else:
        path = "*/20??-??-??_" + yt_id + ".srt"

    srtfiles = glob.glob(path)

    for srtfilename in srtfiles:

        # back it up
        if not os.path.exists(srtfilename + '.orig'):
            shutil.copyfile(srtfilename,srtfilename + '.orig')

        # read it
        with open(srtfilename, 'r', encoding="utf-8") as f:
            text = f.read()

        modified = False
        # replace all strings
        for key in replace_dict.keys():
            if str(key) in text:
                modified = True
                text = text.replace(str(key), replace_dict[key])

        # write it out
        if modified:
            with open(srtfilename, 'w', encoding="utf-8") as f:
                f.write(text)

if __name__ == "__main__":
    fix_common_errors()