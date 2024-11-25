import glob, json

files = glob.glob("*/*.json")

number_to_id = 0
for file in files:
    nspeakers = 0
    unidentified = 0

    with open(file, 'r') as fp:
        speaker_ids = json.load(fp)

    for key in speaker_ids.keys():
        if "SPEAKER" in speaker_ids[key]:
            unidentified += 1
        nspeakers += 1

    if unidentified == nspeakers: 
        print(file + " not done (" + str(unidentified) + " unidentified speakers)")
        number_to_id += 1

print(str(number_to_id) + " left to do")