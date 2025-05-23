import glob, os
import pickle, json

import ipdb

# compute the cosine similarity of embeddings
#from scipy.spatial.distance import cosine
from scipy.stats import wasserstein_distance
# this is a massive dependency for a simple task
# TODO: compute myself

import numpy as np
import utils

'''
compute the cosine similarity of two vectors
used to evaluate the similarity of two embeddings (speakers)

1 => perfect agreement
0 => no correlation
-1 => anti-correlated

> 0.7 is a good threshold for identifying the same speaker
'''
def cosine(vector1, vector2):
    dot_product = np.dot(vector1, vector2)
    norm1 = np.linalg.norm(vector1)
    norm2 = np.linalg.norm(vector2)
    if norm1 == 0.0 or norm2 == 0.0: return 0
    #print((norm1, norm2))

    return dot_product / (norm1 * norm2)

def distance(vector1, vector2):
    return np.sqrt(np.sum((vector1-vector2)**2))

'''
This will propagate manual identifications throughout the speaker_id.json files
'''
def propagate():
    files = glob.glob("*/speaker_ids.json")

    # propagate updates in the referenced files
    for file in files:
        update = False

        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]

        # read iexit(n the speaker mappings
        with open(file, 'r') as fp:
            speaker_ids = json.load(fp)

        #print(yt_id)
        #print(json.dumps(speaker_ids, indent=4))

        for speaker in speaker_ids.keys():

            # reference to another file's ID, grab its (updated?) ID
            if len(speaker_ids[speaker]) > 12:
                if speaker_ids[speaker][11] == "_":
                    mapped_yt_id = speaker_ids[speaker][:11]
                    mapped_speaker = speaker_ids[speaker][12:]

                    #print((speaker_ids[speaker], mapped_yt_id, mapped_speaker))

                    # read in the speaker mappings
                    mapped_file = glob.glob('*' + mapped_yt_id + '/speaker_ids.json')
                    if len(mapped_file) == 1: 
                        with open(mapped_file[0], 'r') as fp:
                            mapped_ids = json.load(fp)

                        # if it's been updated, propagate it
                        if mapped_ids[mapped_speaker] != mapped_speaker:
                            speaker_ids[speaker] = mapped_ids[mapped_speaker]
                            update = True

        if update:
            with open(file, "w") as fp:
                json.dump(speaker_ids, fp, indent=4)

    return

def change_name(old_name,new_name):
    jsonfiles = glob.glob("*/speaker_ids.json")
    for jsonfile in jsonfiles:
        updated = False

        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)

        for speaker_id in speaker_ids.keys():
            if old_name == speaker_ids[speaker_id]:
                speaker_ids[speaker_id] = new_name
                print("Changing name in " + jsonfile)
                updated = True

        if updated:
            with open(jsonfile, "w") as fp:
                json.dump(speaker_ids, fp, indent=4)


def standardize_speakers():
    with open("addresses.json", 'r') as fp:
        directory = json.load(fp)

    jsonfiles = glob.glob("*/speaker_ids.json")
    for jsonfile in jsonfiles:
        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)

        for speaker_id in speaker_ids.values():
            if (speaker_id not in directory.keys()) and ("SPEAKER_" not in speaker_id):
                print(speaker_id)
                #match_to_speaker(speaker_id)
                #ipdb.set_trace()
                directory[speaker_id] = ""

    # Sort the directory by last name, then first name
    sorted_directory = dict(sorted(directory.items(),
        key=lambda item: (item[0].split()[-1], item[0].split()[0])
    ))


    # save the new directory
    with open("addresses2.json", "w") as fp:
        json.dump(sorted_directory, fp, indent=4)


    ipdb.set_trace()
    for speaker_id in directory.keys():
        match_to_speaker(speaker_id)

