import datetime, time, os
import ipdb
from wordcloud import WordCloud
import json,glob
from googletrans import Translator, constants
import shutil
import os
import gzip
from xml.etree import cElementTree
import dateutil.parser as dparser
import re
import fix_common_errors
import argparse

def finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=None, languages={"en" : "English"}):

    if text == '': return

    translator = Translator()

    for language in languages.keys():
        if language == 'en':
            htmlfilename = basename + '.html'
            html = open(htmlfilename, 'a', encoding="utf-8")
            html.write("    <p>[" + speaker + "]</a>: " + htmltext + "</p>\n\n")
            html.close()
        else: 
            htmlfilename = basename + '.' + language + '.html'
            translation = translator.translate(text, dest=language)
            html = open(htmlfilename, 'a', encoding="utf-8")
            html.write('    <p><a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
            html.write("[" + speaker + "]</a>: " + translation.text + "</p>\n\n")
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

def get_councilors(file="councilors.txt"):
    councilors = []
    with open(file,'r') as fp:
        for line in fp:
            entries = line.split("#")[0].strip().split(',')
            for entry in entries:
                if entry != '':
                    councilors.append(entry.strip())
    return list(set(councilors))


def srt2html(yt_id,skip_translation=False):

    srtfilename = glob.glob('*'+yt_id+'*/20??-??-??_' + yt_id + '.srt')[0]
    htmlfilename = os.path.splitext(srtfilename)[0] + '.html'
    dir = os.path.dirname(srtfilename)

    last_changed = os.path.getmtime(srtfilename)

    # we will do some analytics on these people
    councilors = get_councilors()

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
    #last_update = datetime.datetime(2024,11,4,2,35).timestamp() 
    #last_update = datetime.datetime(2024,12,12,0,0).timestamp() 
    #last_update = 0.0 # uncomment to remake them all (for changes to the template)
    if (last_update > last_changed) and os.path.exists(htmlfilename): return
    #######################################################################################################

    basename = os.path.splitext(srtfilename)[0]
    filebasename = os.path.basename(basename)

    # top 10 languages used in MA from
    # https://www.mass.gov/doc/appendix-f-language-audience-guidesdoc/download
    # english, spanish, brazilian portuguese, chinese, haitian creole, vietnamese, khmer, (cape verdean), russian, arabic, korean
    # cape verdean is not supported by googletrans

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
            try:
                translation = translator.translate(text, dest=language)
                text = translation.text
            except:
                pass
        html.write('    <meta name="description" content="' + text + '">\n')

        text = title    
        if language != 'en':
            translation = translator.translate(text, dest=language)
            text = translation.text
        html.write('    <title>' + text + '</title>\n')

        html.write('    <link rel="canonical" href="https://medford-transcripts.github.io/' + htmlfilename + '" />\n')
        html.write('  </head>\n')
        html.write('  <body>\n')

        text = 'AI-generated transcript of ' + video_title
        if language != 'en':
            translation = translator.translate(text, dest=language)
            text = translation.text
        html.write('  <h1>' + text + '</h1>\n')

        html.write(links_to_languages + '<br><br>\n')

        text = 'Back to all transcripts'
        if language != 'en':
            translation = translator.translate(text, dest=language)
            text = translation.text
        html.write('    <a href="../index.html">' + text + '</a><br><br>\n')
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
                    link = ' <a href="https://youtu.be/' + yt_id + '&t=' + str(this_start) + 's">' + tmp_text[0] + '</a> '
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

                    # links mid text for more precise timestamps
                    #tmp_text = this_text.split()
                    #link = ' <a href="https://youtu.be/' + yt_id + '&t=' + str(this_start) + 's">' + tmp_text[0] + '</a> '
                    #tmp_text[0] = link
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
                    wordcloud = WordCloud(max_font_size=40).generate(speaker_stats[speaker]["all_words"])
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
            translation = translator.translate(text, dest=language)
            text = translation.text

        html = open(htmlfilename, 'a', encoding="utf-8")
        html.write('  <br><br><a href="../index.html">' + text + '</a><br><br>\n')
        html.write('  </body>\n')
        html.write('</html>\n')
        html.close()

    if yt_id not in video_data.keys(): video_data[yt_id] = {}
    video_data[yt_id]["last_update"] = time.time()

    update_video_json(video_data)

def update_video_json(video_data):

    jsonfile = 'video_data.json'

    while os.path.exists('video_data.lock'):
        time.sleep(1)

    with open("video_data.lock", "w") as file:
        file.write("lock")

    with open(jsonfile, "w") as fp:
        json.dump(video_data, fp, indent=4)

    os.remove("video_data.lock")


def make_index():

    import yt_dlp
    # read in the speaker mappings
    jsonfile = 'video_data.json'
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else:
        video_data = {}

    htmlfiles = glob.glob('*/20??-??-??_???????????.html')
    lines = []
    for htmlfile in htmlfiles:
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

        # first priority, the date field of video_data.json
        # next, date parsed from title
        # next, upload date
        if "date" in video_data[yt_id].keys():
            # you can hand edit the date in the video_data.json file for ones that fail to parse
            date = video_data[yt_id]["date"]
        else:
            try:
                create_date = dparser.parse(title,fuzzy=True)
                upload_date = datetime.datetime.strptime(date,'%Y-%m-%d')

                # sometimes the parser guesses too much. It can't be later the upload date
                if upload_date > create_date:
                    date = create_date.strftime("%Y-%m-%d")
            except ValueError:
                # default to the upload date
                #print('No parsable date in title of "' + title + '"; using upload date')
                pass

        duration_string = time.strftime('%H:%M:%S', time.gmtime(duration))

        # one row in the html table
        lines.append('      <tr>' +\
            '<td>' + date + '</td>' +\
            '<td><a href="' + url + '">[' + duration_string + ']</a></td>'+\
            '<td><a href="' + htmlfile +'">' + title + '</a></td>'+\
            '<td>' + channel + '</td>'+\
            '<td><a href="' + srtfile + '">SRT</a></td>'+\
            '<td><a href="' + speaker_id_file + '">JSON</a></td>'+\
            '</tr>\n')

    update_video_json(video_data)

    lines.sort(reverse=True)
    shutil.copy("header.html", "index.html")
    index_page = open('index.html', 'a', encoding="utf-8")
    index_page.write("    <table border=1>\n")
    # table header
    index_page.write("      <tr><td><center>Date</center></td><td><center>Duration</center></td><td><center>Title (click for transcript)</center></td><td><center>Channel</center></td><td colspan=2><center>Raw files</center></td></tr>\n")
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

def do_one(yt_id,skip_translation=False):
    fix_common_errors.fix_common_errors(yt_id=yt_id)
    srt2html(yt_id, skip_translation=skip_translation)
    # make the top level page with links to all transcripts
    make_index()
    make_sitemap()

def do_all(skip_translation=False):
    #fix_common_errors.fix_common_errors()
    files = glob.glob("*/20??-??-??_???????????.srt")
    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        try:
            do_one(yt_id, skip_translation=skip_translation)
            #srt2html(yt_id, skip_translation=skip_translation)
        except Exception as error:
            print("Failed on " + yt_id)
            print(error)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Transcribe YouTube videos')
    parser.add_argument('-i','--yt_id', dest='yt_id', default=None, help="id to just do one")
    parser.add_argument('-s','--skip_translation', dest='skip_translation', action='store_true', default=False, help="Only do english transcript")

    opt = parser.parse_args()

    if opt.yt_id != None:
        do_one(opt.yt_id, skip_translation=opt.skip_translation)
    else:
        do_all(skip_translation=opt.skip_translation)
