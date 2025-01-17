import glob, os
import pickle, json

import ipdb

# compute the cosine similarity of embeddings
from scipy.spatial.distance import cosine

import utils

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

    print(yt_id + ":")
    for i, embedding in enumerate(embeddings.embeddings):
        score = []

        reference_files = glob.glob("*/embeddings.pkl")
        for reference_file in reference_files:

            # don't compare to yourself
            if reference_file == embedding_file: continue

            ref_dir = os.path.dirname(reference_file)
            ref_yt_id = ref_dir.split("_")[1]

            # read in the speaker mappings
            ref_jsonfile = os.path.join(ref_dir,'speaker_ids.json')
            if os.path.exists(ref_jsonfile):
                with open(ref_jsonfile, 'r') as fp:
                    ref_speaker_ids = json.load(fp)

            # read in the reference embeddings
            with open(reference_file,'rb') as fp: reference_embeddings = pickle.load(fp)


            #score[ref_yt_id] = {}
            for j,reference_embedding in enumerate(reference_embeddings.embeddings):
                #score[ref_yt_id][speaker_ids[reference_embeddings.speaker[j]]] = 
                score.append({
                    "yt_id":ref_yt_id,
                    "speaker":ref_speaker_ids[reference_embeddings.speaker[j]],
                    "score":1.0 - abs(cosine(embedding,reference_embedding)),
                    }
                )

        #print(embeddings.speaker[i])

        best_score = -1
        for match in score:
            if match["score"] > threshold:
                print(embeddings.speaker[i] + " matches " + match["speaker"] + " of " + match["yt_id"] + " (" + str(match["score"]) + ")")
                if match["score"] > best_score:
                    best_score = match["score"]
                    if "SPEAKER_" == match["speaker"][:8]: best_match = match["yt_id"] + "_" + match["speaker"]
                    else: best_match = match["speaker"]

        if best_score != -1:
            if speaker_ids[embeddings.speaker[i]][:8] == "SPEAKER_":
                speaker_ids[embeddings.speaker[i]] = best_match
            else:
                #print("speaker ID already assigned")
                pass

    print(json.dumps(speaker_ids, indent=4))

    ipdb.set_trace()
    with open(jsonfile, "w") as fp:
        json.dump(speaker_ids, fp, indent=4)


if __name__ == "__main__":

    yt_id = "DSAvAI2oq28"
    yt_id = "7D6c0Dkkm94"
    match_embeddings(yt_id)
