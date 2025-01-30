import glob, json, pickle
import subprocess, os
import datetime, random
import ipdb

import numpy as np
from scipy.spatial.distance import cosine

import yt_dlp 
from yt_dlp.utils import download_range_func
import ffmpeg

import utils
import whisperx, torch


'''
 This generates a handful of reference voices from previously identified clips with which to map generic speaker IDs to names.
'''

def get_unique_speakers():

    files = glob.glob("*/*.json")

    all_speakers = []
    unidentified = 0

    for file in files:
        with open(file, 'r') as fp:
            speaker_ids = json.load(fp)

        for key in speaker_ids.keys():
            if "SPEAKER" in speaker_ids[key]:
                unidentified += 1
            nspeakers += 1
            if "SPEAKER" in key and "SPEAKER" not in speaker_ids[key]:
                all_speakers.append(speaker_ids[key])

    unique_speakers = list(set(all_speakers))
    unique_speakers.sort()

    return unique_speakers

def download_audio_clips(clips, max_per_speaker=3, shuffle=True, min_length=10, max_length=30):

#    unique_speakers = get_unique_speakers()
    counter = {}

    # randomly select audio clips
    if shuffle:
        random.shuffle(clips)

    for clip in clips:

        clip_length = clip["stop_time"] - clip["start_time"]

        # only select clips within range for good/fast identification
        if clip_length < min_length or clip_length > max_length: continue

        # skip unidentified speakers
        if "SPEAKER_" in clip["speaker"]: continue 

        # skip clips without necessary metadata
        required_keys = ["date","speaker","start_time","stop_time","yt_id"]
        if not all(key in video_data[yt_id].keys() for key in required_keys): continue

        if clip["speaker"] in counter.keys():
            counter[clip["speaker"]] += 1
        else: 
            counter[clip["speaker"]] = len(glob.glob("voices_folder/" + clip["speaker"] + "/*.wav")) + 1

        if counter[clip["speaker"]] <= max_per_speaker:
            output_name = os.path.join("voices_folder", clip["speaker"], clip["speaker"] + "_" + clip["date"] + "_" + clip["yt_id"] + '_' + str(counter[clip["speaker"]]).zfill(3) + '.wav')
            download_clip(clip["yt_id"],clip["start_time"],clip["stop_time"],output_name)

def download_clip(yt_id, start_time, stop_time, output_name):

    url = "https://www.youtube.com/watch?v=" + yt_id

    yt_opts = {
        'verbose': True,
        'download_ranges': download_range_func(None,[(start_time, stop_time)]),
        'force_keyframes_at_cuts': True,
        "format": "bestaudio[ext=wav]/best", 
        "outtmpl": output_name,
    }

    with yt_dlp.YoutubeDL(yt_opts) as ydl:
        ydl.download(url)


def identify_clips():

    t0 = datetime.datetime(1900,1,1)   
    files = glob.glob("*/20??-??-??_???????????.srt")
    video_data = utils.get_video_data()

    clips = []

    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        dir = os.path.dirname(file)
        
        jsonfile = os.path.join(dir,'speaker_ids.json')
        if os.path.exists(jsonfile):
            with open(jsonfile, 'r') as fp:
                speaker_ids = json.load(fp)
        else: continue

        speaker = ""
        text = ""

        # extract text from this transcript
        with open(file, 'r', encoding="utf-8") as f:
            # Read each line in the file
            for line in f:
                line.strip()

                if "-->" in line:
                    # timestamp
                    start_string = line.split()[0]
                    stop_string = line.split()[-1]

                    # convert timestamp to seconds elapsed
                    this_start_time = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
                    this_stop_time = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()

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
                        stop_time = this_stop_time 
                    else:
                        # new speaker, save old one
                        if text != "":
                            clips.append({
                                "start_time":start_time,
                                "stop_time": stop_time,
                                "yt_id": yt_id,
                                "speaker": speaker,
                                "text": text,
                                "date": video_data[yt_id]["date"]
                                })

                        # update for next speaker
                        start_time = this_start_time
                        stop_time = this_stop_time
                        text = this_text
                        speaker = this_speaker 

                else: continue


            # append the final clip
            clips.append({
                "start_time":start_time,
                "stop_time": stop_time,
                "yt_id": yt_id,
                "speaker": speaker,
                "text": text
                })

    return clips

def get_reference_embeddings2(voices_folder="voices_folder", update=False):

    files = glob.glob('*/*.json')
    for jsonfile in files:

        dir = os.path.dirname(jsonfile)
        embedding_file = os.path.join(dir,"embeddings.pkl")

        # we already have embeddings (from runs that saved them), skip
        if os.path.exists(embedding_file): continue

        yt_id = '_'.join(jsonfile.split('_')[1:]).split('\\')[0]
        srtfile = os.path.join(dir,dir + ".srt")
        print(yt_id)

        # read the speaker_ids file
        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)        

        for key in speaker_ids.keys():

            # for each speaker, extract their longest clip
            clipname = extract_clip(srtfile, key, voices_folder=voices_folder)

            # and extract the speaker embeddings from that clip
            pklfile = extract_embedding(clipname)

