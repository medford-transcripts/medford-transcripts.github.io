import datetime, time, os
import ipdb
import json,glob
from wordcloud import WordCloud
import yt_dlp 
from yt_dlp.utils import download_range_func
import ffmpeg
import subprocess

import srt2html
import create_subtitles

# openAI has conflicting requirements with googletrans :(
# pip install googletrans-py instead
from openai import OpenAI
with open('openai_key.txt') as f: api_key = f.readline().strip()
client = OpenAI(api_key=api_key)

def supercut(speaker):

    t0 = datetime.datetime(1900,1,1)    
    excerpts = []
    files = glob.glob("*/20??-??-??_???????????.srt")
    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        dir = os.path.dirname(file)
        srtfilename = os.path.join(dir,dir) + '.srt'
        if srtfilename != file: continue

        jsonfile = os.path.join(dir,'speaker_ids.json')
        if os.path.exists(jsonfile):
            with open(jsonfile, 'r') as fp:
                speaker_ids = json.load(fp)
        else: speaker_ids = {}

        # requested speaker not in this transcript; skip file
        if speaker not in speaker_ids.values(): continue

        # extract text from this transcript
        with open(srtfilename, 'r', encoding="utf-8") as f:

            # Read each line in the file
            for line in f:
                line.strip()

                if "-->" in line:
                    # timestamp
                    start_string = line.split()[0]
                    stop_string = line.split()[-1]

                    # convert timestamp to seconds elapsed
                    start_time = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
                    stop_time = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()

                elif "[" in line:
                    # text
                    this_speaker = line.split()[0].split("[")[-1].split("]")[0]
                    text = ":".join(line.split(":")[1:])

                    if speaker_ids[this_speaker] == speaker:
                        excerpts.append({
                            "yt_id" : yt_id,
                            "start": start_time,
                            "stop" : stop_time,
                            "text" : text,
                            })
                    
                else: continue

    messages = [ {"role": "system", "content": "You are a video editor."} ]
    text = "You are a video editor. Select a list of quotes in JSON format that, when read together, is the script for a campaign ad for a local candidate using only their complete quotes (separated by new lines) from the following list:\n"

    #office = "city council"
    #values = ["engagement","passion","competence","critical thinking","creativity","intelligence","communication","compassion","inspirational","integrity","honesty","visionary","fiscal responsibility","respect"]
    #priorities = ["education","infrastructure","economic development","jobs","equity","equality","climate change","economy","veterans","health","affordable housing","public safety"]
    #text = "Based on their quotes below, on a scale from 1 to 10 " + \
    #    "(10 being best) rate the candidate's suitability for " + office + \
    #    " based on each of the following values: " + ",".join(values) + \
    #    ". Also rate them based on the following priorities: " + ",".join(priorities) + \
    #    ". 'not enough information' is a valid ranking. Explain each score in 1-2 sentences."

    text = ""
    alltime = 0.0
    htmlfilename = os.path.join("electeds",speaker + '.html')
    html = open(htmlfilename, 'w', encoding="utf-8")

    imagename = speaker + '.wordcloud.png'
    html.write('        <a href="' + imagename + '"><img src="' + imagename + '" alt="word cloud for ' + speaker + '" height=150></img></a><br>\n')

    for excerpt in excerpts:
        html.write('    <a href="https://youtu.be/' + excerpt["yt_id"] + '&t=' + str(excerpt["start"]) + 's">')
        html.write("[" + speaker + "]</a>: " + excerpt["text"].strip() + "<br><br>\n\n")
        text = text + "\n" + excerpt["text"]
        alltime += (excerpt["stop"] - excerpt["start"])

    if text != "":
        wordcloud = WordCloud(max_font_size=40).generate(text)
        wordcloud.to_file("electeds/" + imagename)

    html.close()
    messages = [({"role": "user", "content": text})]
    print(str(alltime/3600) + " hours of speech")

    #return text
    #ipdb.set_trace()

    model = "gpt-3.5-turbo"
    #model = "gpt-4o-mini"
    ipdb.set_trace()
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content.strip()

def do_all_councilors():

    councilors = srt2html.get_councilors()

    for councilor in councilors:
        print(councilor)
        excerpts = supercut(councilor)
        ipdb.set_trace()

