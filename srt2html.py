import datetime, time 
import os, shutil, asyncio
import json, glob
from xml.etree import cElementTree
import re
import argparse
import pypdf
import dateutil.parser as dparser
from rapidfuzz import fuzz, process

import ipdb

from wordcloud import WordCloud

# dependency hell... 
#pip install googletrans
#pip install httpx==0.28.1 --ignore-requires-python
#pip install openai
from googletrans import Translator, constants

import yt_dlp

# imports from this repo
import utils, supercut, fix_common_errors, heatmap, scrape

def translate_text(text, dest="en"):
    translator = Translator()
    try:
        result = asyncio.run(translator.translate(text, dest=dest))
        return result.text
    except:
        return text

def finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=None, languages={"en" : "English"}):

    if text == '': return

    #ipdb.set_trace()

    for language in languages.keys():
        if language == 'en':
            htmlfilename = basename + '.html'
            html = open(htmlfilename, 'a', encoding="utf-8")
            html.write("    <p>[" + speaker + "]</a>: " + htmltext + "</p>\n\n")
            html.close()
        else: 
            htmlfilename = basename + '.' + language + '.html'
            if text != None:
                text = translate_text(text, dest=language)
            else: text = ""
            html = open(htmlfilename, 'a', encoding="utf-8")
            html.write('    <p><a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
            html.write("[" + speaker + "]</a>: " + text + "</p>\n\n")
            html.close()

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

def srt2html(yt_id,skip_translation=False, force=False):

    srtfilename = glob.glob('*'+yt_id+'*/20??-??-??_' + yt_id + '.srt')[0]
    htmlfilename = os.path.splitext(srtfilename)[0] + '.html'
    dir = os.path.dirname(srtfilename)

    last_changed = os.path.getmtime(srtfilename)

    # we will do some analytics on these people
    councilors = utils.get_councilors()

    # read in the speaker mappings
    jsonfile = os.path.join(dir,'speaker_ids.json')
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)
        last_changed = max(os.path.getmtime(jsonfile),last_changed)
    else: speaker_ids = {}

    video_data = utils.get_video_data()

    ### if the speaker IDs or SRT file haven't been updated since we did this last, no need to redo it ###
    last_update = 0.0
    if yt_id in video_data.keys():
        if "last_update" in video_data[yt_id].keys():
            last_update = video_data[yt_id]["last_update"]

    # this is my hack to allow non-youtube sources....
    if yt_id[0:6] == "XXXXXX": 
        on_youtube = False
        on_spotify = True
        on_archive = False
    elif yt_id[0:6] == "MCM000":
        on_youtube = False
        on_spotify = False
        on_archive = True
    else:
        on_youtube = True
        on_spotify  = False
        on_archive = False

    # redo all videos updated before 2024-11-04 2:35 PM
    #last_update = datetime.datetime(2024,11,4,2,35).timestamp() 
    #last_update = datetime.datetime(2024,12,12,0,0).timestamp() 
    #last_update = 0.0 # uncomment to remake them all (for changes to the template)
    if (not force) and (last_update > last_changed) and os.path.exists(htmlfilename): return
    #######################################################################################################

    basename = os.path.splitext(srtfilename)[0]
    filebasename = os.path.basename(basename)

    # top 10 languages used in MA from
    # https://www.mass.gov/doc/appendix-f-language-audience-guidesdoc/download
    # english, spanish, brazilian portuguese, chinese, haitian creole, vietnamese, khmer, (cape verdean), russian, arabic, korean
    # cape verdean is not supported by googletrans

    #skip_translation = True
    if skip_translation:
        languages = {'en' : "English" }
    else:
        languages = {
            'en' : "English" , # English
            'es' : "español" , # Spanish
            'pt' : "português" , # Portuguese
            'zh-cn' : "中国人", # Chinese
            'ht' : "kreyol ayisyen" , # Haitian Creole
            'vi' : "tiếng việt" , # Vietnamese
            'km' : "ខ្មែរ", # Khmer
            'ru' : "русский", # Russian
            'ar' : "عربي", # Arabic
            'ko' : "한국인" # Korean
            }

    # generate links to other language pages
    links_to_languages = ""
    for language in languages.keys():
        if language == "en":
            htmlname = filebasename + '.html'
        else:
            htmlname =  filebasename + '.' + language + '.html'
            links_to_languages += ' | '
        links_to_languages += '<a href="' + htmlname + '">' + languages[language] + '</a>'
    #ipdb.set_trace()

    print("Making HTML for " + yt_id)

    video_title = video_data[yt_id]["title"]
    title = "Transcript for " + video_title + " (" + yt_id + ")"

    translator = Translator()
    for language in languages.keys():

        if language == 'en':
            htmlfilename = basename + '.html'
        else: 
            htmlfilename = basename + '.' + language + '.html'

        html = open(htmlfilename, 'w', encoding="utf-8")
        html.write('<!DOCTYPE html>\n')
        html.write('<html lang="' + language + '">\n')
        html.write('  <head>\n')
        html.write('    <meta charset="UTF-8">\n')
        html.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
        html.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
        if "keywords" in video_data[yt_id].keys():
            html.write('    <meta name="keywords" content="' + ','.join(video_data[yt_id]["keywords"]) + '">\n')

        text = 'AI-generated transcript of ' + video_title + ', a video relevant to Medford Massachusetts local politics.'        
        if language != 'en':
            text = translate_text(text, dest=language)

        html.write('    <meta name="description" content="' + text + '">\n')

        text = title    
        if language != 'en':
            text = translate_text(text, dest=language)
        html.write('    <title>' + text + '</title>\n')

        html.write('    <link rel="canonical" href="https://medford-transcripts.github.io/' + htmlfilename + '" />\n')
        html.write('  </head>\n')
        html.write('  <body>\n')

        text = 'AI-generated transcript of ' + video_title
        if language != 'en':
            text = translate_text(text, dest=language)

        html.write('  <h1>' + text + '</h1>\n')

        html.write(links_to_languages + '<br><br>\n')

        text = 'Back to all transcripts'
        if language != 'en':
            text = translate_text(text, dest=language)

        html.write('    <a href="../index.html">' + text + '</a><br><br>\n')

        if os.path.exists(os.path.join(dir,"heatmap.html")):
            text = 'Heatmap of speakers'
            if language != 'en':
                text = translate_text(text, dest=language)

            html.write('    <a href="heatmap.html">' + text + '</a><br><br>\n')

        html.close()

    speaker_stats = {}

    start = 0.0
    stop = 86400.0
    speaker = ""
    text = ""
    htmltext = ""
    t0 = datetime.datetime(1900,1,1)    
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

                this_html_text = this_text
                tmp_text_og = this_html_text.split()

                # if a resolution is mentioned (##-###) and we have a copy of that resolution,
                # link to it (in green to distinguish it from video links)
                resolutions = re.findall(r'\d\d-\d\d\d',this_html_text)+re.findall(r'\d\d\d\d\d',this_html_text)
                resolution_is_first = False
                for resolution in resolutions:
                    if '-' not in resolution:
                        resolution_str = resolution[:2] + '-' + resolution[2:]
                    else:
                        resolution_str = resolution

                    pdf_name = os.path.join('resolutions',resolution_str + '.pdf')
                    if os.path.exists(pdf_name):
                        # replace text
                        link = '<a href="../resolutions/' + resolution_str + '.pdf"><font color="green">' + resolution_str + '</font></a>'
                        this_html_text = this_html_text.replace(resolution,link)

                        if resolution in tmp_text_og[0]:
                            resolution_is_first = True

                # if it's not a resolution, and it's the first word, link to the timestamped video
                tmp_text = this_html_text.split()
                if not resolution_is_first:
                    if on_youtube:
                        link = ' <a href="https://youtu.be/' + yt_id + '&t=' + str(this_start) + 's">' + tmp_text[0] + '</a> '
                    elif on_spotify or on_archive:
                        if 'url' in video_data[yt_id].keys():
                            if on_spotify:
                                link = ' <a href="' + video_data[yt_id]['url'] + '?t=' + str(this_start) + '">' + tmp_text[0] + '</a> '
                            elif on_archive:
                                link = ' <a href="' + video_data[yt_id]['url'] + '&start=' + str(this_start) + '">' + tmp_text[0] + '</a> '
                        else:
                            link = tmp_text[0]
                    else:
                        link = tmp_text[0]
                    tmp_text[0] = link
                    this_html_text = ' '.join(tmp_text)

                # replace automated speaker tag with speaker ID
                if this_speaker in speaker_ids.keys():
                    this_speaker = speaker_ids[this_speaker]
                else:
                    speaker_ids[this_speaker] = this_speaker

                if this_speaker == speaker:
                    # same speaker; append to previous text
                    text += this_text
                    htmltext += this_html_text

                else:
                    finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=htmltext, languages=languages)

                    # update to new values
                    start = this_start
                    text = this_text
                    htmltext = this_html_text
                    speaker = this_speaker

                stop = this_stop

            else: continue

    finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=htmltext, languages=languages)

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
                try:
                    # if only words are common/excluded, it'll raise a valueError
                    wordcloud = WordCloud(max_font_size=40).generate(" ".join(speaker_stats[speaker]["all_words"]))
                    wordcloud.to_file(os.path.join(dir,speaker + '.wordcloud.png'))
                except:
                    pass

    ncols = 4
    nrows = 4
    idx = 0

    # find the subset of councilors present
    present_councilors = []
    for speaker_id in speaker_stats.keys():
        if speaker_id in councilors: present_councilors.append(speaker_id)

    # make a table with stats (english only)
    htmlfilename = basename + '.html'
    html = open(htmlfilename, 'a', encoding="utf-8")
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

    for language in languages:

        text = "Back to all transcripts"

        if language == 'en':
            htmlfilename = basename + '.html'
        else: 
            htmlfilename = basename + '.' + language + '.html'
            text = translate_text(text, dest=language)

        html = open(htmlfilename, 'a', encoding="utf-8")
        html.write('  <br><br><a href="../index.html">' + text + '</a><br><br>\n')
        html.write('  </body>\n')
        html.write('</html>\n')
        html.close()

    # update the saved video data, but reload it in case another process updated it in the meantime
    video_data = utils.get_video_data()
    if yt_id not in video_data.keys(): video_data[yt_id] = {}
    video_data[yt_id]["last_update"] = time.time()

    utils.save_video_data(video_data)

