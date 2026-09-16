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

#from wordcloud import WordCloud

# dependency hell... 
#pip install googletrans
#pip install httpx==0.28.1 --ignore-requires-python
#pip install openai
from googletrans import Translator, constants

import yt_dlp

# imports from this repo
import utils, supercut, fix_common_errors, heatmap, scrape
import make_committee_pages
from urllib.parse import quote
from html import escape
from site_url import site_url

# ---------------------------------------------------------------------------
# TRANSLATIONS ARE OFF.
#
# googletrans 3.4.0 is broken: half the target languages raise
# AttributeError("'NoneType' object has no attribute 'send'") and the other
# half silently return the input unchanged. Either way the generator was
# writing ENGLISH into pages served as lang="ar" / "km" / "ru" -- i.e. ~20,000
# near-duplicate pages, the exact pattern Google treats as scaled content
# abuse, on a domain that is already struggling to stay indexed.
#
# The translated pages have also been removed from git tracking. They are NOT
# deleted -- they are still on disk and still in history at
#     01245267f2de2472f2563765052468ad376ca6bc
# See the recovery banner at the top of plan.txt.
#
# Translations DID work roughly a year ago, so older pages are genuinely
# translated and are the ones worth restoring first. The intended path forward
# is to translate the Phase 8 SUMMARIES (short, cheap, spot-checkable) rather
# than raw transcripts.
#
# Set this back to False only after replacing googletrans AND adding a check
# that the returned text actually differs from the input -- the silent failure
# mode raises nothing, so exception logging alone will not catch it.
TRANSLATIONS_DISABLED = True

# file suffixes of the retired translated pages, used to keep them out of the
# sitemap even while they remain on disk
TRANSLATED_SUFFIXES = (".es.html", ".pt.html", ".pt-BR.html", ".zh-cn.html",
                       ".ht.html", ".vi.html", ".km.html", ".ru.html",
                       ".ar.html", ".ko.html")


def is_translated_page(path):
    """True for a retired per-language transcript page."""
    return str(path).endswith(TRANSLATED_SUFFIXES)


def translate_text(text, dest="en", cachefile=None):

    if cachefile is not None:
        if not os.path.exists(cachefile):
            translations = {}
        else:
            with open(cachefile, 'r') as fp:
                translations = json.load(fp)
                if text in translations.keys():
                    if dest in translations[text].keys():
                        return translations[text][dest]

    translator = Translator()
    try:
        result = asyncio.run(translator.translate(text, dest=dest))

        ## save the data
        if cachefile is not None:
            if text in translations.keys():
                translations[text][dest] = result.text
            else:
                translations[text] = {dest : result.text}
            with open(cachefile, "w") as fp:
                json.dump(translations, fp, indent=4)

        return result.text
    except Exception as e:
        # This used to be a bare `except: return text`, which silently emitted
        # ENGLISH into a page served as lang="ar"/"km"/"ru". A rate-limited or
        # interrupted run therefore produced pages that looked fine but were
        # not translated at all, with no error anywhere. Still degrade rather
        # than crash a long run, but make it visible and countable.
        global _translation_failures
        _translation_failures += 1
        if _translation_failures <= 5 or _translation_failures % 100 == 0:
            print("  translate_text(-> %s) FAILED (%d so far): %s: %s"
                  % (dest, _translation_failures, type(e).__name__, e))
        return text

_translation_failures = 0


def translation_failure_count():
    return _translation_failures


def timestamp_url(yt_id, start, video_data=None):
    """Timestamped deep link into the source media for this yt_id.

    The platform is implied by the id prefix, exactly as make_html() derives
    on_youtube / on_spotify / on_archive. Returns None when no URL is known.

    finish_speaker() used to hardcode https://youtu.be/<id> for the
    non-English branch, so every translated page of every MCM archive.org
    item carried a dead YouTube link on every timestamp -- 5,517 pages.
    The English branch was correct because it reuses the caller's htmltext.
    """
    entry = (video_data or {}).get(yt_id, {})

    if yt_id[0:6] == "XXXXXX":            # Medford Bytes podcast
        # Our own player (player.html?video=...&t=...) rather than Spotify.
        # The audio URL comes straight from the RSS <enclosure>, so it is
        # fully programmatic -- see update_podcast_audio.py. Spotify episode
        # ids are NOT derivable from the feed, and this also covers the 12
        # episodes whose Spotify URL was lost entirely (plan.txt A19).
        # entry["url"] is kept as the Spotify page, for "listen/subscribe".
        audio = entry.get("audio_url")
        if audio:
            return (site_url("player.html")
                    + "?video=" + quote(audio, safe="")
                    + "&t=" + str(start))
        url = entry.get("url")
        return url + "?t=" + str(start) if url else None

    if yt_id[0:6] == "MCM000":            # MCM archive -> archive.org
        url = entry.get("url")
        return url + "&start=" + str(start) if url else None

    return "https://youtu.be/" + yt_id + "&t=" + str(start) + "s"


