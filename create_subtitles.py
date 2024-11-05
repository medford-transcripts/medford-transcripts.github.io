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
import datetime, os, glob, argparse
import json

##### test hugging face token #####
#from pyannote.audio import Pipeline
#with open('hf_token.txt') as f: token = f.readline()
#pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
#ipdb.set_trace()
###################################

'''
 download the Youtube audio at highest quality as an mp3
 yt_id   - youtube ID
''' 
def download_audio(yt_id, dir=None):

    # read info
    jsonfile = 'video_data.json'
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else: video_data = {}
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
    if download_only: return

    # skip files that are already done
    files = glob.glob("*/*_" + yt_id + ".srt")
    if len(files) != 0 and not redo: 
        print("Already done with " + yt_id + " (" + files[0] + "). Set redo=True to redo transcription")
        return

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

def transcribe_entry(entry, download_only=False, id_file="ids_to_transcribe.txt", redo=False):

    # putting this here makes it possible to queue new videos without interrupting
    if os.path.exists(id_file):
        with open(opt.id_file) as f:
            yt_ids = f.read().splitlines()
        for yt_id in yt_ids:
            # only do it if the mp3 file already exists
            # assumes we have a parallel download script running
            mp3files = glob.glob("*/*" + yt_id + '.mp3')
            if (download_only != (len(mp3files) == 1)): # xor
                try:
                    transcribe(yt_id, download_only=download_only, redo=redo)
                except:
                    pass

    yt_id = entry["display_id"]
    # don't let hiccups halt progress
    # Move to next video and we can clean up later
    try: 
        transcribe(yt_id, download_only=download_only, redo=redo)
    except KeyboardInterrupt:
        print('Interrupted')
        ipdb.set_trace()
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
    parser.add_argument('-c','--channel-file', dest='channel_file', help='filename containing a list of channels, transcribe all videos')
    parser.add_argument('-i','--youtube-id-file', dest='id_file', help='filename containing a list of YouTube IDs to transcribe')
    opt = parser.parse_args()

    # command to trim an audio file (0 to 300 seconds)
    # ffmpeg -i original.mp3 -ss 0 -to 300 trimmed.mp3

 #   # prioritize videos by specifying youtube IDs (one per line) in priority_videos.txt
 #   if os.path.exists(opt.id_file):
 #       with open(opt.id_file) as f:
 #           yt_ids = f.read().splitlines()
 #       for yt_id in yt_ids:
 #           transcribe(yt_id, download_only=opt.download_only)

    if os.path.exists(opt.channel_file):
        with open(opt.channel_file) as f:
            channels = f.read().splitlines()

        # loop through every video on these channels
        # it does regular videos, streams, then shorts
        for channel in channels:
            url = "https://www.youtube.com/" + channel 
            info = yt_dlp.YoutubeDL().extract_info(url, download=False) 

            # the structure of "info" varies depending on how many playlists (live stream, short, etc)
            if "display_id" in info["entries"][0].keys():
                for entry in info["entries"]:
                    transcribe_entry(entry, download_only=opt.download_only, id_file=opt.id_file, redo=opt.redo)
            else:
                for playlist in info["entries"]:
                    for entry in playlist["entries"]:
                        transcribe_entry(entry, download_only=opt.download_only, id_file=opt.id_file, redo=opt.redo)
