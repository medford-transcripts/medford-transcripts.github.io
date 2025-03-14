import glob, json
import ipdb
import re

files = glob.glob("*/speaker_ids.json")

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

# pattern to match a cross matched speaker: ???????????_SPEAKER_??
pattern = r"^.{11}_SPEAKER_.{2}$"
pattern2 = r"SPEAKER_.{2}$"


# Sort speaker_count by its count to prioritize output
sorted_speaker_count = dict(sorted(speaker_count.items(), key=lambda item: (item[1], item[0])))

print()
nunique = 0
nunidentified = 0
ntotal = 0
nunmatched = 0

print("The following speakers have been automatically cross matched from multiple videos, but are unidentified:")
for speaker in sorted_speaker_count.keys():
    if re.match(pattern,speaker):
        print((speaker, sorted_speaker_count[speaker]))
        nunidentified += (sorted_speaker_count[speaker]+1)
        nunmatched -= 1
        nunique += 1
    ntotal += sorted_speaker_count[speaker]
    if re.match(pattern2,speaker):
        nunmatched += sorted_speaker_count[speaker]

print("unique matched, unidentified speakers: " + str(nunique))
print("total matched (but unidentified) speakers: " + str(nunidentified))
print("total unmatched speakers: " + str(nunmatched))
print("total speakers: " + str(ntotal))

#print(json.dumps(speaker_count,indent=4))