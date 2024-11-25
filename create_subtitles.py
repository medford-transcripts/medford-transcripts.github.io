# requires a "hugging face" token called "hf_token.txt" 
# in the top level directory with permissions for 
# a couple libraries. See requirements here:
# https://huggingface.co/pyannote/speaker-diarization-3.1 

# pip install git+https://github.com/m-bain/whisperx.git
import whisperx

# pip install yt_dlp
import yt_dlp 
# yt_dlp requires ffmpeg in your path (https://www.ffmpeg.org/download.html)

# whisperx dependency, pip will grab this
import torch 

# pip install ipdb
import ipdb
# not required. I'm leaving this here for debugging

# standard libraries 
import datetime, os, glob, argparse, math, sys, subprocess
import json

import srt2html, supercut

##### test hugging face token #####
#from pyannote.audio import Pipeline
#with open('hf_token.txt') as f: token = f.readline()
#pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
#ipdb.set_trace()
###################################

last_update = datetime.datetime(2000,1,1)


def update_priority():
    # read info
    jsonfile = 'video_data.json'
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else: return

    now = datetime.datetime.now()
    priority = []
    halflife = 90.0
    for yt_id in video_data.keys():
        if "view_count" in video_data[yt_id].keys(): 
            views = video_data[yt_id]["view_count"]
        else: views = 0

        if "upload_date" in video_data[yt_id].keys(): 
            age = ((now - datetime.datetime.strptime(video_data[yt_id]["upload_date"],'%Y-%m-%d')).total_seconds()/86400)
        else: age = 0

        if "duration" in video_data[yt_id].keys(): 
            duration = video_data[yt_id]["duration"]
        else: duration = 9e999

        # ad hoc prioritization based on popularity and age

        # prioritize by popularity
        #priority.append(views)

        # prioritize by age (newest first)
        #priority.append(1.0/age)

        # prioritize by age (oldest first)
        #priority.append(age)

        # exponential decay penalizes old videos too strongly or doesn't weight new ones strongly enough
        #priority.append(views*math.exp(-math.log(2.0)*age/halflife))

        # linear decay weakly penalizes old videos
        priority.append((views+100)*100/age)

    # sort video_data by priority (equivalent to np.argsort)
    sort_ndx = reversed(sorted(range(len(priority)), key=priority.__getitem__))
    yt_ids = list(video_data.keys())
    sorted_dict = {}
    for k in sort_ndx:
        sorted_dict[yt_ids[k]] = video_data[yt_ids[k]]
        sorted_dict[yt_ids[k]]["priority"] = priority[k]

    # update video_data
    jsonfile = 'video_data.json'
    with open(jsonfile, "w") as fp:
        json.dump(sorted_dict, fp, indent=4)


# updates video_data.json with info from yt_id
def update_data(yt_id):

    # read info
    jsonfile = 'video_data.json'
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else: video_data = {}

    if yt_id not in video_data.keys(): video_data[yt_id] = {}

    required_keys = ["upload_date","channel","title","duration","view_count"]
    if not all(key in video_data[yt_id].keys() for key in required_keys):
        url = "https://youtu.be/" + yt_id
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(url, download=False)

            video_data[yt_id]["title"] = info["title"]
            video_data[yt_id]["channel"] = info["channel"]
            video_data[yt_id]["duration"] = info["duration"]
            video_data[yt_id]["upload_date"] = datetime.datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")
            video_data[yt_id]["view_count"] = info["view_count"]
            #video_data[yt_id]["last_update"] = 0.0

            # update video_data
            with open(jsonfile, "w") as fp:
                json.dump(video_data, fp, indent=4)

def update_video_data():
    # read info
    jsonfile = 'video_data.json'
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
            for yt_id in video_data.keys():
                update_data(yt_id)

def update_channel_old(channel):

    url = "https://www.youtube.com/" + channel 
    info = yt_dlp.YoutubeDL().extract_info(url, download=False) 

    # the structure of "info" varies depending on how many playlists (live stream, short, etc)
    if "display_id" in info["entries"][0].keys():
        for entry in info["entries"]:
            update_data(entry["display_id"])
    else:
        for playlist in info["entries"]:
            for entry in playlist["entries"]:
                update_data(entry["display_id"])

