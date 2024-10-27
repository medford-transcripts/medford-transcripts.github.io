import datetime, time, os
import ipdb
from wordcloud import WordCloud
import json,glob
from googletrans import Translator, constants

def finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop, eshtml=None):
    # new speaker; wrap up and start new
    if text != "":
        html.write('    <a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
        html.write("[" + speaker + "]</a>: " + text + "<br><br>\n\n")

        if eshtml != None:
            translator = Translator()
            translation = translator.translate(text, dest="es")
            eshtml.write('    <a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
            eshtml.write("[" + speaker + "]</a>: " + translation.text + "<br><br>\n\n")

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

    councilors = ["Lungo-Koehn", # Mayor
    "Bears","Collins","Callahan","Lazzaro","Leming","Scarpelli","Tseng", # City Councilors
    "Branley","Graham","Intoppa","Olapade","Reinfeld","Ruseau", # School committee
    "Jessica"] # important guest speakers

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

    if last_update > last_changed: return
    #######################################################################################################

    # output custom html with links to corresponding parts of the youtube video
    html = open(htmlfilename, 'w', encoding="utf-8")
    html.write('<!DOCTYPE html>\n')
    html.write('<html lang="en">\n')
    html.write('  <head>\n')
    html.write('    <meta charset="UTF-8">\n')
    html.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
    html.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
    html.write('   <title>Transcript for ' + yt_id + '</title>\n')
    html.write('  </head>\n')
    html.write('  <body>\n')
    html.write('  <table>\n')

    eshtml = open(eshtmlfilename, 'w', encoding="utf-8")


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
                this_text = line.split(":")[-1]

                # replace automated speaker tag with speaker ID
                if this_speaker in speaker_ids.keys():
                    this_speaker = speaker_ids[this_speaker]

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
                    html.write('        <a href="' + imagename + '"><img src="' + imagename + '" height=150></img></a><br>\n')
            html.write('      </td>\n')
        html.write('    </tr>\n')
    html.write('  </table>\n')

    html.write('  </body>\n')
    html.write('</html>\n')
    html.close()
    eshtml.close()

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
        if htmlfile.endswith("es.html"): continue
        date = htmlfile.split('_')[0]
        yt_id = '_'.join(htmlfile.split('_')[1:]).split('\\')[0]

        eshtmlfile = os.path.splitext(htmlfile)[0]+'.es.html'
        url = "https://youtu.be/" + yt_id 

        download = True
        if yt_id in video_data.keys():
            if "title" in video_data[yt_id].keys():
                title = video_data[yt_id]["title"]
                channel = video_data[yt_id]["channel"]
                download = False

        if download:
            info = yt_dlp.YoutubeDL().extract_info(url, download=False) 
            title = info["title"]
            channel = info["channel"]
            video_data[yt_id] = {}
            video_data[yt_id]["title"] = title
            video_data[yt_id]["channel"] = channel

        lines.append('<tr><td>' + date + '</td><td><a href="' + url + '">[Video]</a></td><td>' + channel + '</td><td>'+title+'</td><td><a href="' + htmlfile + '">English</a></td><td><a href="' + eshtmlfile + '">Spanish</a></td></tr>\n')

    with open(jsonfile, "w") as fp:
        json.dump(video_data, fp, indent=4)

    lines.sort(reverse=True)
    index_page = open('index.html', 'w', encoding="utf-8")
    index_page.write("<table border=1>\n")
    index_page.write("<tr><td><center>Upload Date</center></td><td><center>YouTube</center></td><td><center>Channel</center></td><td><center>Title</center></td><td colspan=2><center>Transcript</center></td></tr>\n")
    for line in lines:
        index_page.write(line)
    index_page.write("</table>")
    index_page.close()

if __name__ == "__main__":

    files = glob.glob("*/*.srt")
    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        dir = os.path.dirname(file)
        srtfilename = os.path.join(dir,dir) + '.srt'
        if srtfilename != file: continue
        htmlfilename = os.path.join(dir,dir) + '.html'

        if os.path.exists(srtfilename): 
            srt2html(yt_id)

    # make the top level page with links to all transcripts
    make_index()