def extract_embedding(clipname):
    pklfile = os.path.splitext(clipname)[0] + '.pkl'
    if os.path.exists(pklfile): return pklfile

    if not os.path.exists(clipname): return False

    # whisperX options
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with open('hf_token.txt') as f: token = f.readline()
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=token, device=device)    

    audio = whisperx.load_audio(clipname)
    diarize_segments, embeddings = diarize_model(audio, num_speakers=1, return_embeddings=True)

    with open(pklfile, 'wb') as fp: pickle.dump(embeddings, fp)

    return pklfile


def extract_clip(srtfile, key, voices_folder="voices_folder"):

    yt_id = '_'.join(srtfile.split('_')[1:]).split('\\')[0]
    clipname = os.path.join("voices_folder",yt_id + '_' + key + '.webm')
    if os.path.exists(clipname): return clipname

    t0 = datetime.datetime(1900,1,1)   

    with open(srtfile, 'r', encoding="utf-8") as f:

        text = ''
        last_speaker = ''
        max_clip_duration = 0.0
        last_stop_time = 0.0
        best_start = 0.0
        best_stop = 0.0

        # Read each line in the file
        for line in f:
            line.strip()

            if "-->" in line:
                # timestamp
                start_string = line.split()[0]
                stop_string = line.split()[-1]

                # convert timestamp to seconds elapsed
                this_start_time = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
                this_stop_time = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()

                if last_stop_time == 0.0: 
                    last_stop_time = this_start_time
                    start_time = this_start_time

            elif "[" in line:
                # text
                this_speaker = line.split()[0].split("[")[-1].split("]")[0]
                this_text = ":".join(line.split(":")[1:])

                # changed speakers or long silence; wrap it up                
                if this_speaker != last_speaker or ((this_start_time - last_stop_time) > 10):
                    if text != '':
                        clip_duration = last_stop_time - start_time

                        if clip_duration > max_clip_duration:
                            max_clip_duration = clip_duration
                            best_start = start_time
                            best_stop = last_stop_time

                    # for next time
                    start_time = this_start_time

                    if this_speaker != key: text = ''
                    else: text = this_text
                else:
                    # same speaker
                    stop_time = this_stop_time
                    text += this_text
                    if this_speaker != key: text = ''

                last_stop_time = this_stop_time
                last_speaker = this_speaker

        if text != '':
            clip_duration = last_stop_time - start_time

            if clip_duration > max_clip_duration:
                max_clip_duration = clip_duration
                best_start = start_time
                best_stop = last_stop_time        

    print((key, best_start, best_stop, max_clip_duration))

    if (best_stop - best_start) > 0.0:
        download_clip(yt_id, best_start, best_stop, output_name=clipname)

    return clipname

# Prepare speaker embeddings from the voices_folder
def get_reference_embeddings(voices_folder="voices_folder", update=False):

    # if no update requested, load pkl file and return
    pklfile = 'speaker_references.pkl'
    if os.path.exists(pklfile):
        with open(pklfile,'rb') as fp: reference_embeddings = pickle.load(fp)
    else:  
        reference_embeddings = {}

    update=True
    if not update:
        return reference_embeddings

    # whisperX options
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with open('hf_token.txt') as f: token = f.readline()
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=token, device=device)

    for speaker in os.listdir(voices_folder):
        print("Generating reference embeddings for " + speaker)
        speaker_path = os.path.join(voices_folder, speaker)
        if os.path.isdir(speaker_path):
            all_embeddings = []
            for file in os.listdir(speaker_path):
                if file.endswith(".wav"):
                    file_path = os.path.join(speaker_path, file)

                    audio = whisperx.load_audio(file_path)
                    diarize_segments, embeddings = diarize_model(audio, num_speakers=1, return_embeddings=True)

                    all_embeddings.append(embeddings["embeddings"][0])

            if len(all_embeddings) > 0:
                reference_embeddings[speaker] = {
                    "all": all_embeddings,
                    "average": np.mean(all_embeddings, axis=0)
                }

    # this is expensive! save to restore later
    with open(pklfile, 'wb') as fp: pickle.dump(reference_embeddings, fp)

    return reference_embeddings

if __name__ == "__main__":

    get_reference_embeddings2()
    ipdb.set_trace()


    reference_embeddings = get_reference_embeddings()
    ipdb.set_trace()

    clips = identify_clips()
    download_audio_clips(clips)
    ipdb.set_trace()