# finds all matches to a particular speaker by name with a specified threshold, both the new files and back ported embeddings.
# if they're not the same, set update_json to update matched value to the supplied value
# be careful about threshholds! it's wise to do a dry run first!
def match_to_speaker(speaker, threshold=0.75, voices_folder='voices_folder', update_json=False, only_print_updates=False, noisy_embedding=0.15):
    pklfiles = glob.glob(voices_folder + '/*.pkl') # embeddings made after the fact
    pklfiles2 = glob.glob("*/embeddings.pkl") # embeddings made during transcription

    embeddings = []
    stdevs = []
    speaker_ids = []
    speaker_keys = []
    yt_ids = []

    # embeddings made after the fact
    for pklfile1 in pklfiles:
        with open(pklfile1,'rb') as fp: 
            embedding1 = pickle.load(fp)
        if len(embedding1) == 0: continue

        stdev = np.std(embedding1.embeddings[0])
        if stdev < noisy_embedding: continue

        speaker_num1 = '_'.join(os.path.splitext(os.path.basename(pklfile1))[0].split('_')[-2:])
        yt_id1 = '_'.join(os.path.splitext(os.path.basename(pklfile1))[0].split('_')[:-2])

        jsonfile = glob.glob('*' + yt_id1 + '*/speaker_ids.json')[0]
        with open(jsonfile, 'r') as fp:
            speaker_ids1 = json.load(fp)
        speaker_id1 = speaker_ids1[speaker_num1]

        # embeddings made during transcription
        embeddings.append(embedding1.embeddings[0])
        yt_ids.append(yt_id1)
        speaker_ids.append(speaker_id1)
        speaker_keys.append(speaker_num1)
        stdevs.append(stdev)

    # embeddings made during transcription
    for pklfile2 in pklfiles2:
        with open(pklfile2,'rb') as fp: 
            embeddings2 = pickle.load(fp)

        dir = os.path.dirname(pklfile2)
        yt_id2 = '_'.join(dir.split('_')[1:]).split('\\')[0]

        # read in the speaker mappings
        jsonfile = os.path.join(dir,'speaker_ids.json')
        if not os.path.exists(jsonfile): continue        
        with open(jsonfile, 'r') as fp:
            speaker_ids2 = json.load(fp)

        # loop over all speakers for this video
        for i, embedding in enumerate(embeddings2.embeddings):

            stdev = np.std(embedding)
            if stdev < noisy_embedding: continue

            if embeddings2.speaker[i] not in speaker_ids2.keys(): continue

            embeddings.append(embedding)
            yt_ids.append(yt_id2)
            speaker_id2 = speaker_ids2[embeddings2.speaker[i]]
            speaker_ids.append(speaker_id2)
            speaker_keys.append(embeddings2.speaker[i])
            stdevs.append(stdev)

    # now compare the complete list of speakers with each other
    for i in range(len(yt_ids)):
        if speaker_ids[i] != speaker: continue # skip it if doesn't match the requested speaker
        for j in range(len(yt_ids)):
            # don't need to compare A to B and B to A
            if (j <= i) and (speaker_ids[j] == speaker): continue

            score = cosine(embeddings[i], embeddings[j])
            if score > threshold:

                if not only_print_updates or (speaker_ids[i] != speaker_ids[j]): 
                    print(yt_ids[i] + " (" + str(round(stdevs[i],2)) + "): " + speaker_ids[i] + " matches " + speaker_ids[j] + " of " + yt_ids[j] + " (" + str(round(score,3)) + ")")

                # if they're not the same and updates were requested, update matched value to the supplied value
                # be careful about threshholds! it's wise to do a dry run first!
                if (speaker_ids[i] != speaker_ids[j]) and update_json:

                    jsonfile = (glob.glob('*' + yt_ids[j] + "/speaker_ids.json"))[0]
                    with open(jsonfile, 'r') as fp:
                        these_speaker_ids = json.load(fp)
                    these_speaker_ids[speaker_keys[j]] = speaker
                    with open(jsonfile, "w") as fp: 
                        json.dump(these_speaker_ids, fp, indent=4)
                    speaker_ids[j] = speaker

def match_to_reference3(embeddings=None, threshold=0.7, yt_id=None, voices_folder='voices_folder'):

    if embeddings == None: 
        embeddings = get_embeddings()

    keys = list(embeddings.keys())
    for i in enumerate(keys):
        embedding1 = embeddings[keys[i]]
        best_score = 0.0
        for j in enumerate(keys):
            if j <= i: continue
            embedding2 = embeddings[keys[j]]

            try:
                score = cosine(embedding1["embeddings"], embedding2["embeddings"])
            except:
                score = 0.0

            if score > threshold and score > best_score:
                best_score = score
                best_match = j

        if best_score > threshold:
            with open(jsonfiles[best_match], 'r') as fp:
                speaker_ids2 = json.load(fp)


