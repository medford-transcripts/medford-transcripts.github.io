# pip install git+https://github.com/m-bain/whisperx.git
# note: I've manally updated to PR 952 to return speaker embeddings
# https://github.com/m-bain/whisperX/pull/952/files
import whisperx

# pip install yt_dlp
import yt_dlp 
# yt_dlp requires ffmpeg (stand alone executable) to be in your path (https://www.ffmpeg.org/download.html)

# pip install internetarchive (for MCM pages)
from internetarchive import Search, ArchiveSession, get_item
import requests

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
from pathlib import Path

# imports from this repo
import srt2html, supercut, generate_reference_voices, utils, track_speakers
import download_mcm

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

# prevent thread clashing for git push
_git_lock = threading.Lock()
_git_pending = False
_git_pending_lock = threading.Lock()

audio_path_backup = "D:/medford-transcripts.github.io/audio/"
audio_path = "audio/"

last_update = datetime.datetime(2000,1,1)

# if the transcription is done, make sure the audio file is on the external drive
def move_audio():
    video_data = utils.get_video_data()
    for yt_id in video_data.keys():
        base = video_data[yt_id]["upload_date"] + "_" + yt_id

        mp3_external = audio_path_backup + base + ".mp3"
        mp3_local = audio_path + base + ".mp3"

        srtfile = base + "/" + base + ".srt"
        if os.path.exists(srtfile):
            if os.path.exists(mp3_local):
                shutil.move(mp3_local,mp3_external)

def get_audio_absolute_path(base, allow_nonexist=False):

    external_name = audio_path_backup + base + '.mp3'
    local_name = audio_path + base + '.mp3'

    if os.path.exists(local_name): return local_name
    if os.path.exists(external_name): return external_name

    if allow_nonexist: return local_name
    return None

