import json, os
import datetime

jsonfile = 'video_data.json'
with open(jsonfile, 'r') as fp:
	video_data = json.load(fp)

time = 0
nvideos = 0
ndownloaded = 0
time_downloaded = 0
nrequested = 0
time_requested = 0

for video in video_data.keys(): 
	if "duration" in video_data[video].keys():

		# requested
		time_requested += video_data[video]["duration"]
		nrequested += 1

		dirname = video_data[video]["upload_date"] + "_" + video
		base = os.path.join(dirname,dirname)

		# downloaded
		mp3file = base + '.mp3'
		if os.path.exists(mp3file):
			time_downloaded += video_data[video]["duration"]
			ndownloaded +=1

		# transcribed
		srtfile = base + '.srt'
		if os.path.exists(srtfile):
			time += video_data[video]["duration"]
			nvideos += 1			

print(str(round(time_requested/86400,2)) + " days of (" + str(nrequested) + ") videos requested")
print(str(round(time_downloaded/86400,2)) + " days of (" + str(ndownloaded) + ") videos downloaded")
print(str(round(time/86400,2)) + " days of (" + str(nvideos) + ") videos transcribed")
print()

started = datetime.datetime(2024,10,26)
now = datetime.datetime.now()
elasped_time = (now-started).total_seconds()
print("It takes " + str(round(elasped_time/time,2)) + " hours to transcribe an hour of video")
print("Will finish remaining videos on " + str(started + datetime.timedelta(seconds=elasped_time*time_requested/time)))
