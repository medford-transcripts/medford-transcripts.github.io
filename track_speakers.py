import glob, os
import pickle, json

import ipdb

# compute the cosine similarity of embeddings
#from scipy.spatial.distance import cosine
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

'''
This will propagate manual identifications throughout the speaker_id.json files
'''
def propagate():
    files = glob.glob("*/speaker_ids.json")

    # propagate updates in the referenced files
    for file1 in files:
        update1 = False

        yt_id1 = '_'.join(file1.split('_')[1:]).split('\\')[0]

        # read in the speaker mappings
        with open(file1, 'r') as fp:
            speaker_ids1 = json.load(fp)

        print(yt_id1)
        print(json.dumps(speaker_ids1, indent=4))

        for speaker1 in speaker_ids1.keys():

            # reference to another file's ID, grab its (updated?) ID
            if len(speaker_ids1[speaker1]) > 12:
                if speaker_ids1[speaker1][11] == "_":
                    mapped_yt_id = speaker_ids1[speaker1][:11]
                    mapped_speaker = speaker_ids1[speaker1][12:]

                    print((speaker_ids1[speaker1], mapped_yt_id, mapped_speaker))

                    # read in the speaker mappings
                    mapped_file = glob.glob('*' + mapped_yt_id + '/speaker_ids.json')
                    if len(mapped_file) == 1: 
                        with open(mapped_file[0], 'r') as fp:
                            mapped_ids = json.load(fp)

                        # if it's been updated, propagate it
                        if mapped_ids[mapped_speaker] != mapped_speaker:
                            speaker_ids1[speaker1] = mapped_ids[mapped_speaker]
                            update1 = True

        if update1:
            with open(file1, "w") as fp:
                json.dump(speaker_ids1, fp, indent=4)

    return

    # wait... what scenario was I handling here? I think I covered it all
    for file1 in files:
        print("doing " + file1)
        update1 = False
        yt_id1 = '_'.join(file1.split('_')[1:]).split('\\')[0]

        # read in the speaker mappings
        with open(file1, 'r') as fp:
            speaker_ids1 = json.load(fp)

        for file2 in files:
            update2 = False

            # skip self
            if file1 == file2: continue

            yt_id2 = '_'.join(file1.split('_')[1:]).split('\\')[0]

            # read in the speaker mappings
            with open(file2, 'r') as fp:
                speaker_ids2 = json.load(fp)

            for speaker1 in speaker_ids1.keys():

                for speaker2 in speaker_ids2.keys():

                    # overwrite speaker2's automatic identification with 
                    # speaker1's manual identification
                    if speaker_ids2[speaker2] == yt_id1 + '_' + speaker2: ipdb.set_trace()
                    if speaker_ids1[speaker1] == yt_id2 + '_' + speaker1: ipdb.set_trace()

                    if speaker_ids1[speaker1][:8] != "SPEAKER_" and speaker_ids2[speaker2] == yt_id1 + '_' + speaker2:
                        ipdb.set_trace()
                        speaker_ids2[speaker2] = speaker_ids1[speaker1]
                        update2 = True

                    # overwrite speaker1's automatic identification with 
                    # speaker2's manual identification
                    if speaker_ids2[speaker2][:8] != "SPEAKER_" and speaker_ids1[speaker1] == yt_id2 + '_' + speaker1:
                        ipdb.set_trace()
                        speaker_ids1[speaker1] = speaker_ids2[speaker2]
                        update1 = True

        # if the speakers in file2 were updated, save it
        if update2:
            print(json.dumps(speaker_ids2, indent=4))
            ipdb.set_trace()
            with open(file2, "w") as fp:
                json.dump(speaker_ids2, fp, indent=4)

    # if the speakers in file1 were updated, save it
    if update1:
        print(json.dumps(speaker_ids1, indent=4))
        ipdb.set_trace()
        with open(file1, "w") as fp:
            json.dump(speaker_ids1, fp, indent=4)


def match_all():

    files = glob.glob("*/embeddings.pkl")
    for file in files:
        print(file)
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

    print(yt_id + ":")
    print(json.dumps(speaker_ids, indent=4))

    update = False
    for i, embedding in enumerate(embeddings.embeddings):

        # this speaker is not in the ID file; add it
        # maybe pruned, maybe never created
        if embeddings.speaker[i] not in speaker_ids.keys(): 
            speaker_ids[embeddings.speaker[i]] = embeddings.speaker[i]

        score = []

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
                print(embeddings.speaker[i] + " matches " + match["speaker"] + " of " + match["yt_id"] + " (" + str(match["score"]) + ")")
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
        print(json.dumps(speaker_ids, indent=4))
        with open(jsonfile, "w") as fp:
            json.dump(speaker_ids, fp, indent=4)


if __name__ == "__main__":

    match_all()
    propagate()
    ipdb.set_trace()

    yt_id = "DSAvAI2oq28"
    yt_id = "7D6c0Dkkm94"
    yt_id = "hGxT3FthToQ"
    yt_id = "fvIk50DtTTc"
    match_embeddings(yt_id)
