import datetime, time, os
import ipdb
from wordcloud import WordCloud
import json,glob
from googletrans import Translator, constants
import shutil
import os
import gzip
from xml.etree import cElementTree

def finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop, eshtml=None):
    # new speaker; wrap up and start new
    if text != "":
        html.write('    <p><a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
        html.write("[" + speaker + "]</a>: " + text + "</p>\n\n")

        if eshtml != None:
            translator = Translator()
            translation = translator.translate(text, dest="es")
            eshtml.write('    <p><a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
            eshtml.write("[" + speaker + "]</a>: " + translation.text + "</p>\n\n")

    # let's do some stats by speaker
    if not speaker in speaker_stats.keys(): speaker_stats[speaker] = {"words": {}, "all_words" : ""}
    
    # time
    added_time = stop-start
    if "total_time" in speaker_stats[speaker].keys(): speaker_stats[speaker]["total_time"] += added_time
    else: speaker_stats[speaker]["total_time"] = added_time

    # all words for word cloud
    speaker_stats[speaker]["all_words"] += text

    added_words = 0
    for word in text.split():
        this_word = word.lower().split(".")[0].split(",")[0]
        added_words += 1
        if this_word in speaker_stats[speaker]["words"].keys(): speaker_stats[speaker]["words"][this_word] += 1
        else: speaker_stats[speaker]["words"][this_word] = 1

    if "total_words" in speaker_stats[speaker].keys(): speaker_stats[speaker]["total_words"] += added_words
    else: speaker_stats[speaker]["total_words"] = added_words

def srt2html(yt_id):

    srtfilename = glob.glob('*'+yt_id+'*/*.srt')[0]
    htmlfilename = os.path.splitext(srtfilename)[0] + '.html'
    eshtmlfilename = os.path.splitext(srtfilename)[0] + '.es.html'
    dir = os.path.dirname(srtfilename)

    last_changed = os.path.getmtime(srtfilename)

    # we will do some analytics on these people
    councilors = [
    # Mayor
    "Lungo-Koehn", # Mayor 2020-
    "Burke", # Mayor 2016-2020
    "McGlynn", # Mayor 1988-2016
    # City Councilors
    "Callahan","Lazzaro","Leming", # 2024 (Caraviello, Knight, Morell out) 
    "Collins","Tseng", # 2022 (Marks, Falco out)
    "Bears","Morell", # 2020 (Dello Russo, Lungo-Koehn out)
    # 2018 (no new councilors)
    "Falco", "Scarpelli", # 2016 (Penta, Camuso out)
    "Knight", # 2014 (Maiocco out)
    "Caraviello", # 2012 (Burke out)
    # 2010 (no new members)
    "Camuso","Dello Russo","Maiocco","Marks","Penta", # 2008 (also Burke, Lungo-Koehn)
    # School Committee
    "Branley","Intoppa","Olapade","Reinfeld", # 2024 (Kreatz, McLaughlin, Mustone, Hays out)
    "Hays", # 2022 (Van der Kloot out)
    "McLaughlin","Graham", # 2020 (DiBenedetto, Ruggiero out)
    "Ruseau","Ruggiero", # 2018 (Skerry, Cugno out)
    "Kreatz","Mustone", # 2016 (Falco, Scarpelli out)
    # 2014 (no new members) 
    # 2012 (Plus Skerry, Guzik out)
    "DiBenedetto","Guzik", # 2010 (plus Falco, Scarpelli. Brady, DiGiantommaso, Pompeo, Skerry out)
    "Brady","Cugno","DiGiantommaso","Pompeo","Skerry", "Van der Kloot", # 2008
    ]

    speaker = ""
    start = 0.0
    stop = 86400.0
    text = ""
    t0 = datetime.datetime(1900,1,1)    

    # read in the speaker mappings
    jsonfile = os.path.join(dir,'speaker_ids.json')
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)
        last_changed = max(os.path.getmtime(jsonfile),last_changed)
    else: speaker_ids = {}

    ### if the speaker IDs or SRT file haven't been updated since we did this last, no need to redo it ###
    jsonfile = os.path.join('video_data.json')
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else:
        video_data = {}

    last_update = 0.0
    if yt_id in video_data.keys():
        if "last_update" in video_data[yt_id].keys():
            last_update = video_data[yt_id]["last_update"]

    # redo all videos updated before 2024-11-04 2:35 PM
    #last_update = datetime.datetime(2024,11,4,14,35).timestamp() 
    #last_update = 0.0 # uncomment to remake them all (for changes to the template)
    if (last_update > last_changed) and os.path.exists(htmlfilename) and os.path.exists(eshtmlfilename): return
    #######################################################################################################
    print("Making HTML for " + yt_id)

    video_title = video_data[yt_id]["title"]
    title = "Transcript for " + video_title + " (" + yt_id + ")"

    # output custom html with links to corresponding parts of the youtube video
    html = open(htmlfilename, 'w', encoding="utf-8")
    html.write('<!DOCTYPE html>\n')
    html.write('<html lang="en">\n')
    html.write('  <head>\n')
    html.write('    <meta charset="UTF-8">\n')
    html.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
    html.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
    if "keywords" in video_data[yt_id].keys():
        html.write('    <meta name="keywords" content="' + ','.join(video_data[yt_id]["keywords"]) + '">\n')
    html.write('    <meta name="description" content="AI-generated transcript of ' + video_title + ', a video relevant to Medford Massachusetts local politics">\n')
    html.write('    <title>' + title + '</title>\n')
    html.write('    <link rel="canonical" href="https://medford-transcripts.github.io/' + htmlfilename + '" />\n')
    html.write('  </head>\n')
    html.write('  <body>\n')
    html.write('  <h1>AI-generated transcript of ' + video_title + '</h1>\n')
    html.write('    <a href="../index.html">Back to all transcripts</a><br><br>\n')

    eshtml = open(eshtmlfilename, 'w', encoding="utf-8")
    eshtml.write('<!DOCTYPE html>\n')
    eshtml.write('<html lang="es">\n')
    eshtml.write('  <head>\n')
    eshtml.write('    <meta charset="UTF-8">\n')
    eshtml.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
    eshtml.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
    eshtml.write('    <meta name="description" content="Transcripción generada por IA de ' + video_title + ', un vídeo relevante para la política local de Medford, Massachusetts.">\n')
    eshtml.write('    <title>' + title + '</title>\n')
    eshtml.write('    <link rel="canonical" href="https://medford-transcripts.github.io/' + eshtmlfilename + '" />\n')
    eshtml.write('  </head>\n')
    eshtml.write('  <body>\n')
    eshtml.write('  <h1>Transcripción generada por IA de ' + video_title + '</h1>\n')
    eshtml.write('    <a href="../index.html">Volver a todas las transcripciones</a><br><br>\n')
    speaker_stats = {}

    with open(srtfilename, 'r', encoding="utf-8") as file:

        # Read each line in the file
        for line in file:
            line.strip()

            if "-->" in line:
                # timestamp
                start_string = line.split()[0]
                stop_string = line.split()[-1]

                # convert timestamp to seconds elapsed
                this_start = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
                this_stop = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()

            elif "[" in line:
                # text
                this_speaker = line.split()[0].split("[")[-1].split("]")[0]
                this_text = ":".join(line.split(":")[1:])

                # replace automated speaker tag with speaker ID
                if this_speaker in speaker_ids.keys():
                    this_speaker = speaker_ids[this_speaker]
                else:
                    speaker_ids[this_speaker] = this_speaker

                if this_speaker == speaker:
                    # same speaker; append to previous text
                    text += this_text
                else:
                    finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop, eshtml=eshtml)

                    # update to new values
                    start = this_start
                    text = this_text
                    speaker = this_speaker

                stop = this_stop

            else: continue

    finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop, eshtml=eshtml)

    # create speaker_ids.json, sorting by auto-assigned speaker ID (SPEAKER_##)
    with open(os.path.join(dir,"speaker_ids.json"), "w") as fp:
        json.dump(dict(sorted(speaker_ids.items())), fp, indent=4)

    # get speaker stats (total time speaking, number of words), make a word cloud
    for speaker in speaker_stats.keys():
        nprinted = 0
        if speaker != '':
            print(speaker + ': ')
            print("  total time: " + str(round(speaker_stats[speaker]["total_time"]/60.0,2)) + ' minutes')
            print("  total words: " + str(speaker_stats[speaker]["total_words"]))

            # make a word cloud
            if speaker in councilors:
                wordcloud = WordCloud(max_font_size=40).generate(speaker_stats[speaker]["all_words"])
                wordcloud.to_file(os.path.join(dir,speaker + '.wordcloud.png'))


    ncols = 4
    nrows = 4
    idx = 0

    # find the subset of councilors present
    present_councilors = []
    for speaker_id in speaker_stats.keys():
        if speaker_id in councilors: present_councilors.append(speaker_id)

    # make a table with stats
    html.write('  <table>\n')
    for i in range(nrows):
        html.write('    <tr>\n')
        for j in range(ncols):
            html.write('      <td>\n')
            idx = i*ncols+j
            if idx < len(present_councilors):
                if present_councilors[idx] in speaker_stats.keys():
                    imagename = present_councilors[idx] + '.wordcloud.png'
                    html.write('        <center>' + present_councilors[idx] + "</center><br>\n")
                    html.write('        total time: ' + str(round(speaker_stats[present_councilors[idx]]["total_time"]/60.0,2)) + ' minutes<br>\n')
                    html.write('        total words: ' + str(speaker_stats[present_councilors[idx]]["total_words"]) + '<br>\n')
                    html.write('        <a href="' + imagename + '"><img src="' + imagename + '" alt="word cloud for ' + present_councilors[idx] + '" height=150></img></a><br>\n')
            html.write('      </td>\n')
        html.write('    </tr>\n')
    html.write('  </table>\n')
    html.write('  <br><br><a href="../index.html">Back to all transcripts</a><br><br>\n')
    html.write('  </body>\n')
    html.write('</html>\n')
    html.close()


    eshtml.write('    <a href="../index.html">Volver a todas las transcripciones</a><br><br>\n')
    eshtml.write('  </body>\n')
    eshtml.write('</html>\n')
    eshtml.close()
    eshtml.close()

    if yt_id not in video_data.keys(): video_data[yt_id] = {}
    video_data[yt_id]["last_update"] = time.time()
    with open(jsonfile, "w") as fp:
        json.dump(video_data, fp, indent=4)

