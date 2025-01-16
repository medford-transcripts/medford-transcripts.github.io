# pip install git+https://github.com/m-bain/whisperx.git
# note: I've manally updated to PR 952 to return speaker embeddings
# https://github.com/m-bain/whisperX/pull/952/files
import whisperx

# pip install yt_dlp
import yt_dlp 
# yt_dlp requires ffmpeg (stand alone executable) to be in your path (https://www.ffmpeg.org/download.html)
import numpy as np

# separately, pip install ffmpeg-python (the python package)
import ffmpeg

# whisperx dependency, pip will grab this
import torch 

# pip install ipdb
import ipdb
# not strictly required, but I'm leaving this here for debugging

# standard libraries 
import datetime, os, glob, argparse, math, sys, subprocess, time, traceback
import json
import dateutil.parser as dparser

# imports from this repo
import srt2html, supercut, generate_reference_voices, utils

# requires a "hugging face" token called "hf_token.txt" 
# in the top level directory with permissions for 
# a couple libraries. See requirements here:
# https://huggingface.co/pyannote/speaker-diarization-3.1 
#
##### test hugging face token #####
#from pyannote.audio import Pipeline
#with open('hf_token.txt') as f: token = f.readline()
#pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
#ipdb.set_trace()
###################################

last_update = datetime.datetime(2000,1,1)




# this prioritizes the videos by age, popularity (views), and/or duration
def update_priority():

    video_data = utils.get_video_data()

    now = datetime.datetime.now()
    priority = []
    halflife = 90.0
    for yt_id in video_data.keys():
        if "view_count" in video_data[yt_id].keys(): 
            views = video_data[yt_id]["view_count"]
        else: views = 0

        date = now

        if "upload_date" in video_data[yt_id].keys(): 
            date = datetime.datetime.strptime(video_data[yt_id]["upload_date"],'%Y-%m-%d')

        if "title" in video_data[yt_id].keys():
            try: 
                create_date = dparser.parse(video_data[yt_id]["title"],fuzzy=True)

                # sometimes the parser guesses too much. It can't be later the upload date
                if date > create_date:
                    date = create_date

            except ValueError:
                print('No parsable date in title of "' + video_data[yt_id]["title"] + '"')
                pass

        if "date" in video_data[yt_id].keys():
            # you can hand edit the date in the video_data.json file for ones that fail to parse
            date = datetime.datetime.strptime(video_data[yt_id]["date"],'%Y-%m-%d')

            
        age = (now - date).total_seconds()/86400.0

        if "duration" in video_data[yt_id].keys(): 
            duration = video_data[yt_id]["duration"]
        else: duration = 7200.0 # default to 2 hours

        # ad hoc prioritization scheme based on popularity, age, and/or duration

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

    utils.save_video_data(sorted_dict)

# updates video_data.json with info from yt_id
def update_data(yt_id):

    video_data = utils.get_video_data()

    if yt_id not in video_data.keys(): 
        video_data[yt_id] = {}

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
            utils.save_video_data(video_data)

def update_video_data():
    # read info
    video_data = utils.get_video_data()
    for yt_id in video_data.keys():
        update_data(yt_id)

def update_channel_slow(channel):

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

#def update_channel_fast(channel):
def update_channel(channel):

    video_data = utils.get_video_data()
    url = "https://www.youtube.com/" + channel 
    info = yt_dlp.YoutubeDL({'extract_flat':'in_playlist'}).extract_info(url, download=False) 

    # all we're trying to do is loop through a list of all YouTube IDs in this channel
    # there must be a better way, but the structure of info is a mystery to me
    # beware: info changes between channels with only one video type vs multiple video types

    for playlist in info["entries"]:
        if "entries" in playlist.keys():
            for entry in playlist["entries"]:
                if entry["id"] not in video_data.keys():
                    try:
                        update_data(entry["id"])
                    except Exception as error:
                        print("Failed on " + entry["id"])
                        print(error)
                        print(traceback.format_exc())
        else:
            # this captures channels with only one video type (?)
            # I think "playlist" is actually a video
            try:
                update_data(playlist["id"])
            except Exception as error:
                print("Failed on " + playlist["id"])
                print(error)
                print(traceback.format_exc())

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
    # I'm not sure what level of disagreement is acceptable. I've seen 6.6s discrepancies
    if abs((duration - video_data[yt_id]["duration"])) > 10.0:
        print(yt_id + ' mp3 file exists, but its length (' + str(duration) + ') does not match YouTube duration (' + str(video_data[yt_id]["duration"]) + ')')
        return False

    # otherwise, it's good
    return True