# this matches to the old-style embeddings extracted after the fact by my modified version of whisperx
def match_to_reference2(threshold=0.7, yt_id=None, voices_folder='voices_folder'):

    pklfiles = glob.glob(voices_folder + '/*.pkl')
    embeddings = []
    speakers = []
    yt_ids = []
    jsonfiles = []
    goodpklfiles = []
    stdevs = []
    ranges = []

    for pklfile in pklfiles:
        with open(pklfile,'rb') as fp: 
            these_embeddings = pickle.load(fp)

        if len(these_embeddings) == 0: continue

        # this is a signature of noisy embeddings (untrustworthy diarization) skip automatic IDs
        if np.std(these_embeddings.embeddings[0]) < 0.1: continue


        #print((pklfile, np.std(these_embeddings.embeddings[0]), np.max(these_embeddings.embeddings[0])-np.min(these_embeddings.embeddings[0])) )
        #stdevs.append(np.std(these_embeddings.embeddings[0]))
        #ranges.append( np.max(these_embeddings.embeddings[0])-np.min(these_embeddings.embeddings[0]) )

        embeddings.append(these_embeddings)

        speaker = '_'.join(os.path.splitext(os.path.basename(pklfile))[0].split('_')[-2:])
        yt_id = '_'.join(os.path.splitext(os.path.basename(pklfile))[0].split('_')[:-2])

        yt_ids.append(yt_id)
        speakers.append(speaker)
        jsonfiles.append(glob.glob('*' + yt_id + '*/speaker_ids.json')[0])
        goodpklfiles.append(pklfile)


    #import matplotlib.pyplot as plt
    #plt.hist(stdevs, bins=30, color='skyblue', edgecolor='black')
    #plt.show()

    #plt.hist(ranges, bins=30, color='skyblue', edgecolor='black')
    #plt.show()

    #ipdb.set_trace()

    nfiles = len(goodpklfiles)
    score = np.zeros((nfiles,nfiles))
    for i,embedding1 in enumerate(embeddings):
        update1 = False
        best_score = 0.0

        with open(jsonfiles[i], 'r') as fp:
            speaker_ids1 = json.load(fp)

        for j,embedding2 in enumerate(embeddings):
            if i == j: continue

            try:
                score = cosine(embedding1.embeddings[0], embedding2.embeddings[0])
            except:
                score = 0.0
            if score > threshold and score > best_score:
                best_score = score
                best_match = j

        if best_score > threshold:
            with open(jsonfiles[best_match], 'r') as fp:
                speaker_ids2 = json.load(fp)

            if speaker_ids1[speakers[i]][0:8] == "SPEAKER_":
                if speaker_ids2[speakers[best_match]][0:8] != "SPEAKER_":
                    if speaker_ids2[speakers[best_match]] != yt_ids[i] + "_" + speaker_ids1[speakers[i]]:
                        speaker_ids1[speakers[i]] = speaker_ids2[speakers[best_match]]
                        update1 = True
                else:
                    speaker_ids1[speakers[i]] = yt_ids[best_match] + "_" + speaker_ids2[speakers[best_match]]
                    update1 = True
            else:
                if speaker_ids2[speakers[best_match]][0:8] == "SPEAKER_":
                    if speaker_ids1[speakers[i]] != yt_ids[best_match] + "_" + speaker_ids2[speakers[best_match]]:
                        #ipdb.set_trace()
                        speaker_ids2[speakers[best_match]] = speaker_ids1[speakers[i]]
                        with open(jsonfiles[best_match], "w") as fp: 
                            json.dump(speaker_ids2, fp, indent=4)

        if update1:
            #ipdb.set_trace()
            with open(jsonfiles[i], "w") as fp: 
                json.dump(speaker_ids1, fp, indent=4)

            print((goodpklfiles[i], speakers[i], speaker_ids1[speakers[i]], best_score, yt_ids[best_match], speakers[best_match], speaker_ids2[speakers[best_match]] ))

# this matches to an intermediate/incomplete set of old-style embeddings. This function should be retired.
def match_to_reference(threshold=0.7, yt_id=None):

    with open('speaker_references.pkl','rb') as fp: reference_speakers = pickle.load(fp)

    video_data = utils.get_video_data()
    files = glob.glob("*/embeddings.pkl")
    for file in files:
        update=False
        with open(file,'rb') as fp: embeddings = pickle.load(fp)

        dir = os.path.dirname(file)

        if yt_id != None:
            if yt_id != '_'.join(file.split('_')[1:]).split('\\')[0]: continue
        else: 
            yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]

        # read in the speaker mappings
        jsonfile = os.path.join(dir,'speaker_ids.json')
        if os.path.exists(jsonfile):
            with open(jsonfile, 'r') as fp:
                speaker_ids = json.load(fp)
        else:
            speaker_ids = {}

        for i, embedding in enumerate(embeddings.embeddings):
            best_score = -1.0
            best_match = ""
            for reference_speaker in reference_speakers.keys():
                score = cosine(embedding, reference_speakers[reference_speaker]["average"])
                if score > best_score:
                    best_score = score
                    best_match = reference_speaker

            if best_score > threshold and best_match != "North":
                #print(yt_id + ': ' + embeddings.speaker[i])
                #print("best match: " + best_match + ' (' + str(best_score) + ')')
                #print("current id: " + speaker_ids[embeddings.speaker[i]])
                if speaker_ids[embeddings.speaker[i]][:8] == "SPEAKER_":
                    #ipdb.set_trace()
                    speaker_ids[embeddings.speaker[i]] = best_match
                    update = True

        if update:
            #print(json.dumps(speaker_ids, indent=4))
            print("Updating " + yt_id)
            with open(jsonfile, "w") as fp:
                json.dump(speaker_ids, fp, indent=4)

            