def match_files(title, minutes=False):

    if minutes: 
        dir = "minutes"
    else: 
        dir = "agendas"
    files = glob.glob(os.path.join(dir,'*'))

    try:
        ref_date = dparser.parse(title,fuzzy=True)
    except:
        return ""

    matches = []
    for file in files:
        try:
            date = dparser.parse(os.path.splitext(os.path.basename(file))[0][0:12],fuzzy=True)
        except:
            try:
                date = dparser.parse(os.path.splitext(os.path.basename(file))[0],fuzzy=True)
            except:
                date = ''

        if date == ref_date:
            matches.append(file)

    if len(matches) == 0: return ""
    best_match = process.extractOne(title,matches)
    #print(title)
    #print(best_match)
    #print("")

    return best_match[0]

def make_redirect(dir):
    index_filename = os.path.join(dir,'index.html')

    if os.path.exists(index_filename): return

    with open(index_filename, "w", encoding="utf-8") as index_page:

        index_page.write('<!DOCTYPE HTML>')
        index_page.write('<html lang="en-US">')
        index_page.write('    <head>')
        index_page.write('       <meta charset="UTF-8">')
        index_page.write('        <meta http-equiv="refresh" content="0; url="' + dir + '.html">')
        index_page.write('        <script type="text/javascript">')
        index_page.write('            window.location.href = "' + dir + '.html"')
        index_page.write('        </script>')
        index_page.write('        <title>Page Redirection</title>')
        index_page.write('    </head> index_page.write("<body>')
        index_page.write("       <!-- Note: don't tell people to 'click' the link, just tell them that it is a link. -->")
        index_page.write('        If you are not redirected automatically, follow this <a href="' + dir + '.html">link</a>.')
        index_page.write('    </body>')
        index_page.write('</html>')