def asset_prefix(page_dir):
    """Relative path from a page's directory back to the site root, e.g. "../".

    Assets are linked RELATIVELY (the canonical URL stays absolute, since it
    must be). Relative means a local checkout previews correctly with no
    rewriting, and nothing breaks if the site moves to a custom domain. The
    depth is computed rather than hardcoded so the Phase 3 restructure to
    t/<yt_id>/ (depth 1 -> 2) needs no change here.
    """
    rel = os.path.relpath(".", page_dir or ".").replace(os.sep, "/")
    return "" if rel == "." else rel + "/"


def player_source(yt_id, video_data=None):
    """(kind, src) for the in-page player, or (None, None) if unavailable.

    kind is one of "youtube" | "audio" | "archive"; transcript-player.js maps
    each to a backend behind a common seek/time interface.
    """
    entry = (video_data or {}).get(yt_id, {})

    if yt_id[0:6] == "XXXXXX":
        audio = entry.get("audio_url")
        return ("audio", audio) if audio else (None, None)

    if yt_id[0:6] == "MCM000":
        # archive.org's embed exposes no reliable seek API, so the player is
        # informational there and line clicks fall back to the <a href>.
        url = entry.get("url") or ""
        ident = url.rstrip("/").split("/details/")[-1] if "/details/" in url else ""
        return ("archive", ident) if ident else (None, None)

    return ("youtube", yt_id)


def finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=None, languages={"en" : "English"}, video_data=None):

    if text == '': return

    #ipdb.set_trace()

    for language in languages.keys():
        if language == 'en':
            htmlfilename = basename + '.html'
            html = open(htmlfilename, 'a', encoding="utf-8")
            # data-t drives the in-page synced player (transcript-player.js).
            # The <a href> inside htmltext is deliberately KEPT: without JS,
            # and for crawlers, the line behaves exactly as it always has.
            # (The old markup also emitted a stray unmatched </a> here.)
            html.write('    <p class="line" data-t="' + str(start) + '">['
                       + speaker + ']: ' + htmltext + '</p>\n\n')
            html.close()
        else: 
            htmlfilename = basename + '.' + language + '.html'
            if text != None:
                text = translate_text(text, dest=language, cachefile=basename + '.cache.json')
            else: text = ""
            html = open(htmlfilename, 'a', encoding="utf-8")
            url = timestamp_url(yt_id, start, video_data)
            if url:
                html.write('    <p><a href="' + url + '" rel="nofollow">')
                html.write("[" + speaker + "]</a>: " + text + "</p>\n\n")
            else:
                html.write("    <p>[" + speaker + "]: " + text + "</p>\n\n")
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
    if skip_translation or TRANSLATIONS_DISABLED:
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

    # generate links to other language pages.
    # With only English there is nothing to switch between, so emit nothing
    # rather than a lone self-link.
    links_to_languages = ""
    if len(languages) > 1:
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
            text = translate_text(text, dest=language, cachefile=basename + '.cache.json')

        html.write('    <meta name="description" content="' + text + '">\n')

        text = title    
        if language != 'en':
            text = translate_text(text, dest=language, cachefile=basename + '.cache.json')
        html.write('    <title>' + text + '</title>\n')

        html.write('    <link rel="canonical" href="' + site_url(htmlfilename) + '" />\n')
        html.write('    <link rel="stylesheet" href="' + asset_prefix(dir) + 'transcript-player.css">\n')
        html.write('  </head>\n')
        html.write('  <body>\n')

        text = 'AI-generated transcript of ' + video_title
        if language != 'en':
            text = translate_text(text, dest=language, cachefile=basename + '.cache.json')

        html.write('  <h1>' + text + '</h1>\n')

        # In-page synced player. This is an ENHANCEMENT of the existing page,
        # not a new one: same URL, same canonical, all transcript text still in
        # the DOM, so Ctrl+F, selection and indexing are unaffected. If the
        # mount is absent or JS is off, every line's <a href> still works.
        kind, src = player_source(yt_id, video_data)
        if kind:
            # data-words points at the optional per-word timing sidecar
            # (make_word_times.py). Absent -> the player stays at line level.
            words_attr = ''
            if os.path.exists(os.path.join(dir, filebasename + '.words.json')):
                words_attr = ' data-words="' + filebasename + '.words.json"'
            html.write('  <div id="mt-player" data-kind="' + kind
                       + '" data-src="' + escape(src, quote=True) + '"'
                       + words_attr + '></div>\n')

        if links_to_languages:
            html.write(links_to_languages + '<br><br>\n')

        text = 'Back to all transcripts'
        if language != 'en':
            text = translate_text(text, dest=language, cachefile=basename + '.cache.json')

        html.write('    <a href="../index.html">' + text + '</a><br><br>\n')

        if os.path.exists(os.path.join(dir,"heatmap.html")):
            text = 'Heatmap of speakers'
            if language != 'en':
                text = translate_text(text, dest=language, cachefile=basename + '.cache.json')

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
                    # single source of truth for media links -- the English and
                    # translated paths used to build these separately, drifted
                    # apart, and put dead youtu.be links on 5,669 pages
                    media = timestamp_url(yt_id, this_start, video_data)
                    if media:
                        link = ' <a href="' + media + '" rel="nofollow">' + tmp_text[0] + '</a> '
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
                    finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=htmltext, languages=languages, video_data=video_data)

                    # update to new values
                    start = this_start
                    text = this_text
                    htmltext = this_html_text
                    speaker = this_speaker

                stop = this_stop

            else: continue

    finish_speaker(basename, speaker_stats, text, speaker, yt_id, start, stop, htmltext=htmltext, languages=languages, video_data=video_data)

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

            ## make a word cloud
            #if speaker in councilors:
            #    try:
            #        # if only words are common/excluded, it'll raise a valueError
            #        wordcloud = WordCloud(max_font_size=40).generate(" ".join(speaker_stats[speaker]["all_words"]))
            #        wordcloud.to_file(os.path.join(dir,speaker + '.wordcloud.png'))
            #    except:
            #        pass

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
                    #imagename = present_councilors[idx] + '.wordcloud.png'
                    html.write('        <center>' + present_councilors[idx] + "</center><br>\n")
                    html.write('        total time: ' + str(round(speaker_stats[present_councilors[idx]]["total_time"]/60.0,2)) + ' minutes<br>\n')
                    html.write('        total words: ' + str(speaker_stats[present_councilors[idx]]["total_words"]) + '<br>\n')
                    #html.write('        <a href="' + imagename + '"><img src="' + imagename + '" alt="word cloud for ' + present_councilors[idx] + '" height=150></img></a><br>\n')
            html.write('      </td>\n')
        html.write('    </tr>\n')
    html.write('  </table>\n')

    for language in languages:

        text = "Back to all transcripts"

        if language == 'en':
            htmlfilename = basename + '.html'
        else: 
            htmlfilename = basename + '.' + language + '.html'
            text = translate_text(text, dest=language, cachefile=basename + '.cache.json')

        html = open(htmlfilename, 'a', encoding="utf-8")
        html.write('  <br><br><a href="../index.html">' + text + '</a><br><br>\n')
        # loaded last and deferred: the transcript renders and is readable
        # (and indexable) whether or not this ever runs
        if language == 'en':
            html.write('  <script src="' + asset_prefix(dir) + 'transcript-player.js" defer></script>\n')
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

        index_page.write('<!DOCTYPE HTML>\n')
        index_page.write('<html lang="en-US">\n')
        index_page.write('    <head>\n')
        index_page.write('       <meta charset="UTF-8">\n')
        index_page.write('        <meta name="robots" content="noindex, follow">\n')
        index_page.write('        <meta http-equiv="refresh" content="0; url=' + dir + '.html">\n')
        index_page.write('        <script type="text/javascript">\n')
        index_page.write('            window.location.replace = "' + dir + '.html"\n')
        index_page.write('        </script>\n')
        index_page.write('        <title>Page Redirection</title>\n')
        index_page.write('    </head> index_page.write("<body>\n')
        index_page.write('        If you are not redirected automatically, follow this <a href="' + dir + '.html">link</a>.\n')
        index_page.write('    </body>\n')
        index_page.write('</html>\n')

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

        if "url" in video_data[yt_id].keys():
            url = video_data[yt_id]["url"]
        else:
            url = "https://youtu.be/" + yt_id

        minutes_line = '<td></td>'
        agenda_line = '<td></td>'
        if video_data[yt_id]["meeting_type"] == "CC City Council":
            agenda_file = match_files(title)
            if agenda_file != "":
                agenda_line = '<td><a href="' + agenda_file +'">Agenda</a></td>'

            minutes_file = match_files(title,minutes=True)
            if minutes_file != "":
                minutes_line = '<td><a href="' + minutes_file +'">Minutes</a></td>'

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

    # The per-language transcript copies are retired (TRANSLATIONS_DISABLED)
    # and no longer tracked by git, so they are not published -- keep them out
    # of the sitemap even though the files are still sitting on disk.
    files = [f for f in files if not is_translated_page(f)]

    # create root XML node
    sitemap_root = cElementTree.Element('urlset')
    sitemap_root.attrib['xmlns'] = "http://www.sitemaps.org/schemas/sitemap/0.9"

    # add urls
    for file in files:
        timestamp = datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(os.path.getmtime(file)),'%Y-%m-%dT%H:%M:%SZ') 
        url = site_url(file)
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

    # NOT force: the heatmap depends only on speaker_ids.json + addresses.json,
    # never on the transcript template, so a forced HTML rebuild has no reason
    # to redraw it. And folium stamps a RANDOM element id into every map
    # (map_<32 hex>), so redrawing an unchanged map produces a ~4 KB diff whose
    # coordinate data is byte-identical -- ~8 MB of pure git noise across the
    # 1,935 heatmaps on every full regeneration.
    # To genuinely rebuild them, delete the heatmap.html files first.
    make_heatmap(yt_id, force=False)
    srt2html(yt_id, skip_translation=skip_translation, force=force)
    # make the top level page with links to all transcripts
    if do_extras:
        make_committee_pages.make()
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