#    ipdb.set_trace()
import matplotlib.pyplot as plt
def probe():

    plt.figure(figsize=(8, 5))
    values = np.linspace(0, 255, 256)

    file = '2024-10-05_3gvhm0AovZU/embeddings.pkl'
    yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]

    with open(file,'rb') as fp: embeddings = pickle.load(fp)
    for i, embedding in enumerate(embeddings.embeddings):
        norm = np.linalg.norm(embedding)
        print( ( i, np.min(embedding), np.max(embedding), np.max(embedding) - np.min(embedding), np.std(embedding), np.median(embedding), np.mean(embedding), norm ) )

        if i > 40:
            plt.plot(values, embedding, label=str(i), linewidth=2)
    plt.title('embeddings for ' + yt_id, fontsize=14)
    plt.xlabel('X', fontsize=12)
    plt.ylabel('embedding', fontsize=12)
    plt.legend()
    plt.grid(True)
    plt.show()
 
    ipdb.set_trace()


def match_all():
    files = glob.glob("*/embeddings.pkl")
    for file in files:
        #print(file)
        dir = os.path.dirname(file)
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        match_embeddings(yt_id)

# this matches the embeddings of a video with only new-style embeddings
def match_embeddings(yt_id, threshold=0.7):
    video_data = utils.get_video_data()

    dir = video_data[yt_id]["upload_date"] + "_" + yt_id
    embedding_file = os.path.join(dir,"embeddings.pkl")

    if not os.path.exists(embedding_file): 
        print("ERROR: no embedding file for " + yt_id)
        return

    with open(embedding_file,'rb') as fp: embeddings = pickle.load(fp)

    # read in the speaker mappings
    jsonfile = os.path.join(dir,'speaker_ids.json')
    if os.path.exists(jsonfile):
        with open(jsonfile, 'r') as fp:
            speaker_ids = json.load(fp)
    else:
        speaker_ids = {}

    #print(json.dumps(speaker_ids, indent=4))

    update = False
    for i, embedding in enumerate(embeddings.embeddings):

        # this speaker is not in the ID file; add it
        # maybe pruned, maybe never created
        if embeddings.speaker[i] not in speaker_ids.keys(): 
            speaker_ids[embeddings.speaker[i]] = embeddings.speaker[i]

        score = []

        # skip ones we've already ID'ed
        if speaker_ids[embeddings.speaker[i]][0:8] != "SPEAKER_": continue

        reference_files = glob.glob("*/embeddings.pkl")
        for reference_file in reference_files:

            # don't compare to yourself
            if reference_file == embedding_file: continue

            ref_dir = os.path.dirname(reference_file)
            ref_yt_id = '_'.join(ref_dir.split('_')[1:]).split('\\')[0]

            # read in the speaker mappings
            ref_jsonfile = os.path.join(ref_dir,'speaker_ids.json')
            if os.path.exists(ref_jsonfile):
                with open(ref_jsonfile, 'r') as fp:
                    ref_speaker_ids = json.load(fp)
            else:
                # hasn't been created yet 
                continue

            # read in the reference embeddings
            with open(reference_file,'rb') as fp: reference_embeddings = pickle.load(fp)

            #score[ref_yt_id] = {}
            for j,reference_embedding in enumerate(reference_embeddings.embeddings):

                # this speaker has been pruned from the ID file; skip it
                if reference_embeddings.speaker[j] not in ref_speaker_ids.keys(): continue

                score.append({
                    "yt_id" : ref_yt_id,
                    "speaker" : ref_speaker_ids[reference_embeddings.speaker[j]],
                    "score": cosine(embedding,reference_embedding),
                    }
                )

        #print(embeddings.speaker[i])

        best_score = -1
        best_named_score = -1
        for match in score:
            if match["score"] > threshold:

                if match["speaker"] != (yt_id + "_" + embeddings.speaker[i]):
                   print(yt_id + ": " + embeddings.speaker[i] + " matches " + match["speaker"] + " of " + match["yt_id"] + " (" + str(match["score"]) + ")")

                if match["score"] > best_score:
                    best_score = match["score"]

                    if match["speaker"][:8] == "SPEAKER_":
                        # name assigned by diarization
                        best_match = match["yt_id"] + "_" + match["speaker"]
                    else:
                        if match["speaker"] == (yt_id + "_" + embeddings.speaker[i]):
                            # no self references (from multiple passes)
                            best_match = embeddings.speaker[i]
                        else:
                            # manually assigned name
                            best_match = match["speaker"]

                if "SPEAKER_" not in match["speaker"] and match["score"] > best_named_score:
                    best_named_score = match["score"]

                    # manually assigned name
                    best_named_match = match["speaker"]



        if best_named_score > threshold:
            if speaker_ids[embeddings.speaker[i]][:8] == "SPEAKER_":
                if speaker_ids[embeddings.speaker[i]] != best_named_match:
                    speaker_ids[embeddings.speaker[i]] = best_named_match
                    update = True
            else:
                #print("speaker ID already assigned")
                pass
        elif best_score > threshold:
            if speaker_ids[embeddings.speaker[i]][:8] == "SPEAKER_":
                if speaker_ids[embeddings.speaker[i]] != best_match:
                    speaker_ids[embeddings.speaker[i]] = best_match
                    update = True
            else:
                #print("speaker ID already assigned")
                pass

    if update:
        #print(json.dumps(speaker_ids, indent=4))
        with open(jsonfile, "w") as fp:
            json.dump(speaker_ids, fp, indent=4)

