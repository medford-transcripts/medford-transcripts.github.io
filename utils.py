import json, glob
import os, time, datetime
import dateutil.parser as dparser
import yt_dlp 

import ipdb

# ward geometry
from geopy.geocoders import Nominatim
from shapely.geometry import shape, Point


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

    #filtered_video_data = {
    #    k: v for k, v in video_data.items()
    #    if not v.get("skip", False)
    #}

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
        
def pick_date(entry):
    return (
        entry.get("date")
        or entry.get("upload_date")
        or "9999-99-99"
    )

def get_mp3filename(yt_id, video_data=None, local=False, external=False):
    audio_path_backup = "D:/medford-transcripts.github.io/audio/"
    audio_path = "audio/"

    if video_data is None:
        video_data = get_video_data()

    upload_date = video_data[yt_id]["upload_date"]


    base = upload_date + "_" + yt_id
    mp3_external = audio_path_backup + base + ".mp3"
    mp3_local = audio_path + base + ".mp3"

    if os.path.exists(mp3_external) or external: return mp3_external
    if os.path.exists(mp3_local) or local: return mp3_local
    return None 

def add_all_meeting_types(overwrite=False):
    video_data = get_video_data()

    update = False
    for yt_id in video_data.keys():

        meeting_type = get_meeting_type(video_data[yt_id])
        if "meeting_type" not in video_data[yt_id].keys():
            video_data[yt_id]["meeting_type"] = meeting_type            
            update = True

        if (meeting_type != video_data[yt_id]["meeting_type"] and overwrite) or (meeting_type != video_data[yt_id]["meeting_type"] and video_data[yt_id]["meeting_type"] is None):
            video_data[yt_id]["meeting_type"] = meeting_type            
            update = True            

    sorted_data = dict(
        sorted(
            video_data.items(),
            key=lambda item: (
                item[1].get("meeting_type") or "zzzz",
                pick_date(item[1]),
            )
        )
    )

    #nnone = 0
    #for yt_id in sorted_data.keys():
    #    if video_data[yt_id]["meeting_type"] is None: nnone += 1
    #    print(pick_date(video_data[yt_id]),  " | ", video_data[yt_id]["meeting_type"], " | ", video_data[yt_id]["channel"], " | ", video_data[yt_id]["title"])
    #
    #print(nnone)
    #print(len(video_data))

    if update:
        save_video_data(video_data)

def get_meeting_type_by_title(title):

    t = title.lower()
    with open("meeting_types.json", "r", encoding="utf-8") as fp:
        meeting_type_map = json.load(fp)

    # check against all keywords
    for meeting_type, keywords in meeting_type_map.items():
        if any(kw in t for kw in keywords):
            return meeting_type

def get_meeting_type(video):

    campaign_channels = ["Zac Bears","Dr. Lisa Kingsley","Justin Tseng for Medford","Matt Leming","Anna Callahan for Medford","Elect Aaron Olapade", "Invest in Medford", "ALL Medford"]
    news_channels = ["WCVB Channel 5 Boston","CBS Boston","NBC10 Boston"]

    if video["channel"].strip() in campaign_channels:
        return "Campaign"

    if video["channel"].strip() in news_channels:
        return "News"

    if video["channel"].strip() == "Medford Bytes":
        return "Medford Bytes"

    if video["channel"].strip() == "Medford Happenings":
        return "Medford Happenings"


    t = video["title"].lower()
    with open("meeting_types.json", "r", encoding="utf-8") as fp:
        meeting_type_map = json.load(fp)

    # some meetings can only be differentiated by channel and title
    if video["channel"].strip() == "Medford Public Schools":
        possible_meetings = ["MPS Meeting of the Whole","MPS Facilities","MPS Budget"]
        for possible_meeting in possible_meetings:
            keywords = meeting_type_map[possible_meeting]
            if any(kw in t for kw in keywords):
                return possible_meeting

    # now check the leftovers against all keywords
    for meeting_type, keywords in meeting_type_map.items():
        if any(kw in t for kw in keywords):
            return meeting_type

    return None

