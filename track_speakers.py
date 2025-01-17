import glob, os
import pickle, json

import ipdb

# compute the cosine similarity of embeddings
from scipy.spatial.distance import cosine

import utils

def match_embeddings(yt_id):
    video_data = utils.get_video_data()

    dir = video_data[yt_id]["upload_date"] + "_" + yt_id
    embedding_file = os.path.join(dir,"embeddings.pkl")

    if not os.path.exists(embedding_file): 
        print("ERROR: no embedding file for " + yt_id)
        return

    with open(embedding_file,'rb') as fp: embeddings = pickle.load(fp)

    reference_files = glob.glob("*/embeddings.pkl")
    for reference_file in reference_files:

        # don't compare to yourself
        #if reference_file == embedding_file: continue

        ref_dir = os.path.dirname(reference_file)
        ref_yt_id = ref_dir.split("_")[1]

        # read in the speaker mappings
        jsonfile = os.path.join(ref_dir,'speaker_ids.json')
        if os.path.exists(jsonfile):
            with open(jsonfile, 'r') as fp:
                speaker_ids = json.load(fp)

        # read in the reference embeddings
        with open(reference_file,'rb') as fp: reference_embeddings = pickle.load(fp)

        score = {}
        for i,embedding in enumerate(embeddings.embeddings):
            score[ref_yt_id] = {}
            for j,reference_embedding in enumerate(reference_embeddings.embeddings):
                score[ref_yt_id][speaker_ids[reference_embeddings.speaker[j]]] = 1.0 - abs(cosine(embedding,reference_embedding))
                print(score)

            ipdb.set_trace()


if __name__ == "__main__":

    yt_id = "DSAvAI2oq28"
    match_embeddings(yt_id)
