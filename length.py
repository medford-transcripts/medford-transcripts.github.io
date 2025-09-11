import json, os, glob
import datetime
import ipdb
import dateutil.parser as dparser
import utils

import create_subtitles

time_by_year_sc = {}
time_by_year_cc = {}
number_by_year_sc = {}
number_by_year_cc = {}

video_data = utils.get_video_data()

time = 0
nvideos = 0
ndownloaded = 0
time_downloaded = 0
nrequested = 0
time_requested = 0

srtfiles = glob.glob("*/20??-??-??_???????????.srt")

now = datetime.datetime.now()
latest_date = datetime.datetime(1900,1,1)
latest_video = ""

for video in video_data.keys(): 

    date = datetime.datetime.strptime(video_data[video]["date"],'%Y-%m-%d')

    if "duration" not in video_data[video].keys():
        print(video + " not found in video_data") 
        continue

    year = date.strftime('%Y')


    if date < datetime.datetime(2000,1,1): print((date,video))
    title = video_data[video]["title"]

    #if "City Council" in video_data[video]["title"]:
    if (video_data[video]["channel"] == "City of Medford, Massachusetts") and "City Council" in video_data[video]["title"]:
        if year not in time_by_year_cc.keys(): 
            time_by_year_cc[year] = 0
            number_by_year_cc[year] = 0
        time_by_year_cc[year] += video_data[video]["duration"]/3600.0
        number_by_year_cc[year] += 1
    elif (video_data[video]["channel"] == "Medford Public Schools" or video_data[video]["channel"] == "City of Medford, Massachusetts") and \
        ("ommittee" in title or "eeting" in title or "MSC" in title):
        if year not in time_by_year_sc.keys(): time_by_year_sc[year] = 0
        if year not in number_by_year_sc.keys(): number_by_year_sc[year] = 0
        time_by_year_sc[year] += video_data[video]["duration"]/3600.0
        number_by_year_sc[year] += 1
    else:
        pass
        #print('"' + title + '"'+ " not a meeting video")
        #if (video_data[video]["channel"] == "Medford Public Schools"): ipdb.set_trace()

    # requested
    time_requested += video_data[video]["duration"]
    nrequested += 1

    dirname = video_data[video]["upload_date"] + "_" + video
    base = os.path.join(dirname,dirname)

    # downloaded
    mp3file = base + '.mp3'
    if create_subtitles.mp3_is_good(video,video_data):
    #if os.path.exists(mp3file):
        time_downloaded += video_data[video]["duration"]
        ndownloaded +=1
    elif os.path.exists(mp3file):
        print(video + ": mp3file exists but is not acceptable for transcription")
    else:
        print(video + ": not yet downloaded")

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


print(str(round(time_requested/86400,2)) + " days of (" + str(nrequested) + ") videos requested")
print(str(round(time_downloaded/86400,2)) + " days of (" + str(ndownloaded) + ") videos downloaded")
print(str(round(time/86400,2)) + " days of (" + str(nvideos) + ") videos transcribed")
print()

started = datetime.datetime(2024,10,26)
now = datetime.datetime.now()
elasped_time = (now-started).total_seconds()
print("It takes " + str(round(elasped_time/time,2)) + " hours to transcribe an hour of video")

if latest_video != "":
    print("Will finish remaining videos on " + str(started + datetime.timedelta(seconds=elasped_time*time_requested/time)))
    print("Done with all videos up until " + datetime.datetime.strftime(latest_date,'%Y-%m-%d') + " (" + latest_video + ")")
else: 
    print("Done with all videos")

verbose = False
if verbose:
    print()
    print("City Council")
    for year in sorted(time_by_year_cc.keys()):
        print(year + ' ' + str(round(time_by_year_cc[year],2)) + ' ' + str(number_by_year_cc[year]))

    print()
    print("School committee")
    for year in sorted(time_by_year_sc.keys()):
        print(year + ' ' + str(round(time_by_year_sc[year],2)) + ' ' + str(number_by_year_sc[year]))

#print(dict(sorted(time_by_year_cc.items())))
#print(dict(sorted(time_by_year_sc.items())))

#print(srtfiles)
#ipdb.set_trace()