def download_clip(yt_id, start_time, stop_time, output_name=None):

    url = "https://www.youtube.com/watch?v=" + yt_id

    yt_opts = {
        'verbose': True,
        'download_ranges': download_range_func(None,[(start_time, stop_time)]),
        'force_keyframes_at_cuts': True,
        "format": "bestvideo+bestaudio/best", 
#        "format":"webm",
        "outtmpl": os.path.join("clips","og_" + output_name),
    }

    ipdb.set_trace()

    with yt_dlp.YoutubeDL(yt_opts) as ydl:
        ydl.download(url)

    ipdb.set_trace()

    og_clipname = glob.glob("clips/og_" + output_name + '*')[0]

    video_data = create_subtitles.get_video_data()
    source = video_data[yt_id]["date"] + " " + video_data[yt_id]["title"]

    # if the line is too long, add a line break at a space nearest to the midpoint
    if len(source) > 80:
        source.split
        halfndx = round(len(source)/2)
        bestdiff = len(source)
        for n in range(len(source)):
            if source[n] == " ":
                diff = abs(n - halfndx)
                if diff < bestdiff:
                    bestdiff = diff
                    bestndx = n
        source = source[:bestndx] + "\n" + source[bestndx:]

    # overlay date and title of source clip, and re-encode to webm
    command = ["ffmpeg", 
               "-i", og_clipname,
               "-vf", f"drawtext=fontfile=fonts/tnr.ttf:text='{source}':fontcolor=white:fontsize=(h/30):x=(w-text_w)/2:y=10:borderw=3:bordercolor=#000000", 
               "-y", 
               "-c:v", "libvpx-vp9", 
               "-crf", "18",
               "-c:a", "libopus",
               os.path.join("clips",output_name)+'.webm']
    subprocess.run(command)