def make_index():

    import yt_dlp
    # read in the speaker mappings
    jsonfile = 'video_data.json'
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else:
        video_data = {}

    htmlfiles = glob.glob('*/*.html')
    lines = []
    for htmlfile in htmlfiles:
        if htmlfile.startswith("electeds"): continue
        if htmlfile.endswith("es.html"): continue
        date = htmlfile.split('_')[0]
        yt_id = '_'.join(htmlfile.split('_')[1:]).split('\\')[0]

        eshtmlfile = os.path.splitext(htmlfile)[0]+'.es.html'
        srtfile = os.path.splitext(htmlfile)[0]+'.srt'
        speaker_id_file = os.path.join(os.path.dirname(htmlfile),'speaker_ids.json')
        url = "https://youtu.be/" + yt_id 

        download = True
        if yt_id in video_data.keys():
            if "duration" in video_data[yt_id].keys():
                title = video_data[yt_id]["title"]
                channel = video_data[yt_id]["channel"]
                duration = video_data[yt_id]["duration"]
                download = False

        if download:
            info = yt_dlp.YoutubeDL().extract_info(url, download=False) 
            title = info["title"]
            channel = info["channel"]
            duration = info["duration"]
            video_data[yt_id] = {}
            video_data[yt_id]["title"] = title
            video_data[yt_id]["channel"] = channel
            video_data[yt_id]["duration"] = duration

        duration_string = time.strftime('%H:%M:%S', time.gmtime(duration))

        # one row in the html table
        lines.append('      <tr>' +\
            '<td>' + date + '</td>' +\
            '<td><a href="' + url + '">[' + duration_string + ']</a></td>'+\
            '<td>' + channel + '</td>'+\
            '<td>'+title+'</td>'
            '<td><a href="' + htmlfile +'">English</a></td>'+\
            '<td><a href="' + eshtmlfile + '">Spanish</a></td>'+\
            '<td><a href="' + srtfile + '">SRT</a></td>'+\
            '<td><a href="' + speaker_id_file + '">JSON</a></td>'+\
            '</tr>\n')

    with open(jsonfile, "w") as fp:
        json.dump(video_data, fp, indent=4)

    lines.sort(reverse=True)
    shutil.copy("header.html", "index.html")
    index_page = open('index.html', 'a', encoding="utf-8")
    index_page.write("    <table border=1>\n")
    # table header
    index_page.write("      <tr><td><center>Upload Date</center></td><td><center>Duration</center></td><td><center>Channel</center></td><td><center>Title</center></td><td colspan=2><center>Transcript</center></td><td colspan=2><center>Raw files</center></td></tr>\n")
    for line in lines:
        index_page.write(line)
    index_page.write("    </table>\n")
    index_page.write('  </body>\n')
    index_page.write('</html>\n')
    index_page.close()

