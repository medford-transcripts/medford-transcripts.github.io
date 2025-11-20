# pip install git+https://github.com/m-bain/whisperx.git
# note: I've manally updated to PR 952 to return speaker embeddings
# https://github.com/m-bain/whisperX/pull/952/files
import whisperx

# pip install yt_dlp
import yt_dlp 
# yt_dlp requires ffmpeg (stand alone executable) to be in your path (https://www.ffmpeg.org/download.html)

import numpy as np
from scipy.spatial.distance import cosine

# separately, pip install ffmpeg-python (the python package)
import ffmpeg

# whisperx dependency, pip will grab this
import torch 

# pip install ipdb
import ipdb
# not strictly required, but I'm leaving this here for debugging

import threading

# standard libraries 
import datetime, os, glob, argparse, math, sys, subprocess, time, traceback, shutil
import json, pickle
import dateutil.parser as dparser

# imports from this repo
import srt2html, supercut, generate_reference_voices, utils, track_speakers

# requires a "hugging face" token called "hf_token.txt" 
# in the top level directory with permissions for 
# a couple libraries. See requirements here:
# https://huggingface.co/pyannote/speaker-diarization-3.1 
#
##### to test your hugging face token, uncomment here #####
#from pyannote.audio import Pipeline
#with open('hf_token.txt') as f: token = f.readline()
#pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
#ipdb.set_trace()
###########################################################

last_update = datetime.datetime(2000,1,1)

def mp3_is_good(yt_id, video_data):

    # if video_data doesn't have all the required info, it's bad
    if yt_id not in video_data.keys(): return False
    required_keys = ["upload_date","channel","title","duration"]
    if all(key not in video_data[yt_id].keys() for key in required_keys): return False

    # if the mp3 file doesn't exist, it's bad
    dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
    mp3file = os.path.join(dir,dir) +'.mp3'
    if not os.path.exists(mp3file): return False

    # if the mp3 duration doesn't match the video duration, it's bad
    duration = float(ffmpeg.probe(mp3file)['format']['duration'])
    # I'm not sure what level of disagreement is acceptable. I've seen 12s discrepancies
    if abs((duration - video_data[yt_id]["duration"])) > 15.0:
        print(yt_id + ' mp3 file exists, but its length (' + str(duration) + ') does not match YouTube duration (' + str(video_data[yt_id]["duration"]) + ')')
        return False

    # otherwise, it's good
    return True

def download_all_channel_videos(channel="@masstraction-us-medford-1-22"):
    url = "https://www.youtube.com/" + channel 
    info = yt_dlp.YoutubeDL({'extract_flat':'in_playlist'}).extract_info(url, download=False) 

    # all we're trying to do is loop through a list of all YouTube IDs in this channel
    # there must be a better way, but the structure of info is a mystery to me
    # beware: info changes between channels with only one video type vs multiple video types

    for playlist in info["entries"]:
        if "entries" in playlist.keys():
            for entry in playlist["entries"]:
                #if entry["id"] not in video_data.keys():
                    try:
                        download_video(entry["id"])
                    except Exception as error:
                        print("Failed on " + entry["id"])
                        print(error)
                        print(traceback.format_exc())
        else:
            # this captures channels with only one video type (?)
            # I think "playlist" is actually a video
            try:
                download_video(playlist["id"])
            except Exception as error:
                print("Failed on " + playlist["id"])
                print(error)
                print(traceback.format_exc())

def download_video(yt_id):
    
    # this only gets audio (but way faster than my audio-only download)
    #yt-dlp https://www.youtube.com/watch?v=NDgiDfoPie4 -x --audio-format mp3 --audio-quality 5

    # getting cookies from chrome in windows is broken
    # generate the cookies if we haven't already:
    # yt-dlp --cookies-from-browser firefox --cookies cookies.txt
    if not os.path.exists("cookies.txt"):
        command = [
            "yt-dlp",
            "--cookies-from-browser","firefox",
            "--cookies","cookies.txt"
            ]
        subprocess.run(command)

    print("Downloading " + yt_id + ", but with a workaround for issue #14157")
    # now download the video
    command = [
        "yt-dlp",
        "--cookies-from-browser", "firefox",
        "--cookies","cookies.txt",
        "--extractor-args", "youtube:player_client=default,web_safari;player_js_version=actual", # workaround as seen in #14680 (lower quality!) to address pending merge of #14157 
        "https://www.youtube.com/watch?v=" + yt_id
        ]

    subprocess.run(command)