def get_embeddings(yt_id='*', noisy_embedding=0.1):

    embeddings = {}

    pklfiles = glob.glob("voices_folder/" + yt_id + "_*.pkl") # embeddings made after the fact
    pklfiles2 = glob.glob("20??-??-??_" + yt_id + "/embeddings.pkl") # embeddings made during transcription

    # embeddings made after the fact
    for pklfile1 in pklfiles:
        with open(pklfile1,'rb') as fp: 
            embedding1 = pickle.load(fp)
        if len(embedding1) == 0: continue

        stdev = np.std(embedding1.embeddings[0])
        if stdev < noisy_embedding: continue

        speaker_num1 = '_'.join(os.path.splitext(os.path.basename(pklfile1))[0].split('_')[-2:])
        yt_id1 = '_'.join(os.path.splitext(os.path.basename(pklfile1))[0].split('_')[:-2])

        jsonfile = glob.glob('*' + yt_id1 + '*/speaker_ids.json')[0]
        with open(jsonfile, 'r') as fp:
            speaker_ids1 = json.load(fp)
        speaker_id1 = speaker_ids1[speaker_num1]

        # embeddings made during transcription
        key = yt_id1 + "_" + speaker_num1
        embeddings[key] = {}
        embeddings[key]["embedding"] = embedding1.embeddings[0]
        embeddings[key]["id"] = speaker_id1
        embeddings[key]["stdev"] = stdev
        embeddings[key]["jsonfile"] = jsonfile

    # embeddings made during transcription
    for pklfile2 in pklfiles2:
        with open(pklfile2,'rb') as fp: 
            embeddings2 = pickle.load(fp)

        dir = os.path.dirname(pklfile2)
        yt_id2 = '_'.join(dir.split('_')[1:]).split('\\')[0]

        # read in the speaker mappings
        jsonfile = os.path.join(dir,'speaker_ids.json')
        if not os.path.exists(jsonfile): continue        
        with open(jsonfile, 'r') as fp:
            speaker_ids2 = json.load(fp)

        # loop over all speakers for this video
        for i, embedding in enumerate(embeddings2.embeddings):

            stdev = np.std(embedding)
            if stdev < noisy_embedding: continue

            if embeddings2.speaker[i] not in speaker_ids2.keys(): continue

            # embeddings made during transcription
            key = yt_id2 + "_" + embeddings2.speaker[i]
            embeddings[key] = {}
            embeddings[key]["embedding"] = embedding
            embeddings[key]["id"] = speaker_ids2[embeddings2.speaker[i]]
            embeddings[key]["stdev"] = stdev
            embeddings[key]["jsonfile"] = jsonfile


    return embeddings

if __name__ == "__main__":

    match_to_reference2()
    propagate()
    match_all()
    propagate()
    #match_to_reference()#yt_id="a6bZISOstiw")
    #propagate()
    
    #probe()
    ipdb.set_trace()


#    ipdb.set_trace()
 #   ipdb.set_trace()

    yt_id = "DSAvAI2oq28"
    yt_id = "7D6c0Dkkm94"
    yt_id = "hGxT3FthToQ"
    yt_id = "fvIk50DtTTc"
#    match_embeddings(yt_id)