def make_index():

    video_data = utils.get_video_data()

    htmlfiles = glob.glob('*/20??-??-??_???????????.html')
    lines = []
    for htmlfile in htmlfiles:
        yt_id = '_'.join(htmlfile.split('_')[1:]).split('\\')[0]

        if yt_id not in video_data.keys(): continue

        if 'skip' in video_data[yt_id].keys():
            if video_data[yt_id]["skip"]: continue

        date = video_data[yt_id]["date"]
        title = video_data[yt_id]["title"]
        channel = video_data[yt_id]["channel"]
        duration = video_data[yt_id]["duration"]
        duration_string = time.strftime('%H:%M:%S', time.gmtime(duration))

        dir = os.path.dirname(htmlfile)
        make_redirect(dir)

        srtfile = os.path.splitext(htmlfile)[0]+'.srt'
        speaker_id_file = os.path.join(os.path.dirname(htmlfile),'speaker_ids.json')
        url = "https://youtu.be/" + yt_id

        agenda_file = match_files(title)
        if agenda_file != "":
            agenda_line = '<td><a href="' + agenda_file +'">Agenda</a></td>'
        else:
            agenda_line = '<td></td>'

        minutes_file = match_files(title,minutes=True)
        if minutes_file != "":
            minutes_line = '<td><a href="' + minutes_file +'">Minutes</a></td>'
        else:
            minutes_line = '<td></td>'

        # one row in the html table
        lines.append('      <tr>' +\
            '<td>' + date + '</td>' +\
            '<td><a href="' + url + '">[' + duration_string + ']</a></td>'+\
            '<td><a href="' + htmlfile +'">' + title + '</a></td>'+\
            agenda_line +\
            minutes_line +\
            '<td>' + channel + '</td>'+\
            '<td><a href="' + srtfile + '">SRT</a></td>'+\
            '<td><a href="' + speaker_id_file + '">JSON</a></td>'+\
            '</tr>\n')

    lines.sort(reverse=True)
    shutil.copy("header.html", "index.html")
    index_page = open('index.html', 'a', encoding="utf-8")
    index_page.write("    <table border=1>\n")
    # table header
    #index_page.write("      <tr><td><center>Date</center></td><td><center>Duration</center></td><td><center>Title (click for transcript)</center></td><td><center>Channel</center></td><td colspan=2><center>Raw files</center></td></tr>\n")
    index_page.write("      <tr><td><center>Date</center></td><td><center>Duration</center></td><td><center>Title (click for transcript)</center></td><td><center>Agenda</center></td><td><center>Minutes</center></td><td><center>Channel</center></td><td colspan=2><center>Raw files</center></td></tr>\n")
    for line in lines:
        index_page.write(line)
    index_page.write("    </table>\n")
    index_page.write('  </body>\n')
    index_page.write('</html>\n')
    index_page.close()

