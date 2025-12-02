import json
import glob
from json import JSONDecodeError

with open("addresses.json", 'r') as fp:
    directory = json.load(fp)

with open("video_data.json", 'r') as fp:
    video_data = json.load(fp)

with open("meeting_types.json", 'r') as fp:
    meeting_types = json.load(fp)

with open("councilors.json", 'r') as fp:
    councilors = json.load(fp)

speaker_id_files = glob.glob("20??-??-??_???????????/speaker_ids.json")
for file in speaker_id_files:
    try:
        with open(file, 'r') as fp:
            speaker_ids = json.load(fp)
    except JSONDecodeError:
        print(file + " is corrupt")


# check for typos in the socials:
socials = ["website","email","facebook","instagram","twitter","linkedin","reddit","whatsapp","youtube","tiktok","pinterest","discord","github","bluesky","donate"]
for councilor in councilors.keys():
    for social in councilors[councilor].keys():
        if len(social) == 4 and social.isdigit(): continue # skip years
        if social == "phone": continue # I'm not posting phone numbers

        if social not in socials:
            print(councilor + ":" + social)
