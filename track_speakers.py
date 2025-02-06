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

def match_to_reference2(threshold=0.7, yt_id=None, voices_folder='voices_folder'):

    pklfiles = glob.glob(voices_folder + '/*.pkl')
    embeddings = []
    speakers = []
    yt_ids = []
    jsonfiles = []

    for pklfile in pklfiles:
        with open(pklfile,'rb') as fp: 
            embeddings.append(pickle.load(fp))

            speaker = '_'.join(os.path.splitext(os.path.basename(pklfile))[0].split('_')[-2:])
            yt_id = '_'.join(os.path.splitext(os.path.basename(pklfile))[0].split('_')[:-2])

            yt_ids.append(yt_id)
            speakers.append(speaker)
            jsonfiles.append(glob.glob('*' + yt_id + '*/speaker_ids.json')[0])

    nfiles = len(pklfiles)
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

            print((pklfiles[i], speakers[i], speaker_ids1[speakers[i]], best_score, yt_ids[best_match], speakers[best_match], speaker_ids2[speakers[best_match]] ))

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

def match_embeddings(yt_id, threshold=0.7, voices_folder=None):
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
        for match in score:
            if match["score"] > threshold:
                print(yt_id + ": " + embeddings.speaker[i] + " matches " + match["speaker"] + " of " + match["yt_id"] + " (" + str(match["score"]) + ")")
                if match["score"] > best_score:
                    best_score = match["score"]
                    if "SPEAKER_" == match["speaker"][:8]:
                        # name assigned by diarization
                        best_match = match["yt_id"] + "_" + match["speaker"]
                    else:
                        if match["speaker"] == (yt_id + "_" + embeddings.speaker[i]):
                            # no self references (from multiple passes)
                            best_match = embeddings.speaker[i]
                        else:
                            # manually assigned name
                            best_match = match["speaker"]

        if best_score > threshold:
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


if __name__ == "__main__":

    match_to_reference2()
    propagate()
    match_all()
    propagate()
    match_to_reference()#yt_id="a6bZISOstiw")
    propagate()
    
    #probe()
    ipdb.set_trace()


#    ipdb.set_trace()
 #   ipdb.set_trace()

    yt_id = "DSAvAI2oq28"
    yt_id = "7D6c0Dkkm94"
    yt_id = "hGxT3FthToQ"
    yt_id = "fvIk50DtTTc"
#    match_embeddings(yt_id)