def download_clip_old(yt_id, start_time, stop_time, output_name=None):

    url = "https://www.youtube.com/watch?v=" + yt_id

    if output_name == None:
        output_name = yt_id + str(round(start_time)).zfill(5) + '_' + str(round(stop_time)).zfill(5)

    # pad by 10 seconds (and trim later) to avoid bad video
    if start_time < 10:
        start_time_ext = 0
    else: 
        start_time_ext = start_time - 10
    start_pad = start_time - start_time_ext + 6
    stop_time_ext = stop_time + 10

    # this allows clipping to fractions of a second
    start_string = (datetime.datetime(2000,1,1) + datetime.timedelta(seconds=start_time_ext)).strftime("%H:%M:%S.%f")[:-3]
    stop_string = (datetime.datetime(2000,1,1) + datetime.timedelta(seconds=stop_time_ext)).strftime("%H:%M:%S.%f")[:-3]

    # download clip
    ffmpeg_args = {
        "ffmpeg_i": ["-ss", start_string, "-to", stop_string]
    }

    opts = {
      "format": "bestvideo+bestaudio/best", 
      "external_downloader": "ffmpeg",
      "external_downloader_args": ffmpeg_args,
      "quiet": True,
      "outtmpl": os.path.join("clips","pad_" + output_name),
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(url)

    # find the extension that was downloaded
    pad_clipname = glob.glob("clips/pad_" + output_name + '*')[0]
    ext = os.path.splitext(pad_clipname)[1]

    video_data = create_subtitles.get_video_data()
    source = video_data[yt_id]["date"] + " " + video_data[yt_id]["title"]

    # if the line is too long, add a line break at a space nearest to the midpoint
    if len(source) > 80:
        source.split
        halfndx = round(len(source)/2)
        bestdiff = len(source)
        for n in range(len(source)):
            if source[n] == " ":
                diff = abs(n - halfndx)
                if diff < bestdiff:
                    bestdiff = diff
                    bestndx = n
        source = source[:bestndx] + "\n" + source[bestndx:]
        #print(source)
        #ipdb.set_trace()

    # trim the clip to original length, overlay date and title of source clip, and re-encode to webm
    command = ["ffmpeg", 
               "-ss", str(start_pad-1), 
               "-to", str(start_pad+stop_time-start_time+2), 
               "-i", pad_clipname,
               "-vf", f"drawtext=fontfile=fonts/tnr.ttf:text='{source}':fontcolor=white:fontsize=(h/30):x=(w-text_w)/2:y=10:borderw=3:bordercolor=#000000", 
               "-y", 
               "-c:v", "libvpx-vp9", 
               "-crf", "18",
               "-c:a", "libopus",
               os.path.join("clips",output_name)+'.webm']
    subprocess.run(command)

    return

def supercut_by_keyword_and_speaker(keyword, speaker):

    keyword_filename = keyword.replace(" ","")
    keyword_filename = keyword_filename.replace(".","")
    keyword_filename = keyword_filename.replace(",","")
    keyword_filename = keyword_filename.replace("'","")

    t0 = datetime.datetime(1900,1,1)   
    files = glob.glob("*/20??-??-??_???????????.srt")
    video_data = create_subtitles.get_video_data()

    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        dir = os.path.dirname(file)
        srtfilename = os.path.join(dir,dir) + '.srt'
        if srtfilename != file: continue

        jsonfile = os.path.join(dir,'speaker_ids.json')
        if os.path.exists(jsonfile):
            with open(jsonfile, 'r') as fp:
                speaker_ids = json.load(fp)
        else: continue

        # requested speaker not in this transcript; skip file
        if speaker not in speaker_ids.values() and speaker != 'any': continue

        # extract text from this transcript
        with open(srtfilename, 'r', encoding="utf-8") as f:

            # Read each line in the file
            for line in f:
                line.strip()

                if "-->" in line:
                    # timestamp
                    start_string = line.split()[0]
                    stop_string = line.split()[-1]

                    # convert timestamp to seconds elapsed
                    start_time = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
                    stop_time = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()


                elif "[" in line:
                    # text
                    this_speaker = line.split()[0].split("[")[-1].split("]")[0]
                    text = ":".join(line.split(":")[1:])

                    #if keyword in line.upper(): ipdb.set_trace()

                    if ((speaker_ids[this_speaker] == speaker) or speaker == "any") and (keyword.upper() in line.upper()):
                        output_name = speaker + '_' + keyword_filename + '_' + video_data[yt_id]["date"] + '_' + yt_id + '_' + str(round(start_time)).zfill(5) + '_' + str(round(stop_time)).zfill(5)
                        clipname = glob.glob(os.path.join("clips",output_name + "*webm"))
                        if len(clipname) == 0:
                            download_clip(yt_id, start_time, stop_time, output_name=output_name)
                    
                else: continue

    # merge videos
    output_name = os.path.join("supercuts",speaker + '_' + keyword_filename + '.webm') 
    concatenate_clips(os.path.join("clips",speaker + '_' + keyword_filename + '_20??-??-??_???????????_*_*.webm'), output_name)
    mkhtml(output_name)
 
def concatenate_clips(path, output_name):

    # make a list of clips to concatenate
    files = glob.glob(path)
    with open('concat.txt','w') as fp:
        for file in files:       
            fp.write('file ' + file.replace('\\','/')  + '\n')

    # not sure of the syntax for the native python package; use subprocess

    # no need to re-encode; that's already been done
    #command = ["ffmpeg","-y", "-f", "concat", "-i", "concat.txt","-c:v", "libvpx-vp9","-c:a", "libopus", output_name]

    # concatenate clips
    command = ["ffmpeg","-y", "-f", "concat","-i", "concat.txt", "-crf", "18", output_name]
    subprocess.run(command)

# make a page with the video embedded
def mkhtml(video_name):
    with open(os.path.splitext(video_name)[0] + '.html','w') as fp:
        fp.write('<video width="704" height="480" controls><source src="' + os.path.basename(video_name) + '" type="video/webm"></video>')


if __name__ == "__main__":

    ''' The goal for this code is to find the most consequential exerpts
    for a given person, topic, or meeting (using chatGPT?) across all transcripts, then extract 
    the corresponding clips from the transcribed videos and splice 
    them together into a short (< 5 minute) supercut. 

    This does everything but identify the most consequential excerpts, but can compile late-night style montages by identifying common keywords. '''
    #do_all_councilors()
    #ipdb.set_trace()


    #speaker = "Scarpelli"
    #keyword = "transparency"

    speaker = "Marks"
    keyword = "Thank you, Mr. President"

    speaker = "any"
    keyword = "yeoman's work"
    #keyword = "august body"
    #keyword = "slippery slope"


    keyword_filename = keyword.replace(" ","")
    keyword_filename = keyword_filename.replace(".","")
    keyword_filename = keyword_filename.replace(",","")
    keyword_filename = keyword_filename.replace("'","")

    supercut_by_keyword_and_speaker(keyword, speaker)
    ipdb.set_trace()

    output_name = os.path.join("supercuts",speaker + '_' + keyword_filename + '.webm') 
    concatenate_clips("clips/"+speaker + '_' + keyword_filename + '_20??-??-??_???????????_*_*.webm', output_name)
    mkhtml(output_name)

    #


    # merge videos






