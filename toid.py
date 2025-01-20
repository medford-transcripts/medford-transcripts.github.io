import glob, json
import ipdb

files = glob.glob("*/*.json")

all_speakers = []
speaker_count = {}

number_to_id = 0
for file in files:
    nspeakers = 0
    unidentified = 0

    with open(file, 'r') as fp:
        speaker_ids = json.load(fp)

    for key in speaker_ids.keys():

        if speaker_ids[key] not in speaker_count.keys():
            speaker_count[speaker_ids[key]] = 1
        else: speaker_count[speaker_ids[key]] += 1

        if "SPEAKER" in speaker_ids[key]:
            unidentified += 1
        nspeakers += 1
        if "SPEAKER" in key and "SPEAKER" not in speaker_ids[key]:
            all_speakers.append(speaker_ids[key])

    if unidentified > 0.9*nspeakers: 
        print(file + " not done (" + str(unidentified) + "/" + str(nspeakers) + " unidentified speakers)")
        number_to_id += 1

unique_speakers = list(set(all_speakers))
unique_speakers.sort()
#print(str(len(unique_speakers)) + " unique speakers")
#for person in unique_speakers:
#    print(person)

print(str(number_to_id) + " left to do")


print(json.dumps(speaker_count,indent=4))