def mp3_is_good(yt_id, video_data):

    # if video_data doesn't have all the required info, it's bad
    if yt_id not in video_data.keys(): return False
    required_keys = ["upload_date","channel","title","duration"]
    if all(key not in video_data[yt_id].keys() for key in required_keys): return False

    # if the mp3 file doesn't exist, it's bad
    base = video_data[yt_id]["upload_date"] + "_" + yt_id 
    mp3file = utils.get_mp3filename(yt_id)
    if mp3file is None: return False

    # if the mp3 duration doesn't match the video duration, it's bad
    try:
        duration = float(ffmpeg.probe(mp3file)['format']['duration'])
        # I'm not sure what level of disagreement is acceptable. I've seen 12s discrepancies
        if abs((duration - video_data[yt_id]["duration"])) > 15.0:
            print(yt_id + ' mp3 file exists, but its length (' + str(duration) + ') does not match YouTube duration (' + str(video_data[yt_id]["duration"]) + ')')
            return False
    except:
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

    # not a youtube video, can't download in this function
    if yt_id[0:6] == "XXXXXX" or yt_id[0:6] == "MCM000":
        return

    # read info
    video_data = utils.get_video_data()

    if yt_id not in video_data.keys(): video_data[yt_id] = {}

    base = video_data[yt_id]["upload_date"] + "_" + yt_id 
    if mp3_is_good(yt_id, video_data):
        mp3file = utils.get_mp3filename(yt_id, video_data=video_data)
        return mp3file, video_data[yt_id]["duration"]

    # i think these stubs (with no extension) get left behind when it partially downloads while live streaming
    # there must be a way to salvage these parts, but we'll just start over
    corrupt_filename = os.path.join(audio_path,base)
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

    base = video_data[yt_id]["upload_date"] + "_" + yt_id 
    mp3file = utils.get_mp3filename(yt_id, video_data=video_data)

    if audio_url == '': 
        print("Could not find audio url for " + yt_id + ", attempting direct download of mp3")
        subprocess.run(['yt-dlp', 'https://www.youtube.com/watch?v=' + yt_id,'-x', '--audio-format', 'mp3', '--audio-quality', '5'])

        # yt-dlp names the file after the video title, so it has to be moved
        # into audio/ under our <date>_<yt_id> convention.
        #
        # This previously read:
        #     mp3path = glob.glob(...)[0]     # <- already a string
        #     if len(mp3path) == 1:           # <- tests the FILENAME's length
        # which is never true, so the move never ran. The download was left in
        # the repo root, and because there was also no early return, execution
        # fell straight through to the video-download branch below and fetched
        # the SAME video a second time. Every video taking this path was
        # downloaded twice; 49 stranded mp3s / 1.9 GB had accumulated.
        # See plan.txt A14.
        candidates = glob.glob('*' + yt_id + '*.mp3')
        if not candidates:
            print("yt-dlp produced no mp3 for " + yt_id)
        else:
            dest = utils.get_mp3filename(yt_id, video_data=video_data, local=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(candidates[0], dest)
            print("moved " + candidates[0] + " -> " + dest)

            # the fallback succeeded; do NOT also download the full video below
            if mp3_is_good(yt_id, video_data):
                return utils.get_mp3filename(yt_id, video_data=video_data), video_data[yt_id]["duration"]
            print("direct mp3 download failed validation; falling back to video download")

    if False:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(audio_path,base),
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

        
        output_file = os.path.join(audio_path,base) + '.mp3'
        subprocess.run(["ffmpeg", "-y", "-i", input_file, "-vn", "-ab", "320k", output_file])
        os.remove(input_file)

    if mp3_is_good(yt_id, video_data):
        # recompute: mp3file was resolved BEFORE the download, so on a fresh
        # download it is still None. Harmless today only because -d and -t run
        # as separate processes and nothing consumes this return value on the
        # download path; it would crash transcribe() in combined mode.
        return utils.get_mp3filename(yt_id, video_data=video_data), video_data[yt_id]["duration"]

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

        base = video_data[yt_id]["upload_date"] + "_" + yt_id 
        mp3file = utils.get_mp3filename(yt_id, video_data=video_data)
        
        # yt-dlp options for this episode
        ydl_opts = {
            "format": "bestaudio/best",
            "extractaudio": True,
            "audioformat": "mp3",
            "outtmpl": os.path.join(audio_path,base),
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
    #subdir = "_".join(Path(mp3file).stem.split("_")[0:-1])
    subdir = Path(mp3file).stem
    if "_basic" in subdir or "_aligned" in subdir:
        subdir = "_".join(Path(mp3file).stem.split("_")[0:-1])

    result["language"] = "en"
    output_writer = whisperx.utils.get_writer("srt", subdir)
    output_writer(result, mp3file, {'max_line_width': None,'max_line_count': None,'highlight_words': False})
    return

_manual_corrections = None


def is_manually_corrected(yt_id):
    """True if this transcript carries hand corrections we must not clobber.

    The list is produced by find_manual_edits.py, which compares the current
    .srt against fix_common_errors rules re-applied to the .srt.orig snapshot.
    Anything the automated rules cannot account for is a human edit.
    """
    global _manual_corrections
    if _manual_corrections is None:
        try:
            with open("manual_corrections.json", "r", encoding="utf-8") as fp:
                _manual_corrections = set(json.load(fp).get("ids", {}))
        except (OSError, ValueError):
            _manual_corrections = set()
    return yt_id in _manual_corrections



# ---------------------------------------------------------------------------
# MODEL CACHE -- load each model ONCE per process, not once per video.
#
# These three were being constructed inside transcribe(), which the main loop
# calls once per video, so every single meeting paid a full load of the ASR
# model, the alignment model and the diarization pipeline, then dropped them.
#
# That was costing minutes per video, but the bigger problem was memory. Torch
# does not return freed arena back to the OS, so repeatedly allocating and
# discarding GB-sized models grows the process's COMMITTED memory even while
# resident size stays modest. Measured on this machine mid-run: RSS 1.4 GB but
# 11.5 GB committed, with the system at 27.7 GB of a 31.5 GB commit limit --
# which is why unrelated processes kept being evicted, and matches the 89
# Resource-Exhaustion events in the event log.
#
# Holding one copy costs steady-state memory but removes the churn and the
# repeated arena growth, which is the thing actually exhausting commit.
#
# BATCH_SIZE is also lowered from 16: it is the main knob on peak allocation
# during transcription, and this machine has 16 GB shared with everything else.
BATCH_SIZE = 8

_asr_model = None
_align_models = {}
_diarize_model = None


def get_asr_model(device, compute_type):
    global _asr_model
    if _asr_model is None:
        print("loading whisper model (once per process)...")
        # specifying english here will automatically translate other languages
        # to english! but often it gets the language wrong when auto-detecting
        #
        # the few videos done with large-v3 seemed to be the worst
        # transcriptions seen, though that could be coincidence
        _asr_model = whisperx.load_model("large-v2", device,
                                         compute_type=compute_type,
                                         download_root="./", language="en")
    return _asr_model


def get_align_model(language_code, device):
    """Alignment model, cached per language (in practice only 'en')."""
    if language_code not in _align_models:
        print("loading alignment model for " + str(language_code) + " (once)...")
        _align_models[language_code] = whisperx.load_align_model(
            language_code=language_code, device=device)
    return _align_models[language_code]


def get_diarize_model(device):
    global _diarize_model
    if _diarize_model is None:
        print("loading diarization pipeline (once per process)...")
        with open('hf_token.txt') as f:
            token = f.readline()
        _diarize_model = whisperx.DiarizationPipeline(use_auth_token=token,
                                                      device=device)
    return _diarize_model


'''
uses whisperx to transcribe a video specified by YouTube ID (yt_id)
'''
def transcribe(yt_id, min_speakers=None, max_speakers=None, redo=False, download_only=False, transcribe_only=False):

    t0 = datetime.datetime.utcnow()
    print("\n" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Transcribing " + yt_id)

    video_data = utils.get_video_data()
    base = video_data[yt_id]["upload_date"] + "_" + yt_id
    subdir = base

    if "skip" in video_data[yt_id].keys():
        if video_data[yt_id]["skip"]:
            print("Skip flag set for " + yt_id + "; skipping")
            return False

    # make the subdirectory if it doesn't already exist
    path = Path(subdir)
    path.mkdir(parents=True, exist_ok=True)

    srtfile = os.path.join(subdir,base) +'.srt'
    if os.path.exists(srtfile) and not redo:
        print("Already done with " + yt_id + " (" + srtfile + "). Set redo=True to redo transcription")
        return False

    # Never silently destroy hand corrections. 81 transcripts contain manual
    # edits -- corrected words, reassigned speakers, roll-call votes split into
    # individual turns. They are ground truth for the eval set and the
    # roll-call extractor, and 67 of them have no model.pkl, so redoing them
    # means RE-TRANSCRIBING from audio and the corrections are simply gone.
    # See find_manual_edits.py / manual_corrections.json.
    if redo and os.path.exists(srtfile) and is_manually_corrected(yt_id):
        print("REFUSING to redo " + yt_id + ": it contains manual corrections "
              "(manual_corrections.json). Back up " + srtfile + " and remove "
              "the id from that file if you really mean to overwrite it.")
        return False

    if transcribe_only:
        #print("starting: " + str((datetime.datetime.utcnow()-t0).total_seconds()))
        #print("read json video metadata: " + str((datetime.datetime.utcnow()-t0).total_seconds()))
        if not mp3_is_good(yt_id, video_data):
            #print("checking mp3: " + str((datetime.datetime.utcnow()-t0).total_seconds()))
            print("mp3 file not ready and download not requested; skipping " + yt_id)
            return False
        else: 
            print("Duration of " + yt_id + " is " + str(video_data[yt_id]["duration"]/60) + " minutes")         
            mp3file = utils.get_mp3filename(yt_id,video_data=video_data) 
    else:
        result = download_audio(yt_id)
        if result is None:
            print("Cannot download " + yt_id + "; skipping")
            return False

        mp3file, duration = result
        print("Duration of " + yt_id + " is " + str(duration/60) + " minutes")

    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Download of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    if download_only: return False

    # whisperX options
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16" # change to "int8" if low on GPU mem (may reduce accuracy)
    else:
        device = "cpu"
        compute_type = "int8"

    # CHECKPOINT. Transcription + alignment is the overwhelming majority of the
    # work -- roughly 3.3 hours of wall time per hour of audio, so a 5 hour
    # meeting is most of a day. Diarization runs after it, and until this
    # existed a crash, a reboot, a battery blip or an operator restarting the
    # service during diarization threw ALL of it away and started from zero.
    #
    # That happened for real: MCM00000556 lost 3.9 hours of completed
    # transcription and alignment to a restart, even though _basic.srt and
    # _aligned.srt were sitting on disk -- those are text renderings and do
    # not carry the word-level structure assign_word_speakers needs, so they
    # could not be resumed from.
    #
    # The checkpoint is deleted once model.pkl is written, so it costs nothing
    # steady-state; it only exists during the window where a restart is
    # expensive.
    ckpt = os.path.join(subdir, "aligned.checkpoint.pkl")
    aligned_result = None
    if os.path.exists(ckpt):
        try:
            with open(ckpt, "rb") as fp:
                aligned_result = pickle.load(fp)
            print("resuming " + yt_id + " from alignment checkpoint "
                  "(skipping transcription + alignment)")
        except Exception:
            print("alignment checkpoint unreadable; redoing from scratch")
            print(traceback.format_exc())
            aligned_result = None

    audio = whisperx.load_audio(mp3file)

    if aligned_result is None:
        # basic transcription
        model = get_asr_model(device, compute_type)
        result = model.transcribe(audio, batch_size=BATCH_SIZE)
        generate_output(result, base + '_basic.mp3')
        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Transcription of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

        # align whisper output (generate accurate word-level timestamps)
        model_a, metadata = get_align_model(result["language"], device)
        aligned_result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
        generate_output(aligned_result, base + '_aligned.mp3')
        print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Alignment of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

        # write the checkpoint atomically so a crash mid-write cannot leave a
        # truncated pickle that looks resumable
        try:
            tmp = ckpt + ".tmp"
            with open(tmp, "wb") as fp:
                pickle.dump(aligned_result, fp)
            os.replace(tmp, ckpt)
        except Exception:
            print("could not write alignment checkpoint (continuing anyway)")
            print(traceback.format_exc())

    # delete model if low on GPU resources
    # import gc; gc.collect(); torch.cuda.empty_cache(); del model_a

    # Assign speaker labels ("diarization")
    diarize_model = get_diarize_model(device)

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

    # the expensive work is now durably captured in model.pkl, so the resume
    # checkpoint has done its job and would only waste disk from here
    if os.path.exists(ckpt):
        try:
            os.remove(ckpt)
        except OSError:
            pass

    # convert to SRT file
    generate_output(diarize_result, base + '.mp3')

    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ": Output of " + yt_id + " complete in " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    return True

'''
update the repo with new results
'''
def request_git_push():
    global _git_pending

    # If we can run now, run now.
    if _git_lock.acquire(blocking=False):
        try:
            push_to_git()
        finally:
            _git_lock.release()

        # After finishing, check if anything came in while we ran.
        while True:
            with _git_pending_lock:
                if not _git_pending:
                    break
                _git_pending = False
            _git_lock.acquire()
            try:
                push_to_git()
            finally:
                _git_lock.release()
        return

    # Otherwise, mark a single pending push and return immediately.
    with _git_pending_lock:
        _git_pending = True


# Paths holding AUTOMATICALLY GENERATED content. Only these are auto-committed.
#
# Anything not listed here -- source code, .bat files, .gitignore, CLAUDE.md,
# hand-maintained pages like about.html and header.html -- is left alone for a
# human to commit deliberately.
#
# These are directory/file PATHSPECS, not a list of "what we just made":
# `git add <path>` stages every change under that path no matter when it
# happened, so work left behind by a previous failed push, or edited by hand
# afterwards, still gets picked up on the next run.
GENERATED_PATHS = [
    "20*",              # transcript directories, <date>_<yt_id>/
    "t",                # restructured transcripts (Phase 3), if present
    "resolutions",
    "agendas",
    "minutes",
    "other_files",
    "committees",
    "election",
    "electeds",
    "index.html",
    "resolutions.html",
    "heatmap.html",
    "sitemap.xml",
    "video_data.json",
    "medford_index.json",
]


def push_to_git():
    """Commit and push generated content only.

    This used to end in `git commit -a`, which stages EVERY modified tracked
    file -- so a background push would sweep up whatever source edits happened
    to be in the working tree and commit them, mid-edit, as "add video". It did
    exactly that during the 2026-09-15 refactor, committing a half-finished
    srt2html.py without the new module it imported. See plan.txt.
    """
    # stage only generated content; ignore paths that don't exist yet
    for path in GENERATED_PATHS:
        subprocess.run(["git", "add", "--", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # commit only if something is actually staged -- `git commit` with nothing
    # staged returns non-zero and spams the log every cycle
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if staged.returncode != 0:
        result = subprocess.run(["git", "commit", "-m", "add video"])
        if result.returncode != 0:
            print("git commit failed (rc=%d); not pushing" % result.returncode)
            return
    else:
        print("nothing new to commit")

    # push regardless of whether we just committed: a previous push may have
    # failed, leaving good commits stranded locally
    ahead = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"],
                           capture_output=True, text=True)
    try:
        n_ahead = int((ahead.stdout or "0").strip() or 0)
    except ValueError:
        n_ahead = 1  # no upstream info; attempt the push anyway

    if n_ahead == 0:
        return

    print("pushing %d commit(s)" % n_ahead)
    if subprocess.run(["git", "push"]).returncode != 0:
        print("git push FAILED; %d commit(s) still local, will retry next cycle"
              % n_ahead)

# this mostly waits on google translate; do it in the background
def finish_async(yt_id):
    srt2html.do_one(yt_id=yt_id)
    request_git_push()

def rebuild_from_model(yt_id):
    
    video_data = utils.get_video_data()

    subdir = video_data[yt_id]["upload_date"] + "_" + yt_id 
    base = video_data[yt_id]["upload_date"] + "_" + yt_id 
    pklfile = subdir + "/model.pkl"
    if not os.path.exists(pklfile):
        print("No model file")
        return

    with open(pklfile, 'rb') as file:
        diarize_result = pickle.load(file)

    mp3file = audio_path + '/' + base + '.mp3'
    generate_output(diarize_result,mp3file)

    track_speakers.match_embeddings(yt_id)
    track_speakers.match_to_reference2(yt_id=yt_id)
    track_speakers.propagate()
    srt2html.do_one(yt_id=yt_id)
    request_git_push()

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

        # Exponential backoff on repeated failure.
        #
        # This loop used to be `except: more_to_do = True`, which set
        # time_to_sleep = 0. Any PERSISTENT failure (external drive unplugged,
        # network down, expired cookies) therefore span at full speed --
        # pegging a core and hammering YouTube until we got rate-limited,
        # which made downloads slower still. It looked like a hang rather than
        # a crash. See plan.txt A5.
        BACKOFF_START = 60.0      # 1 minute
        BACKOFF_CAP = 1800.0      # 30 minutes
        consecutive_failures = 0

        while True:
            t0 = datetime.datetime.now()
            failed = False
            try:
                more_to_do = transcribe_with_preempt(download_only=opt.download_only, id_file=opt.id_file, redo=opt.redo, transcribe_only=opt.transcribe_only)
            except (KeyboardInterrupt, SystemExit):
                # a bare `except:` swallowed these; Ctrl-C could not stop the loop
                print("\nInterrupted; exiting.")
                raise
            except Exception:
                failed = True
                more_to_do = True
                consecutive_failures += 1
                print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
                      ": pass failed (" + str(consecutive_failures) + " in a row)")
                print(traceback.format_exc())

            if not failed:
                consecutive_failures = 0

            if failed:
                # back off: 60s, 120s, 240s ... capped at 30 min
                time_to_sleep = min(BACKOFF_START * (2 ** (consecutive_failures - 1)),
                                    BACKOFF_CAP)
                print("Backing off for " + str(int(time_to_sleep)) + "s before retrying")
            elif more_to_do:
                # healthy and there is work left: straight on to the next one
                time_to_sleep = 0
            else:
                try:
                    download_rss_feed()
                    download_mcm.main()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    print("feed/archive refresh failed:")
                    print(traceback.format_exc())
                tf = datetime.datetime.now()
                time_to_sleep = 3600.0 - (tf-t0).total_seconds()

            if time_to_sleep > 0.0:
                later = (datetime.datetime.now() + datetime.timedelta(seconds=time_to_sleep)).strftime("%Y-%m-%d %H:%M:%S")
                if not failed:
                    print("Done with all videos; checking again at " + later)
                time.sleep(time_to_sleep)

    else: 
        print("No video data file found after updating. Add channels to channels_to_transcribe.txt or ids to ids_to_transcribe.txt")
        sys.exit()

    # command to trim an audio file (0 to 300 seconds)
    # ffmpeg -i original.mp3 -ss 0 -to 300 trimmed.mp3