'''
 download the Youtube audio at highest quality as an mp3
 yt_id   - youtube ID
''' 
def download_audio(yt_id, video=False):

    # read info
    video_data = utils.get_video_data()

    if yt_id not in video_data.keys(): video_data[yt_id] = {}

    dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
    if mp3_is_good(yt_id, video_data):
        mp3file = os.path.join(dir,dir) +'.mp3'
        return mp3file, video_data[yt_id]["duration"]

    # i think these stubs get left behind when it partially downloads while live streaming
    # there must be a way to salvage these parts, but we'll just start over
    corrupt_filename = os.path.join(dir,dir)
    if os.path.exists(corrupt_filename):
        os.remove(corrupt_filename)

    url = "https://youtu.be/" + yt_id
    with yt_dlp.YoutubeDL() as ydl:
        info = ydl.extract_info(url, download=False)

    audio_url = ''
    for format in info["formats"][::-1]:
        if format["resolution"] == "audio only" and format["ext"] == "m4a":
            # this is a temporary, IP-locked URL, storing it doesn't do any good
            audio_url = format["url"]
            
            # store these for later
            video_data[yt_id]["title"] = info["title"]
            video_data[yt_id]["channel"] = info["channel"]
            video_data[yt_id]["duration"] = info["duration"]

            # links and a bunch of stuff are built around the upload date, 
            # and it sometimes changes (I think livestreams update when finished). 
            # Don't update it or things break!
            if "upload_date" not in video_data[yt_id].keys():
                video_data[yt_id]["upload_date"] = datetime.datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")

            # update video_data
            utils.save_video_data(video_data)
            break

    dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
    if not os.path.exists(dir): os.makedirs(dir)
    mp3file = os.path.join(dir,dir) +'.mp3'

    if audio_url == '': 
        print("Could not find audio url for " + yt_id + ", attempting direct download of mp3")
        subprocess.run(['yt-dlp', 'https://www.youtube.com/watch?v=' + yt_id,'-x', '--audio-format', 'mp3', '--audio-quality', '5'])
        mp3path = glob.glob('*' + yt_id + '*.mp3')[0]        
        if len(mp3path) == 1:
            mp3path = mp3path[0]
            shutil.move(mp3path, mp3file)

    if False:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(dir,dir),
            'skip_unavailable_fragments': False,
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
    else: 
        print("working around audio only download! check on yt-dlp #14157 to see if it's merged")
        download_video(yt_id)
        exts = ['mp4', 'webm', 'mkv']
        input_file = [f for ext in exts for f in glob.glob(f'*{yt_id}*.{ext}')]
        if len(input_file) == 0:
            return
        else:
            input_file = input_file[0]

        
        output_file = os.path.join(dir,dir) + '.mp3'
        subprocess.run(["ffmpeg", "-y", "-i", input_file, "-vn", "-ab", "320k", output_file])
        os.remove(input_file)

    if mp3_is_good(yt_id, video_data):
        return mp3file, video_data[yt_id]["duration"]

# default is Medford Bytes apple podcast  
def download_rss_feed(rss_feed="https://anchor.fm/s/6f6f95b8/podcast/rss"):

    video_data = utils.get_video_data()

    ydl_extract_opts = {"quiet": True, "dump_single_json": True}
    with yt_dlp.YoutubeDL(ydl_extract_opts) as ydl:
        playlist_dict = ydl.extract_info(rss_feed, download=False)

    entries = playlist_dict["entries"]
    for entry in entries:
        date_raw = entry["upload_date"]
        date_fmt = f"{date_raw[0:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        ep_num = entry["playlist_count"] - entry["playlist_index"] + 1
        yt_id = "XXXXXX" + str(ep_num).zfill(5)

        # already downloaded, skip
        if mp3_is_good(yt_id, video_data): continue

        if not yt_id in video_data.keys(): video_data[yt_id] = {}

        # update video_data and download
        video_data[yt_id]["title"] = entry["title"]  
        video_data[yt_id]["channel"] = entry["playlist"]    
        video_data[yt_id]["duration"] = entry["duration"]
        video_data[yt_id]["upload_date"] = date_fmt
        video_data[yt_id]["view_count"] = 100 # this is only used for prioritization
        video_data[yt_id]["date"] = date_fmt
        video_data[yt_id]["url"] = "" # this is used for timestamped links, but we can't do that with apple. TODO: find the URL on spotify (or an RSS feed for spotify)

        utils.save_video_data(video_data)

        dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
        mp3file = os.path.join(dir,dir) +'.mp3'
        
        # Build folder and file name
        os.makedirs(dir, exist_ok=True)

        # yt-dlp options for this episode
        ydl_opts = {
            "format": "bestaudio/best",
            "extractaudio": True,
            "audioformat": "mp3",
            "outtmpl": os.path.join(dir,dir),
            "writethumbnail": False,
            "writeinfojson": False,
            "embedmetadata": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
                {"key": "FFmpegMetadata"},
            ],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([entry["url"]])