def make_sitemap():

    files = glob.glob("*/*.html")

    # make a txt sitemap
    #sitemap_file = 'sitemap.txt'
    #with open(sitemap_file, "w") as fp:
    #    for file in files:
    #        fp.write("https://medford-transcripts.github.io/"+file.replace('\\', '/')+'\n')

    # create root XML node
    sitemap_root = cElementTree.Element('urlset')
    sitemap_root.attrib['xmlns'] = "http://www.sitemaps.org/schemas/sitemap/0.9"

    # add urls
    for file in files:
        timestamp = datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(os.path.getmtime(file)),'%Y-%m-%dT%H:%M:%SZ') 
        url = "https://medford-transcripts.github.io/"+file.replace('\\', '/')
        add_url(sitemap_root, url, timestamp)

    # save sitemap. xml extension will be added automatically
    save_sitemap(sitemap_root, "./sitemap")


def add_url(root_node, url, lastmod):
    doc = cElementTree.SubElement(root_node, "url")
    cElementTree.SubElement(doc, "loc").text = url
    cElementTree.SubElement(doc, "lastmod").text = lastmod

    return doc


def save_sitemap(root_node, save_as, **kwargs):
    compress = kwargs.get("compress", False)

    sitemap_name = save_as.split("/")[-1]
    dest_path = "/".join(save_as.split("/")[:-1])

    sitemap_name = f"{sitemap_name}.xml"
    if compress:
        sitemap_name = f"{sitemap_name}.gz"

    save_as = f"{dest_path}/{sitemap_name}"

    # create sitemap path if not existed
    if not os.path.exists(f"{dest_path}/"):
        os.makedirs(f"{dest_path}/")

    if not compress:
        tree = cElementTree.ElementTree(root_node)
        tree.write(save_as, encoding='utf-8', xml_declaration=True)
    else:

        # gzip sitemap
        gzipped_sitemap_file = gzip.open(save_as, 'wb')
        cElementTree.ElementTree(root_node).write(gzipped_sitemap_file)
        gzipped_sitemap_file.close()

    return sitemap_name

def do_all():
    files = glob.glob("*/20??-??-??_???????????.srt")
    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        srt2html(yt_id)

    # make the top level page with links to all transcripts
    make_index()
    make_sitemap()


if __name__ == "__main__":

    do_all()

