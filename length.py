import json, os, glob
import datetime
import ipdb
import dateutil.parser as dparser


jsonfile = 'video_data.json'
with open(jsonfile, 'r') as fp:
    video_data = json.load(fp)

time = 0
nvideos = 0
ndownloaded = 0
time_downloaded = 0
nrequested = 0
time_requested = 0

srtfiles = glob.glob("*/20??-??-??_???????????.srt")

now = datetime.datetime.now()
latest_date = datetime.datetime(2000,1,1)

for video in video_data.keys(): 


    if "duration" in video_data[video].keys():

        date = now
        if "upload_date" in video_data[video].keys():
            date = datetime.datetime.strptime(video_data[video]["upload_date"],'%Y-%m-%d')

        if "title" in video_data[video].keys():
            try: 
                create_date = dparser.parse(video_data[video]["title"],fuzzy=True)
                # sometimes the parser guesses too much. It can't be later the upload date
                if date > create_date:
                    date = create_date
            except:
                pass

        if "date" in video_data[video].keys():
            # you can hand edit the date in the video_data.json file for ones that fail to parse
            date = datetime.datetime.strptime(video_data[video]["date"],'%Y-%m-%d')

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
            if srtfile in srtfiles:
                ndx = srtfiles.index(srtfile)
                srtfiles[ndx] = ''
        else:
            if date > latest_date:
                latest_date = date
                latest_video = video

    else:
        print(video + " not found in video_data")   

print(str(round(time_requested/86400,2)) + " days of (" + str(nrequested) + ") videos requested")
print(str(round(time_downloaded/86400,2)) + " days of (" + str(ndownloaded) + ") videos downloaded")
print(str(round(time/86400,2)) + " days of (" + str(nvideos) + ") videos transcribed")
print()

started = datetime.datetime(2024,10,26)
now = datetime.datetime.now()
elasped_time = (now-started).total_seconds()
print("It takes " + str(round(elasped_time/time,2)) + " hours to transcribe an hour of video")
print("Will finish remaining videos on " + str(started + datetime.timedelta(seconds=elasped_time*time_requested/time)))
print("Done with all videos up until " + datetime.datetime.strftime(latest_date,'%Y-%m-%d') + " (" + latest_video + ")")

#print(srtfiles)
#ipdb.set_trace()