'''
translates the model file to human-readable outputs (SRT file)
'''
def generate_output(result, mp3file):
    subdir = os.path.dirname(mp3file)
    result["language"] = "en"
    output_writer = whisperx.utils.get_writer("srt", subdir)
    output_writer(result, mp3file, {'max_line_width': None,'max_line_count': None,'highlight_words': False})
    return

'''
uses whisperx to transcribe a video specified by YouTube ID (yt_id)
'''
def transcribe(yt_id, min_speakers=None, max_speakers=None, redo=False, download_only=False, transcribe_only=False):

    t0 = datetime.datetime.utcnow()
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Transcribing " + yt_id)

    if transcribe_only:
        print(str(datetime.datetime.utcnow()-t0).total_seconds())
        video_data = utils.get_video_data()
        print(str(datetime.datetime.utcnow()-t0).total_seconds())
        if not mp3_is_good(yt_id, video_data):
            print("mp3 file not ready and download not requested; skipping " + yt_id)
            return False
        else: 
            print("Duration of " + yt_id + " is " + str(video_data[yt_id]["duration"]/60) + " minutes")
            dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
            mp3file = os.path.join(dir,dir) +'.mp3' 
    else:
        mp3file, duration = download_audio(yt_id)
        print("Duration of " + yt_id + " is " + str(duration/60) + " minutes")

    base = os.path.splitext(mp3file)[0]
    subdir = os.path.dirname(mp3file)
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Download of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    if download_only: return False

    # skip files that are already done
    print(str(datetime.datetime.utcnow()-t0).total_seconds())
    files = glob.glob("*/20??-??-??_" + yt_id + ".srt")
    print(str(datetime.datetime.utcnow()-t0).total_seconds())
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
    # specifying english here will automatically translate other languages to english!
    # but often, it gets the language wrong when automatically identifying it
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

    # returning embeddings require custom modifications to whisperx (see PR997). 
    # use commented line for stock whisperx (and lose the ability to match speakers across videos)
    diarize_segments, embeddings = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers, return_embeddings=True)
    #diarize_segments = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers) 
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Diarization of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # assign generic speaker IDs (e.g., SPEAKER_01) to segments
    diarize_result = whisperx.assign_word_speakers(diarize_segments, aligned_result)

    # save result for later (word level timestamps, speaker re-identification)
    with open(os.path.join(subdir,"embeddings.pkl"),'wb') as fp: pickle.dump(embeddings, fp)
    with open(os.path.join(subdir,"model.pkl"),'wb') as fp: pickle.dump(diarize_result, fp)

    # convert to SRT file
    generate_output(diarize_result, base + '.mp3')

    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Output of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    return True

'''
update the repo with new results
'''
def push_to_git():
    subprocess.run(["git","add", "20*"]) 
    subprocess.run(["git","add", "resolutions/*"]) 
    subprocess.run(["git","add", "agendas/*"]) 
    subprocess.run(["git","add", "minutes/*"]) 
    subprocess.run(["git","add", "other_files/*"]) 
    subprocess.run(["git","commit", "-a", "-m", "add video"]) 
    subprocess.run(["git","push"]) 

# this mostly waits on google translate; do it in the background
def finish_async(yt_id):
    srt2html.do_one(yt_id=yt_id)
    push_to_git()