def update_channel(channel):

    video_data = read_video_data()
    url = "https://www.youtube.com/" + channel 
    info = yt_dlp.YoutubeDL({'extract_flat':'in_playlist'}).extract_info(url, download=False) 

    if "id" in info["entries"][0].keys():
        for entry in info["entries"]:
            if entry["id"] not in video_data.keys():
                try:
                    update_data(entry["id"])
                except:
                    pass
    else:
        for playlist in info["entries"]:
            for entry in playlist["entries"]:
                if entry["id"] not in video_data.keys():
                    try:
                        update_data(entry["id"])
                    except:
                        pass

def update_all(channel_file="channels_to_transcribe.txt", id_file="ids_to_transcribe.txt"):

    # update data for all videos already transcribed
    transcribed_files = glob.glob("*/20??-??-??_???????????.srt")
    for file in transcribed_files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        update_data(yt_id)

    # update data for files in id_file
    if os.path.exists(id_file):
        with open(id_file) as f:
            yt_ids = f.read().splitlines()
        for yt_id in yt_ids:
            update_data(yt_id)

    # update data for all channels
    #channel_file = ""
    if os.path.exists(channel_file):
        with open(channel_file) as f:
            channels = f.read().splitlines()

            # loop through every video on these channels
            for channel in channels: update_channel(channel)


    update_video_data()
    update_priority()

def read_video_data(jsonfile='video_data.json'):
    # read info
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            return json.load(fp)
    else: return {}

'''
 download the Youtube audio at highest quality as an mp3
 yt_id   - youtube ID
''' 
def download_audio(yt_id, dir=None):

    # read info
    video_data = read_video_data()
    if yt_id not in video_data.keys(): video_data[yt_id] = {}

    # construct the name of the file
    if "upload_date" in video_data[yt_id].keys():
        if dir==None:
            dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
        mp3file = os.path.join(dir,dir) +'.mp3'
        mp3file_exists = os.path.exists(mp3file)
    else: mp3file_exists = False

    # if video_data doesn't have all required info, grab it
    required_keys = ["upload_date","channel","title","duration"]
    if all(key not in video_data[yt_id].keys() for key in required_keys) or not mp3file_exists:
        url = "https://youtu.be/" + yt_id
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(url, download=False)

        for format in info["formats"][::-1]:
            if format["resolution"] == "audio only" and format["ext"] == "m4a":
                # this is a temporary, IP-locked URL, storing it doesn't do any good
                audio_url = format["url"]
                
                # store these for later
                video_data[yt_id]["title"] = info["title"]
                video_data[yt_id]["channel"] = info["channel"]
                video_data[yt_id]["duration"] = info["duration"]
                video_data[yt_id]["upload_date"] = datetime.datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")
                break

        # update video_data    
        with open(jsonfile, "w") as fp:
            json.dump(video_data, fp, indent=4)

    if dir==None:
        dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
    mp3file = os.path.join(dir,dir) +'.mp3'

    if not os.path.exists(dir): os.makedirs(dir)
    if os.path.exists(mp3file): return mp3file, video_data[yt_id]["duration"]

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(dir,dir),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
    }

    # download the audio file
    with yt_dlp.YoutubeDL(ydl_opts) as ydl: 
        ydl.download(audio_url)
        return mp3file, video_data[yt_id]["duration"]

def generate_output(result, mp3file):
    subdir = os.path.dirname(mp3file)
    result["language"] = "en"
    output_writer = whisperx.utils.get_writer("srt", subdir)
    output_writer(result, mp3file, {'max_line_width': None,'max_line_count': None,'highlight_words': False})
    return

