# pip install git+https://github.com/m-bain/whisperx.git
# also requires a "hugging face" token with permissions for 
# a couple libraries. See requirements here:
# https://huggingface.co/pyannote/speaker-diarization-3.1 
import whisperx
## to test hugging face token:
#from pyannote.audio import Pipeline
#with open('hf_token.txt') as f: token = f.readline()
#pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
#ipdb.set_trace()

# pip install yt_dlp
# also requires ffmpeg in your path (https://www.ffmpeg.org/download.html)
import yt_dlp 

# standard libraries 
import datetime, os
import ipdb
import json

'''
 download the Youtube audio at highest quality as an mp3
 yt_id   - youtube ID
 mp3file - name of mp3 to save
''' 
def download_audio(yt_id, mp3file):

	if os.path.isfile(mp3file): return 0

	url = "https://youtu.be/" + yt_id
	with yt_dlp.YoutubeDL() as ydl:
		info = ydl.extract_info(url, download=False)

	for format in info["formats"][::-1]:
		if format["resolution"] == "audio only" and format["ext"] == "m4a":
			audio_url = format["url"]
			break
	        
	ydl_opts = {
	    'format': 'bestaudio/best',
	    'outtmpl': os.path.splitext(mp3file)[0],
	    'postprocessors': [{
	        'key': 'FFmpegExtractAudio',
	        'preferredcodec': 'mp3',
	        'preferredquality': '320',
	    }],
	}

	with yt_dlp.YoutubeDL(ydl_opts) as ydl: 
	    return ydl.download(audio_url)

def generate_output(result, mp3file):
	base = os.path.splitext(mp3file)[0]
	subdir = os.path.dirname(mp3file)
	result["language"] = "en"
	yt_id = subdir

	# for testing
	if yt_id == "council30": yt_id = "kP4iRYobyr0"

	# output in all supported formats
	output_exts = ['vtt','srt','json','txt','tsv']
	for output_ext in output_exts:
		output_writer = whisperx.utils.get_writer(output_ext, subdir)
		output_writer(result, mp3file, {'max_line_width': None,'max_line_count': None,'highlight_words': False})

	# output custom html with links to corresponding parts of the youtube video
	f = open(base + '.html', 'w')
	f.write('<!DOCTYPE html>\n')
	f.write('<html lang="en">\n')
	f.write('  <head>\n')
	f.write('    <meta charset="UTF-8">\n')
	f.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
	f.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
	f.write('   <title>Transcript for ' + yt_id + '</title>\n')
	f.write('  </head>\n')
	f.write('  <body>\n')
	for segment in result["segments"]:
		if 'speaker' in segment.keys(): speaker = segment["speaker"]
		else: speaker = 'UNKOWN'
		f.write('    <a href="https://youtu.be/' + yt_id + '&t=' + str(segment["start"]) + 's">')
		f.write("[" + speaker + "]</a>: " + segment["text"] + "<br><br>\n\n")
	f.write('  </body>\n')
	f.write('</html>\n')
	f.close()

t0 = datetime.datetime.utcnow()

yt_id = "kP4iRYobyr0" # city council meeting 2024-10-15
yt_id = "council.0-60"
yt_id = "eYLl0XsNfvs"

# TODO: loop over every video on a channel
#url = "https://www.youtube.com/@CityofMedfordMass"

subdir = yt_id

base = os.path.join(subdir,yt_id)
mp3file = base + '.mp3'

# command to trim an audio file
# ffmpeg -i kP4iRYobyr0.mp3 -ss 0 -to 300 council5.mp3

error_code = download_audio(yt_id, mp3file)
print("Download complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

# whisperX options
device = "cpu" #"cuda" 
batch_size = 16 # reduce if low on GPU mem
#compute_type = "float16" # change to "int8" if low on GPU mem (may reduce accuracy)
compute_type = "int8" # float16 not supported on my machine (may reduce accuracy)
model_dir = "./"
model = whisperx.load_model("large-v2", device, compute_type=compute_type, download_root=model_dir, language="en")

# basic transcription
audio = whisperx.load_audio(mp3file)
result = model.transcribe(audio, batch_size=batch_size)
generate_output(result, base + '_basic.mp3')
print("Transcription complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

# delete model if low on GPU resources
# import gc; gc.collect(); torch.cuda.empty_cache(); del model

# align whisper output (generate word-level timestamps)
model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
aligned_result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
generate_output(aligned_result, base + '_aligned.mp3')
print("Alignment complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

# delete model if low on GPU resources
# import gc; gc.collect(); torch.cuda.empty_cache(); del model_a

# Assign speaker labels ("diarization")
with open('hf_token.txt') as f: token = f.readline()

diarize_model = whisperx.DiarizationPipeline(use_auth_token=token, device=device)

# add min/max number of speakers if known
diarize_segments = diarize_model(audio)
#diarize_segments = diarize_model(audio, min_speakers=min_speakers, max_speakers=max_speakers)
print("Diarization complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")

# segments are now assigned speaker IDs
diarize_result = whisperx.assign_word_speakers(diarize_segments, aligned_result)
generate_output(diarize_result, base + '.mp3')

diarize_unaligned_result = whisperx.assign_word_speakers(diarize_segments, result)
generate_output(diarize_unaligned_result, base + '_unaligned.mp3')

# let's do some stats by speaker
speakers = {}
for segment in diarize_result["segments"]:
	if 'speaker' in segment.keys(): speaker = segment["speaker"]
	else: speaker = 'UNKOWN'

	if not speaker in speakers.keys(): speakers[speaker] = {"words": {}}

	added_time = (segment["end"] - segment["start"])
	if "total_time" in speakers[speaker].keys(): speakers[speaker]["total_time"] += added_time
	else: speakers[speaker]["total_time"] = added_time

	added_words = 0
	for word in segment["text"].split():
		added_words += 1
		if word in speakers[speaker]["words"].keys(): speakers[speaker]["words"][word] += 1
		else: speakers[speaker]["words"][word] = 1

	if "total_words" in speakers[speaker].keys(): speakers[speaker]["total_words"] += added_words
	else: speakers[speaker]["total_words"] = added_words

with open(base + '.speakers.json', 'w') as fp:
    json.dump(speakers, fp)

print("Output complete. Took " + str((datetime.datetime.utcnow()-t0).total_seconds()) + " seconds")
ipdb.set_trace()