# allow us to pre-empt with ids in a file
def transcribe_with_preempt(download_only=False, id_file="ids_to_transcribe.txt", redo=False, transcribe_only=False):

    if os.path.exists(id_file):
        with open(id_file) as f:
            yt_ids = f.read().splitlines()

        for priority_yt_id in yt_ids:
            # only do it if the mp3 file already exists
            # assumes we have a parallel download script running
            mp3files = glob.glob("*/*" + priority_yt_id + '.mp3')
            if (download_only != (len(mp3files) == 1)): # xor
                try:
                    utils.update_video_data_one(priority_yt_id)
                    if transcribe(priority_yt_id, download_only=download_only, redo=redo, transcribe_only=transcribe_only):
                        track_speakers.match_embeddings(priority_yt_id)
                        track_speakers.match_to_reference2(yt_id=priority_yt_id)
                        track_speakers.propagate()

                        thread = threading.Thread(target=finish_async, args=(priority_yt_id,))
                        thread.start()

                        #srt2html.do_one(yt_id=priority_yt_id)
                        #push_to_git()
                except Exception as error:
                    print("Failed on " + priority_yt_id)
                    print(error)
                    print(traceback.format_exc())

    # check for new videos
    utils.update_all()

    # do the highest priority video not already done
    video_data = utils.get_video_data()
    for yt_id in video_data.keys():
        # wrap in try so don't halt progress
        try: 
            if transcribe(yt_id, download_only=download_only, redo=redo, transcribe_only=transcribe_only):
                track_speakers.match_embeddings(yt_id)
                track_speakers.match_to_reference2(yt_id=yt_id)
                track_speakers.propagate()

                thread = threading.Thread(target=finish_async, args=(yt_id,))
                thread.start()

                #srt2html.do_one(yt_id)
                #push_to_git()
                # after every successful transcription, 
                # we'll restart this loop to check for higher priority videos 
                return True
        except KeyboardInterrupt:
            print('Interrupted')
            sys.exit()
        except Exception as error:
            print("Failed on " + yt_id)
            print(error)
            print(traceback.format_exc())

    return False

'''
 transcribe a youtube video, list of videos, channel, or list of channels.
'''
if __name__ == "__main__":

    # example usage:
    # python create_subtitles.py -c channels_to_transcribe.txt -i ids_to_transcribe.txt

    parser = argparse.ArgumentParser(description='Transcribe YouTube videos')
    parser.add_argument('-d','--download-only', dest='download_only', action='store_true', default=False, help="just download audio; don't transcribe")
    parser.add_argument('-t','--transcribe-only', dest='transcribe_only', action='store_true', default=False, help="just transcribe audio; don't download")
    parser.add_argument('-r','--redo', dest='redo', action='store_true', default=False, help="redo transcription")
    parser.add_argument('-u','--update', dest='update', action='store_true', default=False, help="update only")
    parser.add_argument('-c','--channel-file', dest='channel_file', default="channels_to_transcribe.txt", help='filename containing a list of channels, transcribe all videos. This file will be checked for updates after each file to prioritize videos.')
    parser.add_argument('-i','--youtube-id-file', dest='id_file', default="ids_to_transcribe.txt", help='filename containing a list of YouTube IDs to transcribe')
 
    opt = parser.parse_args()

    if opt.update:
        utils.update_all()
        sys.exit()

    # read info
    jsonfile = 'video_data.json'
    if not os.path.exists(jsonfile):
        print("video_data.json not found; updating")
        utils.update_all()

    if os.path.exists(jsonfile):
        while True:
            t0 = datetime.datetime.now()
            more_to_do = transcribe_with_preempt(download_only=opt.download_only, id_file=opt.id_file, redo=opt.redo, transcribe_only=opt.transcribe_only)

            # if we did them all, wait an hour and check again
            # otherwise, on to the next one
            if more_to_do: time_to_sleep = 0
            else: 
                download_rss_feed()
                tf = datetime.datetime.now()
                time_to_sleep = 3600.0 - (tf-t0).total_seconds()

            if time_to_sleep > 0.0:            
                later = (datetime.datetime.now() + datetime.timedelta(seconds=time_to_sleep)).strftime("%Y-%m-%d %H:%M:%S")
                print("Done with all videos; checking again at " + later)
                time.sleep(time_to_sleep)

    else: 
        print("No video data file found after updating. Add channels to channels_to_transcribe.txt or ids to ids_to_transcribe.txt")
        sys.exit()

    # command to trim an audio file (0 to 300 seconds)
    # ffmpeg -i original.mp3 -ss 0 -to 300 trimmed.mp3