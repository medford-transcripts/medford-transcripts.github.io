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
import datetime, os, glob

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

    files = glob.glob('*' + yt_id + '*/*' + yt_id + '*.mp3')
    if len(files) == 1: return files[0]

    url = "https://youtu.be/" + yt_id
    with yt_dlp.YoutubeDL() as ydl:
        info = ydl.extract_info(url, download=False)

    for format in info["formats"][::-1]:
        if format["resolution"] == "audio only" and format["ext"] == "m4a":
            audio_url = format["url"]
            break
    
    timestamp = datetime.datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")
    title = info["title"].replace(" ","_").replace("#","").replace(",","").replace('"','')
    if dir==None:
        dir = timestamp + "_" + yt_id #+ "_" + title.lower()

    mp3file = os.path.join(dir,dir) +'.mp3'
    if os.path.isfile(mp3file): return mp3file

    if not os.path.exists(dir): os.makedirs(dir)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(dir,dir),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl: 
        ydl.download(audio_url)
        return mp3file

def generate_output(result, mp3file):
    subdir = os.path.dirname(mp3file)
    result["language"] = "en"
    output_writer = whisperx.utils.get_writer("srt", subdir)
    output_writer(result, mp3file, {'max_line_width': None,'max_line_count': None,'highlight_words': False})
    return

def transcribe(yt_id, min_speakers=None, max_speakers=None, redo=False, download_only=False):

    # skip files that are already done
    files = glob.glob("*/*_" + yt_id + ".srt")
    if len(files) != 0 and not redo: 
        print("Already done with " + yt_id + " (" + files[0] + "). Set redo=True to force transcription")
        return

    t0 = datetime.datetime.utcnow()

    mp3file = download_audio(yt_id)
    base = os.path.splitext(mp3file)[0]
    subdir = os.path.dirname(mp3file)
    print("Download complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
    if download_only: return

    # whisperX options
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16" # change to "int8" if low on GPU mem (may reduce accuracy)
    else:
        device = "cpu"
        compute_type = "int8"

    batch_size = 16 # reduce if low on GPU mem
    model_dir = "./"
    model = whisperx.load_model("large-v3", device, compute_type=compute_type, download_root=model_dir, language="en")

    # basic transcription
    audio = whisperx.load_audio(mp3file)
    result = model.transcribe(audio, batch_size=batch_size)
    generate_output(result, base + '_basic.mp3')
    print("Transcription complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # delete model if low on GPU resources
    # import gc; gc.collect(); torch.cuda.empty_cache(); del model

    # align whisper output (generate accurate word-level timestamps)
    model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    aligned_result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
    generate_output(aligned_result, base + '_aligned.mp3')
    print("Alignment complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # delete model if low on GPU resources
    # import gc; gc.collect(); torch.cuda.empty_cache(); del model_a

    # Assign speaker labels ("diarization")
    with open('hf_token.txt') as f: token = f.readline()
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=token, device=device)
    diarize_segments = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers)
    print("Diarization complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

    # segments are now assigned speaker IDs
    diarize_result = whisperx.assign_word_speakers(diarize_segments, aligned_result)
    generate_output(diarize_result, base + '.mp3')

    print("Output complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

def transcribe_entry(entry, download_only=False):
    yt_id = entry["display_id"]
    # don't let hiccups halt progress
    # Move to next video and we can clean up later
    try: 
        transcribe(yt_id, download_only=download_only)
    except: pass

if __name__ == "__main__":

    # downloads are heavily throttled by YouTube (~32 KiB/s) 
    # but we can download future videos while transcribing this one
    # set to True to only download audio files for all channels
    download_only = False

    # command to trim an audio file (0 to 300 seconds)
    # ffmpeg -i kP4iRYobyr0.mp3 -ss 0 -to 300 kP4iRYobyr0.0-5.mp3

    # prioritize videos by specifying youtube IDs (one per line) in priority_videos.txt
    with open('priority_videos.txt') as f:
        yt_ids = f.read().splitlines()
    for yt_id in yt_ids:
        transcribe(yt_id, download_only=download_only)

    # loop through every video on these channels
    # it does regular videos, streams, then shorts
    channels = ["@medfordpublicschools464","@CityofMedfordMass","@InvestinMedford","@ALLMedford"]
    for channel in channels:
        url = "https://www.youtube.com/" + channel 
        info = yt_dlp.YoutubeDL().extract_info(url, download=False) 

        # the structure of "info" varies depending on how many playlists (live stream, short, etc)
        if "display_id" in info["entries"][0].keys():
            for entry in info["entries"]:
                transcribe_entry(entry, download_only=download_only)
        else:
            for playlist in info["entries"]:
                for entry in playlist["entries"]:
                    transcribe_entry(entry, download_only=download_only)