'''
 download the Youtube audio at highest quality as an mp3
 yt_id   - youtube ID
''' 
def download_audio(yt_id):

    # read info
    video_data = utils.get_video_data()

    if yt_id not in video_data.keys(): video_data[yt_id] = {}

    if mp3_is_good(yt_id, video_data):
        dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
        mp3file = os.path.join(dir,dir) +'.mp3'
        return mp3file, video_data[yt_id]["duration"]

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
    utils.save_video_data(video_data)

    dir = video_data[yt_id]["upload_date"] + "_" + yt_id 
    mp3file = os.path.join(dir,dir) +'.mp3'

    if mp3_is_good(yt_id, video_data):
        return mp3file, video_data[yt_id]["duration"]

    if not os.path.exists(dir): os.makedirs(dir)

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

def generate_output(result, mp3file):
    subdir = os.path.dirname(mp3file)
    result["language"] = "en"
    output_writer = whisperx.utils.get_writer("srt", subdir)
    output_writer(result, mp3file, {'max_line_width': None,'max_line_count': None,'highlight_words': False})
    return

def transcribe(yt_id, min_speakers=None, max_speakers=None, redo=False, download_only=False, transcribe_only=False):

    t0 = datetime.datetime.utcnow()
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Transcribing " + yt_id)

    if transcribe_only:
        video_data = utils.get_video_data()
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
    diarize_segments, embeddings = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers, return_embeddings=True)
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Diarization of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # segments are now assigned generic speaker IDs (e.g., SPEAKER_01)
    diarize_result = whisperx.assign_word_speakers(diarize_segments, aligned_result)

    # save result for later (word level timestamps, speaker re-identification)
    np.savez(os.path.join(subdir,"embeddings.npz"),embeddings)
    np.savez(os.path.join(subdir,"model.npz"),diarize_result)

    # now compare each this clip's speaker embeddings to the reference speaker embeddings
    # in order to assign named speakers
    threshold = 0.7
    reference_speakers = generate_reference_voices.get_reference_embeddings()
    nspeakers = len(embeddings["embeddings"])
    speaker_ids = {"AUTOMATED_IDS":True} 
    #speakers = ["SPEAKER_%02d" % x for x in np.arange(nspeakers)]
    for i, embedding in enumerate(embeddings["embeddings"]):
        score = np.empty()
        for speaker in reference_speakers.keys():
            score = np.append(score, 1.0 - cosine(embedding,reference_speaker[speaker]["average"]))
        bestidx = np.argmax(score)
        if score[bestidx] > threshold:
            speaker_ids["SPEAKER_" + str(i).zfill(2)] = reference_speakers.keys()[bestidx]
        else: 
            speaker_ids["SPEAKER_" + str(i).zfill(2)] = "SPEAKER_" + str(i).zfill(2)
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Speaker tracking of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # save the speaker ID JSON file
    jsonfile = os.path.join(subdir,"speaker_ids.json")
    with open(jsonfile, "w") as fp:
        json.dump(speaker_ids, fp, indent=4)

    # convert to SRT file
    generate_output(diarize_result, base + '.mp3')

    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Output of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    ipdb.set_trace()
    return True

def push_to_git():
    subprocess.run(["git","add", "20*"]) 
    subprocess.run(["git","commit", "-a", "-m", "add video"]) 
    subprocess.run(["git","push"]) 

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
                    update_data(priority_yt_id)
                    if transcribe(priority_yt_id, download_only=download_only, redo=redo, transcribe_only=transcribe_only):
                        srt2html.do_one(yt_id=priority_yt_id)
                        push_to_git()
                except Exception as error:
                    print("Failed on " + priority_yt_id)
                    print(error)
                    print(traceback.format_exc())

    # check for new videos
    update_all()

    video_data = utils.get_video_data()

    for yt_id in video_data.keys():
        # wrap in try so don't halt progress
        try: 
            if transcribe(yt_id, download_only=download_only, redo=redo, transcribe_only=transcribe_only):
                srt2html.do_one(yt_id)
                push_to_git()
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
        update_all()
        sys.exit()

    # read info
    jsonfile = 'video_data.json'
    if not os.path.exists(jsonfile):
        print("video_data.json not found; updating")
        update_all()

    if os.path.exists(jsonfile):
        while True:
            t0 = datetime.datetime.now()
            more_to_do = transcribe_with_preempt(download_only=opt.download_only, id_file=opt.id_file, redo=opt.redo, transcribe_only=opt.transcribe_only)
            tf = datetime.datetime.now()

            # if we did them all, wait an hour and check again
            # otherwise, on to the next one
            if more_to_do: time_to_sleep = 0
            else: time_to_sleep = 3600.0 - (tf-t0).total_seconds()

            if time_to_sleep > 0.0:            
                print("Done with all videos; waiting " + str(time_to_sleep) + " seconds to check again")
                time.sleep(time_to_sleep)

    else: 
        print("No video data file found after updating. Add channels to channels_to_transcribe.txt or ids to ids_to_transcribe.txt")
        sys.exit()

    # command to trim an audio file (0 to 300 seconds)
    # ffmpeg -i original.mp3 -ss 0 -to 300 trimmed.mp3