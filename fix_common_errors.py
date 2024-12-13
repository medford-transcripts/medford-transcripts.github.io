import glob
import shutil
import ipdb
import os

def fix_common_errors():

    replace_dict = {
        "Councillor" : "Councilor",
        "Counselor" : "Councilor",
        "Membo" : "Member",
        "Mr " : "Mr. ",
        "Mrs " : "Mrs. ",

        "Memphis" : "Medford",
        "Medfitt" : "Medford",
        "Medfit" : "Medford",
        "Medfin" : "Medford",

        "Car Park" : "Carr Park",

        "Behrs" : "Bears",
        "Councilor Beers" : "Councilor Bears",
        "Councilor beers" : "Councilor Bears",
        "Councilor Piers" : "Councilor Bears",
        "Counsel Pierce" : "Councilor Bears",
        "Councilor Beas" : "Councilor Bears",
        "President Beers" : "President Bears",
        "Councilor Baird" : "Councilor Bears",
        "Councilor Baez" : "Councilor Bears",
        "Councilor Bares" : "Councilor Bears",
        "President Bares" : "President Bears",

        "Brantley" : "Branley",
        "Brandley" : "Branley",

        "Councilor Kellyanne" : "Councilor Callahan",
        "Kallian" : "Callahan",

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

        "Castaneda" : "Castagnetti",
        "Castanetti" : "Castagnetti",
        "Castanete" : "Castagnetti",

        "Cuneo" : "Cugno",
        "Kunio" : "Cugno",

        "De La Russo" : "Dello Russo",
        "DelaRusso" : "Dello Russo",
        "Dela Russo" : "Dello Russo",
        "Della Russo" : "Dello Russo",

        "Falcone" : "Falco",
        "Felco" : "Falco",
        "Fevella" : "Falco",

        "Fibber Carrie" : "Fidler-Carey",
        "Fidler, Carrie" : "Fidler-Carey",
        "Fidler Carey" : "Fidler-Carey",
        "Fidler-Carrie" : "Fidler-Carey",

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
        "Neidt" : "Knight",

        "Kretz" : "Kreatz",
        "Kraetz" : "Kreatz",

        " Zaro" : " Lazzaro",
        "Lazaro" : "Lazzaro",
        "Lazarro" : "Lazzaro",
        "Lozaro" : "Lazzaro",
        "Lozano" : "Lazzaro",
        "Lozzaro" : "Lazzaro",
        "Lizaro" : "Lazzaro",
        "Lazarro" : "Lazzaro",
        "Lazarus" : "Lazzaro",
        "Councilor Lazar" : "Councilor Lazzaro",
        "Councilor Zahra" : "Councilor Lazzaro",
        "Councilor Zara" : "Councilor Lazzaro",

        "Lemming" : "Leming",
        "lemming" : "Leming",
        "Lemmon" : "Leming",

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

        "Morrell" : "Morell",
        "Merrill" : "Morell",
        "Murrell" : "Morell",

        "McStone" : "Mustone",
        "Mrs stone" : "Mustone",

        "Navarro" : "Navarre",
        "Navar," : "Navarre,",

        "Olopade" : "Olapade",
        "Olapode" : "Olapade",

        "Councilor Pinto" : "Councilor Penta",

        "Reinfeldt" : "Reinfeld",
        "Rheinfeld" : "Reinfeld",

        "Member Russo" : "Member Ruseau",
        "member Russo" : "member Ruseau",
        "Roussel" : "Ruseau",
        "Member Rousseau" : "Member Ruseau",

        "Scott Pelley" : "Scarpelli",
        "Scarfelli" : "Scarpelli",
        "Scarbelli" : "Scarpelli",
        "Carpelli" : "Scarpelli",
        "Scott Pelli" : "Scarpelli",
        "Scott Kelly" : "Scarpelli",
        "Starkelli" : "Scarpelli",
        "Skarpel" : "Scarpelli",
        "Scott Pele" : "Scarpelli",

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
        " Seng" : " Tseng",
        "Hsieng" : "Tseng",
        "Zeng" : "Tseng",
        "Hussain" : "Tseng",

        "Van de Kloet" : "Van der Kloot",
        "Van de Kloot" : "Van der Kloot",
        "Van De Kloot" : "Van der Kloot",
        "Vanderkloof" : "Van der Kloot",


        "Councilor Mox" : "Councilor Marks",
        "Council Meeks" : "Councilor Marks",

    }

    path = '*/20??-??-??_???????????.srt'
    #path = "2024-11-19_puRJAp7j8rg/2024-11-19_puRJAp7j8rg.srt"
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