def identify_duplicate_videos(video_data=None, reset=False):

    if video_data is None:
        video_data = get_video_data()

    best_channels = ["City of Medford, Massachusetts","Medford Public Schools","Medford Community Media","MCM Archive","Mass Traction-US-Medford-1 - Government","Select Medford, MA City Meetings"]
    mtchannel ="Mass Traction-US-Medford-1 - Government"

    if reset: 
        for yt_id in video_data.keys():
            # even a reset won't overwrite manually corrected entries
            if "manual_correction" in video_data[yt_id].keys():
                if video_data[yt_id]["manual_correction"]: 
                    continue
            video_data[yt_id].pop('skip', None)
            video_data[yt_id].pop('duplicate_id', None)

    for yt_id in video_data.keys():

        if video_data[yt_id]["meeting_type"] is None:
            continue
        if video_data[yt_id]["meeting_type"] == "Campaign":
            continue

        for yt_id_trial in video_data.keys():

            # don't match to self
            if yt_id == yt_id_trial: continue

            # don't match to uncategorized meetings
            if video_data[yt_id_trial]["meeting_type"] is None:
                continue

            # don't match to campaign meetings
            if video_data[yt_id_trial]["meeting_type"] == "Campaign":
                continue


            # same type, same date, different channel => duplicate
            # same type, same date, channel == Mass Traction, one livestream => duplicate
            if (
                (
                    video_data[yt_id]["date"] == video_data[yt_id_trial]["date"]
                    and video_data[yt_id]["meeting_type"] == video_data[yt_id_trial]["meeting_type"]
                    and video_data[yt_id]["channel"] != video_data[yt_id_trial]["channel"]
                )
                or (
                    video_data[yt_id]["date"] == video_data[yt_id_trial]["date"]
                    and video_data[yt_id]["meeting_type"] == video_data[yt_id_trial]["meeting_type"]
                    and video_data[yt_id]["channel"] == mtchannel
                    and video_data[yt_id_trial]["channel"] == mtchannel
                    and (
                        "Livestream" in video_data[yt_id]["title"]
                        or "Livestream" in video_data[yt_id_trial]["title"]
                    )
                )
            ):
                try:
                    index = best_channels.index(video_data[yt_id]["channel"])
                except ValueError:
                    index = 10

                try:
                    trial_index = best_channels.index(video_data[yt_id_trial]["channel"])
                except ValueError:
                    trial_index = 10

                if (index < trial_index) or (index == trial_index and "Livestream" in video_data[yt_id_trial]["title"]):
                    video_data[yt_id]["duplicate_id"] = yt_id_trial
                    video_data[yt_id_trial]["duplicate_id"] = yt_id
                    video_data[yt_id_trial]["skip"] = True
                    #print(yt_id_trial)
                else:
                    video_data[yt_id_trial]["duplicate_id"] = yt_id
                    video_data[yt_id]["duplicate_id"] = yt_id_trial
                    video_data[yt_id]["skip"] = True                    
                    #print(yt_id)

                #if yt_id == "DSAvAI2oq28" or yt_id_trial == 'DSAvAI2oq28': ipdb.set_trace()

    #ipdb.set_trace()
    save_video_data(video_data)



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

# Function to get latitude and longitude
def get_lat_lon(address):
    geolocator = Nominatim(user_agent="medfordTranscripts/1.0")
    try:
        location = geolocator.geocode(address, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"Error geocoding {address}: {e}")
    return None

def address_to_ward(address, return_district=False):

    with open("medford_wards.geojson", "r") as f:
        wards = json.load(f)

    ward_geoms = []
    # Add text labels for each wards
    for feature in wards["features"]:
        geom = shape(feature["geometry"])
        ward = str(feature["properties"].get("WARD", "")).strip()
        precinct = str(feature["properties"].get("PRECINCT", "")).strip()
        label = f"{ward}-{precinct}"

        # these define the school committee districts
        if ward == "1" or ward == "7": district = "1/7" # East?
        if ward == "2" or ward == "3": district = "2/3" # North?
        if ward == "4" or ward == "5": district = "4/5" # South?
        if ward == "6" or ward == "8": district = "6/8" # West?

        ward_geoms.append(
            {
                "geom": geom,
                "ward": ward,
                "precinct": precinct,
                "ward_precinct": label,
                "district": district,
            }
        )

    lat_lon = get_lat_lon(address)
    if lat_lon is None: return None
    lat = lat_lon[0]
    lon = lat_lon[1]

    for w in ward_geoms:
        if w["geom"].contains(Point(lon, lat)):
            if return_district: return w["district"]
            return w["ward"]

    return None

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
            for channel in channels: 
                if channel[0] == '@':
                    update_channel(channel)

    # update every entry in video_data.json
    video_data = get_video_data()
    for yt_id in video_data.keys():
        update_video_data_one(yt_id)

    update_priority(newest=True)

'''
make a unique set of the councilors from councilors.json
'''
def get_councilors(jsonfile="councilors.json",mayor=False, city_council=False, school_committee=False, candidates=False, year=None, superintendents=False):
    with open(jsonfile, 'r') as fp:
        councilors = json.load(fp)
    return(list(set(councilors.keys())))

'''
make a unique set of the councilors in councilors.txt
'''
def get_councilors_old(file="councilors.txt",mayor=False, city_council=False, school_committee=False, candidates=False, year=None, superintendents=False):
    councilors = []
    with open(file,'r') as fp:
        for line in fp:
            entries = line.split("#")[0].strip().split(',')
            for entry in entries:
                if entry != '':
                    councilors.append(entry.strip())
    return list(set(councilors))