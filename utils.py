import json, glob
import os, time, datetime
import dateutil.parser as dparser
import yt_dlp 

'''
return all the metadata for the videos stored in video_data.json
update the creation date.
'''
def get_video_data(jsonfile='video_data.json'):

    # read info
    if os.path.exists(jsonfile):
        while os.path.exists('video_data.lock'):
            time.sleep(1)
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else: video_data = {}

    return video_data

'''
Save updates to the video metadata back to the json file
Do it in a thread-safe way to avoid corruption 
of the metadata from simultaneous processes
'''
def save_video_data(video_data, jsonfile='video_data.json'):

    # wait until the lock is gone
    while os.path.exists('video_data.lock'):
        time.sleep(1)

    # create new lock
    with open("video_data.lock", "w") as file:
        file.write("lock")

    # save the data
    with open(jsonfile, "w") as fp:
        json.dump(video_data, fp, indent=4)

    os.remove("video_data.lock")

''' 
Update video_data.json with info from yt_id
'''
def update_video_data_one(yt_id):
    video_data = get_video_data()

    if yt_id not in video_data.keys(): 
        video_data[yt_id] = {}

    required_keys = ["upload_date","channel","title","duration","view_count","date"]
    if not all(key in video_data[yt_id].keys() for key in required_keys):
        url = "https://youtu.be/" + yt_id
        with yt_dlp.YoutubeDL() as ydl:
            try:
                info = ydl.extract_info(url, download=False)

                video_data[yt_id]["title"] = info["title"]
                video_data[yt_id]["channel"] = info["channel"]
                video_data[yt_id]["duration"] = info["duration"]

                # links and a bunch of stuff are built around the upload date, and it sometimes changes (I think livestreams update when finished). Don't update it or things break!
                if "upload_date" not in video_data[yt_id].keys():
                    video_data[yt_id]["upload_date"] = datetime.datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")

                video_data[yt_id]["view_count"] = info["view_count"]
                #video_data[yt_id]["last_update"] = 0.0

                now = datetime.datetime.now()

                # get the date of the video use:
                # 1) date in video_data
                # 2) date parsed from title
                # 3) upload date
                # 4) current date
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
                        #print('No parsable date in title of "' + video_data[yt_id]["title"] + '"')
                        pass

                if "date" in video_data[yt_id].keys():
                    # you can hand edit the date in the video_data.json file for ones that fail to parse
                    date = datetime.datetime.strptime(video_data[yt_id]["date"],'%Y-%m-%d')

                video_data[yt_id]["date"] = date.strftime("%Y-%m-%d")  

                # update video_data
                save_video_data(video_data)
            except:
                print(yt_id + " not ready yet")

    if "agenda" not in video_data[yt_id].keys():
        agendas = glob.glob("agendas/*.pdf") 
        


'''
sorts the meta data by a variety of prioritization schemes (default newest)
'''
def update_priority(newest=False, oldest=False, popularity=False, exp_decay=False, 
    linear_decay=True, shortest=False, longest=False):

    video_data = get_video_data()

    now = datetime.datetime.now()
    priority = []
    halflife = 90.0
    for yt_id in video_data.keys():
        if "view_count" in video_data[yt_id].keys(): 
            views = video_data[yt_id]["view_count"]
        else: views = 0

        date = datetime.datetime.strptime(video_data[yt_id]["date"],'%Y-%m-%d')
        age = (now - date).total_seconds()/86400.0

        if "duration" in video_data[yt_id].keys():
            duration = video_data[yt_id]["duration"]
        else: duration = 7200.0 # default to 2 hours

        # ad hoc prioritization scheme based on popularity, age, and/or duration
        if newest:
            # prioritize by age (newest first)
            priority.append(1.0/age)
        elif oldest:
            # prioritize by age (oldest first)
            priority.append(age)
        elif popularity:
            # prioritize by popularity
            priority.append(views)
        elif exp_decay:
            # exponential decay penalizes old videos too strongly or doesn't weight new ones strongly enough
            priority.append(views*math.exp(-math.log(2.0)*age/halflife))
        elif linear_decay:
            # linear decay weakly penalizes old videos
            priority.append((views+100)*100/age)
        elif shortest:
            # prioritize shortest videos first
            priority.append(1.0/duration)
        elif longest:
            # prioritize longest videos first
            priority.append(duration)           

    # sort video_data by priority (equivalent to np.argsort)
    sort_ndx = reversed(sorted(range(len(priority)), key=priority.__getitem__))
    yt_ids = list(video_data.keys())
    sorted_dict = {}
    for k in sort_ndx:
        sorted_dict[yt_ids[k]] = video_data[yt_ids[k]]
        sorted_dict[yt_ids[k]]["priority"] = priority[k]

    save_video_data(sorted_dict)

'''
update the video_data for an entire channel
'''
def update_channel(channel):

    video_data = get_video_data()
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
                        update_video_data_one(entry["id"])
                    except Exception as error:
                        print("Failed on " + entry["id"])
                        print(error)
                        print(traceback.format_exc())
        else:
            # this captures channels with only one video type (?)
            # I think "playlist" is actually a video
            try:
                update_video_data_one(playlist["id"])
            except Exception as error:
                print("Failed on " + playlist["id"])
                print(error)
                print(traceback.format_exc())

''' 
update the meta data for all videos
'''
def update_all(channel_file="channels_to_transcribe.txt", id_file="ids_to_transcribe.txt"):

    # update video data for videos already transcribed
    transcribed_files = glob.glob("*/20??-??-??_???????????.srt")
    for file in transcribed_files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        update_video_data_one(yt_id)

    # update video data for files in id_file
    if os.path.exists(id_file):
        with open(id_file) as f:
            yt_ids = f.read().splitlines()
        for yt_id in yt_ids:
            update_video_data_one(yt_id)

    # update video data for all channels
    if os.path.exists(channel_file):
        with open(channel_file) as f:
            channels = f.read().splitlines()
            # loop through every video on these channels
            for channel in channels: update_channel(channel)

    # update every entry in video_data.json
    video_data = get_video_data()
    for yt_id in video_data.keys():
        update_video_data_one(yt_id)

    update_priority(newest=True)

'''
make a unique set of the councilors in councilors.txt
'''
def get_councilors(file="councilors.txt",mayor=False, city_council=False, school_committee=False, candidates=False, year=None, superintendents=False):
    councilors = []
    with open(file,'r') as fp:
        for line in fp:
            entries = line.split("#")[0].strip().split(',')
            for entry in entries:
                if entry != '':
                    councilors.append(entry.strip())
    return list(set(councilors))