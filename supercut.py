import datetime, time, os
import ipdb
import json,glob
from wordcloud import WordCloud
import yt_dlp 
import ffmpeg
import subprocess

import srt2html

# openAI has conflicting requirements with googletrans :(
#from openai import OpenAI
#with open('openai_key.txt') as f: api_key = f.readline().strip()
#client = OpenAI(api_key=api_key)

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

                    #print(start_time)
                    #print(stop_time)

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

    messages = [ {"role": "system", "content": "You are an intelligent assistant."} ]
    text = "Extract 2-4 minutes of the most consequential quotes from the following excerpts: "

    office = "city council"
    values = ["engagement","passion","competence","critical thinking","creativity","intelligence","communication","compassion","inspirational","integrity","honesty","visionary","fiscal responsibility","respect"]
    priorities = ["education","infrastructure","economic development","jobs","equity","equality","climate change","economy","veterans","health","affordable housing","public safety"]
    text = "Based on their quotes below, on a scale from 1 to 10 " + \
        "(10 being best) rate the candidate's suitability for " + office + \
        " based on each of the following values: " + ",".join(values) + \
        ". Also rate them based on the following priorities: " + ",".join(priorities) + \
        ". 'not enough information' is a valid ranking. Explain each score in 1-2 sentences."

    text = ""
    alltime = 0.0
    htmlfilename = os.path.join("electeds",speaker + '.html')
    html = open(htmlfilename, 'w', encoding="utf-8")

    imagename = speaker + '.wordcloud.png'
    html.write('        <a href="' + imagename + '"><img src="' + imagename + '" alt="word cloud for ' + speaker + '" height=150></img></a><br>\n')

    for excerpt in excerpts:
        html.write('    <a href="https://youtu.be/' + excerpt["yt_id"] + '&t=' + str(excerpt["start"]) + 's">')
        html.write("[" + speaker + "]</a>: " + excerpt["text"].strip() + "<br><br>\n\n")
        text = text + " " + excerpt["text"]
        alltime += (excerpt["stop"] - excerpt["start"])

    if text != "":
        wordcloud = WordCloud(max_font_size=40).generate(text)
        wordcloud.to_file("electeds/" + imagename)


    #if alltime == 0.0: ipdb.set_trace()

    html.close()
    messages = [({"role": "user", "content": text})]
    print(str(alltime/3600) + " hours of speech")

    return text
    ipdb.set_trace()

    model = "gpt-3.5-turbo"
    #model = "gpt-4o-mini"
    #response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content.strip()

def do_all_councilors():

    councilors = srt2html.get_councilors()

    for councilor in councilors:
        print(councilor)
        excerpts = supercut(councilor)
        #ipdb.set_trace()

def download_clip(yt_id, start_time, stop_time, output_name=None):

    url = "https://www.youtube.com/watch?v=" + yt_id

    if output_name == None:
        output_name = yt_id + str(round(start_time)).zfill(5) + '_' + str(round(stop_time)).zfill(5)

    # pad by 10 seconds to avoid bad video
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

    # can/should trimming, converting to webm be combined?

    # trim the padded clip; this eliminates artifacts from downloading clips
    # ffmpeg -i original.mp3 -ss 0 -to 300 trimmed.mp3
    command = ["ffmpeg", "-ss", str(start_pad-1), "-to", str(start_pad+stop_time-start_time+2), "-y", "-i", pad_clipname, os.path.join("clips",output_name)+ext,"-c","copy"]
    subprocess.run(command)

    # if not webm, convert to webm (and re-encode) so the clips can be concatenated later
    if ext != '.webm':
        command = ["ffmpeg", "-i", os.path.join("clips",output_name)+ext,"-c:v", "libvpx-vp9", "-c:a", "libopus",os.path.join("clips",output_name)+'.webm' ]
        subprocess.run(command)

    return

def supercut_by_keyword_and_speaker(keyword, speaker):

    t0 = datetime.datetime(1900,1,1)   
    nclips = 0
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
        else: continue

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

                    if (speaker_ids[this_speaker] == speaker) and (keyword in line):
                        nclips += 1
                        output_name = speaker + '_' + keyword + '_' + str(nclips).zfill(3) + '_' + yt_id + '_' + str(round(start_time)).zfill(5) + '_' + str(round(stop_time)).zfill(5)
                        clipname = glob.glob(os.path.join("clips",output_name + "*webm"))
                        if len(clipname) == 0:
                            download_clip(yt_id, start_time, stop_time, output_name=output_name)
                    
                else: continue

    # merge videos
    output_name = os.path.join("supercuts",speaker + '_' + keyword + '.webm') 
    concatenate_clips(os.path.join("clips",speaker + '_' + keyword + '_???_???????????_*_*.webm'), output_name)
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
    command = ["ffmpeg","-y", "-f", "concat","-i", "concat.txt", output_name]
    subprocess.run(command)

# make a page with the video embedded
def mkhtml(video_name):
    with open(os.path.splitext(video_name)[0] + '.html','w') as fp:
        fp.write('<video width="704" height="480" controls><source src="' + os.path.basename(video_name) + '" type="video/webm"></video>')


if __name__ == "__main__":

    ''' The goal for this code is to find the most consequential exerpts
    for a given person (using chatGPT?) across all transcripts, then extract 
    the corresponding clips (yt_dlp?) from the transcribed videos and splice 
    them together into a 2-4 minute supercut. 

    This is a very early draft that does a few of these things...
    '''

    speaker = "Scarpelli"
    keyword = "transparency"

    supercut_by_keyword_and_speaker(keyword, speaker)
    ipdb.set_trace()

    output_name = os.path.join("supercuts",speaker + '_' + keyword + '.webm') 
    concatenate_clips("clips/"+speaker + '_' + keyword + '_???_???????????_*_*.webm', output_name)
    mkhtml(output_name)

    #


    # merge videos




#    do_all_councilors()