def make_resolution_tracker(do_scrape=True):

    # update meeting files from https://medfordma.civicclerk.com
    if do_scrape: scrape.scrape()

    resolution_dict = {}

    # if a resolution is mentioned (##-###) and we have a copy of that resolution,
    # link to it (in green to distinguish it from video links)
    srtfiles = glob.glob('*/20??-??-??_???????????.srt')


    for srtfile in srtfiles:

        yt_id = '_'.join(srtfile.split('_')[1:]).split('\\')[0]
        htmlfile = os.path.splitext(srtfile)[0] + '.html'

        pattern = r'(?<=\s)(\d{5}|\d{2}-\d{3})(?=[\s.,!?;:\'\"()-])'

        with open(srtfile, 'r', encoding="utf-8") as file:

            # Read each line in the file
            for line in file:
                line.strip()
                resolutions = re.findall(pattern,line)
                for resolution in resolutions:

                    # regularize names as XX-XXX
                    if resolution[2] != "-": 
                        resolution = resolution[:2] + '-' + resolution[2:]

                    # eliminate confusion with other 5-digit numbers
                    year = float(resolution[:2])
                    if year < 10 or year > 25: continue

                    # is the resolution in my dictionary already?
                    if resolution in resolution_dict.keys():
                        # is that meeting ID in the list already?
                        if yt_id not in resolution_dict[resolution]:
                            resolution_dict[resolution].append(yt_id)
                    else:
                        resolution_dict[resolution] = [yt_id]


    video_data = utils.get_video_data()
    sorted_dict = dict(sorted(resolution_dict.items(), reverse=True))
    html = open('resolutions.html', 'w', encoding="utf-8")



    html.write('<table border=1>\n')
    html.write('<tr><td colspan="2">Resolution</td><td>Sponsor</td><td>Description</td></tr>\n')

    for resolution in sorted_dict.keys():
        nvideos = len(sorted_dict[resolution])

        resolution_pdf = os.path.join("resolutions",resolution + '.pdf')
        sponsor = ''
        description = ''
        resolution_text = resolution
        if os.path.exists(resolution_pdf):
            reader = pypdf.PdfReader(resolution_pdf)
            lines = reader.pages[0].extract_text().split('\n')
            use_next_line = False
            add_to_description = False
    
            for line in lines:

                #if '24-357' in resolution_pdf: 
                #    print(line)
                #    ipdb.set_trace()

                if description == '' and line.startswith(resolution):
                    description = " ".join(line.split()[2:])
                    add_to_description = True
                elif add_to_description:
                    if "FULL TEXT AND DESCRIPTION" in line:
                        add_to_description = False
                    else:
                        description += (' ' + line)
                elif "SPONSORED BY" in line:
                    use_next_line = True
                    trim = True
                elif use_next_line:
                    if "AGENDA ITEM" in line:
                        use_next_line = False
                    else:
                        if trim: 
                            sponsor = " ".join(line.split()[3:])
                            trim = False
                        else: 
                            sponsor += (" " + line)

            # link to the (local) pdf
            resolution_text = '<a href="' + resolution_pdf + '">' + resolution + '</a>' 

        # remove titles, extra spaces
        sponsor = sponsor.replace("  ", " ").strip()
        sponsor = sponsor.replace(", City Councilor","")
        sponsor = sponsor.replace(", Council President","")
        sponsor = sponsor.replace(", Council Vice President","")

        # write the resolution
        #html.write('<tr><td>' + resolution_text + '</td><td width="50">&nbsp;</td><td>' + sponsor + '</td><td>' + description + '</td></tr>\n')
        html.write('<tr><td colspan=2>' + resolution_text + '</td><td>' + sponsor + '</td><td>' + description + '</td></tr>\n')


        for yt_id in sorted_dict[resolution]:

            title = video_data[yt_id]["title"]

            dir = video_data[yt_id]["upload_date"] + '_' + yt_id
            htmlfile = os.path.join(dir,dir+'.html')

            html.write('<tr><td></td><td colspan=3><a href="' + htmlfile + '">' + title + '</a></td></tr>\n')



    html.write('</table>\n')
    html.close()