def transcribe(yt_id, min_speakers=None, max_speakers=None, redo=False, download_only=False):

    t0 = datetime.datetime.utcnow()
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Transcribing " + yt_id)

    mp3file, duration = download_audio(yt_id)
    print("Duration of " + yt_id + " is " + str(duration/60) + " minutes")

    base = os.path.splitext(mp3file)[0]
    subdir = os.path.dirname(mp3file)
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Download of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    if download_only: return False

    # skip files that are already done
    files = glob.glob("*/20??-??-??_" + yt_id + ".srt")
    if len(files) != 0 and not redo: 
        print("Already done with " + yt_id + " (" + files[0] + "). Set redo=True to redo transcription")
        return False

    # whisperX options
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16" # change to "int8" if low on GPU mem (may reduce accuracy)
    else:
        device = "cpu"
        compute_type = "int8"

    batch_size = 16 # reduce if low on GPU mem
    model_dir = "./"
    model = whisperx.load_model("large-v2", device, compute_type=compute_type, download_root=model_dir, language="en")

    # the few videos I did with v3 seemed to be the worst transcriptions I've seen, but this could be a coincidence
    #model = whisperx.load_model("large-v3", device, compute_type=compute_type, download_root=model_dir, language="en")

    # basic transcription
    audio = whisperx.load_audio(mp3file)
    result = model.transcribe(audio, batch_size=batch_size)
    generate_output(result, base + '_basic.mp3')
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Transcription of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # delete model if low on GPU resources
    # import gc; gc.collect(); torch.cuda.empty_cache(); del model

    # align whisper output (generate accurate word-level timestamps)
    model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    aligned_result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
    generate_output(aligned_result, base + '_aligned.mp3')
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Alignment of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # delete model if low on GPU resources
    # import gc; gc.collect(); torch.cuda.empty_cache(); del model_a

    # Assign speaker labels ("diarization")
    with open('hf_token.txt') as f: token = f.readline()
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=token, device=device)
    diarize_segments = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers)
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Diarization of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # segments are now assigned speaker IDs
    diarize_result = whisperx.assign_word_speakers(diarize_segments, aligned_result)
    generate_output(diarize_result, base + '.mp3')

    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Output of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    return True

def push_to_git():
    subprocess.run(["git","add", "20*"]) 
    subprocess.run(["git","commit", "-a", "-m", "add video"]) 
    subprocess.run(["git","push"]) 

# allow us to pre-empt with ids in a file
def transcribe_with_preempt(download_only=False, id_file="ids_to_transcribe.txt", redo=False):

    if os.path.exists(id_file):
        with open(id_file) as f:
            yt_ids = f.read().splitlines()

        for priority_yt_id in yt_ids:
            # only do it if the mp3 file already exists
            # assumes we have a parallel download script running
            mp3files = glob.glob("*/*" + priority_yt_id + '.mp3')
            if (download_only != (len(mp3files) == 1)): # xor
                try:
                    update_data(priority_yt_id)
                    if transcribe(priority_yt_id, download_only=download_only, redo=redo):
                        srt2html.do_all()
                        push_to_git()
                except:
                    pass

    # check for new videos
    if (datetime.datetime.now() - last_update).total_seconds() > 3600:
        update_all()
        last_update = datetime.datetime.now()

    with open(jsonfile, 'r') as fp:
        video_data = json.load(fp)

    for yt_id in video_data.keys():
        # don't let hiccups halt progress
        # Move to next video and we can clean up later
        try: 
            if transcribe(yt_id, download_only=download_only, redo=redo):
                srt2html.do_all()
                push_to_git()
                return
        except KeyboardInterrupt:
            print('Interrupted')
            sys.exit()
        except: 
            pass

'''
 transcribe a youtube video, list of videos, channel, or list of channels.
'''
if __name__ == "__main__":

    # example usage:
    # python create_subtitles.py -c channels_to_transcribe.txt -i ids_to_transcribe.txt

    parser = argparse.ArgumentParser(description='Transcribe YouTube videos')
    parser.add_argument('-d','--download-only', dest='download_only', action='store_true', default=False, help="just download audio; don't transcribe")
    parser.add_argument('-r','--redo', dest='redo', action='store_true', default=False, help="redo transcription")
    parser.add_argument('-u','--update', dest='update', action='store_true', default=False, help="update only")
    parser.add_argument('-c','--channel-file', dest='channel_file', default="channels_to_transcribe.txt", help='filename containing a list of channels, transcribe all videos. This file will be checked for updates after each file to prioritize videos.')
    parser.add_argument('-i','--youtube-id-file', dest='id_file', default="ids_to_transcribe.txt", help='filename containing a list of YouTube IDs to transcribe')
 
    opt = parser.parse_args()

    if opt.update:
        update_all()
        sys.exit()

    # read info
    jsonfile = 'video_data.json'
    if not os.path.exists(jsonfile):
        print("video_data.json not found; updating")
        update_all()

    if os.path.exists(jsonfile):
        while True:
            transcribe_with_preempt(download_only=opt.download_only, id_file=opt.id_file, redo=opt.redo)
    else: 
        print("No video data file found after updating. Add channels to channels_to_transcribe.txt or ids to ids_to_transcribe.txt")
        sys.exit()

    # command to trim an audio file (0 to 300 seconds)
    # ffmpeg -i original.mp3 -ss 0 -to 300 trimmed.mp3