def make_sitemap():

    files = glob.glob("*/*.html")

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

    sitemap_name = save_as.split("/")[-1]
    dest_path = "/".join(save_as.split("/")[:-1])

    sitemap_name = f"{sitemap_name}.xml"

    save_as = f"{dest_path}/{sitemap_name}"

    # create sitemap path if not existed
    if not os.path.exists(f"{dest_path}/"):
        os.makedirs(f"{dest_path}/")

    tree = cElementTree.ElementTree(root_node)
    tree.write(save_as, encoding='utf-8', xml_declaration=True)

    return sitemap_name

def do_one(yt_id,skip_translation=False, force=False, do_scrape=True, do_extras=True):
    t0 = datetime.datetime.utcnow()
    fix_common_errors.fix_common_errors(yt_id=yt_id)
    make_heatmap(yt_id, force=force)
    srt2html(yt_id, skip_translation=skip_translation, force=force)
    # make the top level page with links to all transcripts
    if do_extras:
        make_index()
        make_resolution_tracker(do_scrape=do_scrape)
        make_sitemap()
    time_elapsed = (datetime.datetime.utcnow()-t0).total_seconds()
    print("Done with " + yt_id + " in " + str(time_elapsed) + " seconds")

def do_all(skip_translation=False, force=False):

    files = glob.glob("*/20??-??-??_???????????.srt")
    # on the first one only, scrape the city website for new resolutions
    do_scrape=True

    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]

        # on the last one only, remake the index page, resolution tracker, and sitemap
        do_extras = (file == files[-1])
        try:
            do_one(yt_id, skip_translation=skip_translation, force=force, do_scrape=do_scrape, do_extras=do_extras)
            # on the first one only, scrape the city website for new resolutions
            do_scrape=False
        except Exception as error:
            print("Failed on " + yt_id)
            print(error)

def make_heatmap(yt_id, force=False):

    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)
    addresses = []

    srtfilename = glob.glob('*'+yt_id+'*/20??-??-??_' + yt_id + '.srt')[0]
    htmlfilename = os.path.splitext(srtfilename)[0] + '.html'
    dir = os.path.dirname(srtfilename)

    # read in the speaker mappings
    jsonfile = os.path.join(dir,'speaker_ids.json')
    if not os.path.exists(jsonfile): return
    with open(jsonfile, 'r') as fp:
        speaker_ids = json.load(fp)

    for speaker in list(speaker_ids.values()):
        if speaker in directory.keys():
            if directory[speaker] != "":
                addresses.append(directory[speaker])
        elif "SPEAKER_" in speaker:
            pass
        else:
            print("No address found for " + speaker)

    if len(addresses) > 0:
        htmlname = os.path.join(dir,'heatmap.html')
        if not os.path.exists(htmlname) or force:
            heatmap.heatmap(addresses, htmlname=htmlname)
    else:
        print("No matching addresses; skipping heatmap")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Transcribe YouTube videos')
    parser.add_argument('-i','--yt_id', dest='yt_id', default=None, help="id to just do one")
    parser.add_argument('-s','--skip_translation', dest='skip_translation', action='store_true', default=False, help="Only do english transcript")
    parser.add_argument('-f','--force', dest='force', action='store_true', default=False, help="Force regeneration of html")

    opt = parser.parse_args()
    utils.update_all()

    if opt.yt_id != None:
        do_one(opt.yt_id, skip_translation=opt.skip_translation, force=opt.force)
    else:
        do_all(skip_translation=opt.skip_translation, force=opt.force)

    supercut.do_all_councilors(useGPT=False)
