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
import speaker_provenance as sp   # stdlib-only sidecar; see its module doc

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

    return dot_product / (norm1 * norm2)

def distance(vector1, vector2):
    return np.sqrt(np.sum((vector1-vector2)**2))


# ---------------------------------------------------------------------------
# REFERENCE EMBEDDING CACHE
#
# match_embeddings used to glob the filesystem and re-read EVERY reference
# embeddings.pkl once per unidentified speaker in the new video. Measured on
# this corpus: 1,915 files / 25,705 speakers / 25.1 MB, and 64.3 s for one full
# pass. A typical video has ~12 unnamed speakers, so that was 780 s (13 min)
# per video and 22,980 file opens, all to re-read 25 MB that had not changed --
# about 13 of the ~21 minutes of post-processing between videos.
#
# The quadratic comparison was never the problem: 308,460 cosines vectorise to
# 0.056 s. The cost was I/O. The two inputs have different lifetimes:
#
#   embeddings.pkl   IMMUTABLE once written    -> cached in memory (25 MB)
#   speaker_ids.json CHANGES as people are named -> re-read every call (1.0 s)
#
# so the cache is keyed on mtime+size and only the JSON is re-read. Net cost is
# about a second per video instead of 780, with identical results.
_embedding_cache = {}          # path -> (mtime, size, [(speaker_key, vector)])


def _cached_embeddings(path):
    """[(speaker_key, vector)] for one embeddings.pkl, cached by mtime+size."""
    try:
        st = os.stat(path)
    except OSError:
        return []

    hit = _embedding_cache.get(path)
    if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]

    try:
        with open(path, "rb") as fp:
            emb = pickle.load(fp)
    except Exception:
        _embedding_cache[path] = (st.st_mtime, st.st_size, [])
        return []

    rows = [(emb.speaker[j], np.asarray(v, dtype=np.float64))
            for j, v in enumerate(emb.embeddings)]
    _embedding_cache[path] = (st.st_mtime, st.st_size, rows)
    return rows


# ------------------------------------------------- self-consistency filter
#
# A REFERENCE THAT DOES NOT MATCH ITSELF MUST NOT VOUCH FOR ANYONE.
#
# The stored embedding is a MEAN over every segment attributed to a cluster.
# When a speaker's segments are cleanly cut that mean is a voiceprint; when
# they are not, it is a blend. The city clerk is the worst case in this corpus
# and the reason is structural: he reads the roll, and members answer "Here" /
# "Yes" in the gaps, so short responses land inside his segments and his mean
# absorbs a slice of everyone who answered. A different set of members answers
# at every meeting, so each meeting yields a DIFFERENT blend.
#
# Measured over 454 people with 5+ embeddings:
#     median self-consistency (mean pairwise cosine of one person's own
#     embeddings, across meetings)                              0.805
#     Adam Hurtubise, n=808                                     0.406
# He is the second least self-consistent identity in the corpus, behind only
# "BBC Broadcast", which is not a person. 0.406 is BELOW the 0.7 threshold
# match_embeddings uses to decide two clusters are the same human -- his
# vectors would not match each other. That is how the city clerk came to be
# identified in 613 meetings including a jazz festival, a podcast and campaign
# videos, and how one 2024 meeting has FOUR separate clusters all labelled him.
#
# WHY THE EXISTING noisy_embedding FILTER DOES NOT CATCH IT. That test is
# np.std(vector) < 0.15, applied to one vector at a time: averaging unlike
# voices regresses toward the mean and flattens the vector. It is right, and
# it catches 75% of his embeddings -- but ~200 pass, because a blend of the
# clerk plus THIS meeting's five responders can be perfectly sharp on its own.
# Flatness is a property of one vector; a blend that changes every meeting is
# only visible by comparing a person against themselves.
#
# So this is a SECOND, INDEPENDENT dimension, not a replacement: keep the
# per-vector flatness test, and additionally bar a named person from acting as
# a reference when their own embeddings disagree with each other.
# THE THRESHOLD IS 0.55, AND IT IS MEASURED, NOT INHERITED.
#
# The tempting value was 0.7 -- "a reference that cannot match itself at the
# bar we use to call two clusters the same person should not vouch for anyone".
# That is a tidy argument and the data refutes it. 0.7 is the bar for IS THIS
# THE SAME PERSON; it is not the bar for IS THIS IDENTITY COHERENT, and using
# one for the other cuts 19.3% of the reference pool -- Fred Dello Russo (248
# embeddings), John Falco (210), Jenny Graham (363), Aaron Olapade (84). At
# 0.75 it takes Zac Bears. Roll calls blend everyone a little, so a long tail
# of perfectly real officials sits between 0.58 and 0.70 against a corpus
# median of 0.805.
#
# Measured cost, over 453 people with 5+ embeddings and 17,807 named vectors:
#     0.45 ->  5 people,  5.5% of vectors
#     0.50 ->  8 people,  5.9%
#     0.55 ->  8 people,  5.9%   <- identical set: a real gap in the
#     0.60 -> 14 people,  8.8%      distribution, not a slice through it
#     0.70 -> 45 people, 19.3%
# 0.55 sits in that plateau and removes exactly the identities that are broken
# rather than merely noisy: Adam Hurtubise (0.406), Marie Izzo (0.440),
# Evangelista, Maria D'Orsi, and "BBC Broadcast" (0.071), which is not a
# person at all. Hurtubise and Izzo are independently the top of the
# bare-assent ranking -- two unrelated signals, text and acoustic, agreeing.
SELF_CONSISTENCY_MIN = 0.55
SELF_CONSISTENCY_MIN_N = 5      # below this there is no evidence either way
_SELF_CONSISTENCY_CACHE = "speaker_self_consistency.json"
_self_consistency = None


def _corpus_fingerprint():
    """Cheap signature of the embedding corpus, to invalidate the cache."""
    n = size = 0
    for p in glob.glob("*/embeddings.pkl"):
        try:
            st = os.stat(p)
        except OSError:
            continue
        n += 1
        size += st.st_size
    return "%d:%d" % (n, size)


def speaker_self_consistency(force=False):
    """{name: [n, mean pairwise cosine]} for every named speaker.

    One person's embeddings from different meetings should resemble each
    other. Where they do not, the cluster is not a stable identity.
    """
    global _self_consistency
    if _self_consistency is not None and not force:
        return _self_consistency

    fp = _corpus_fingerprint()
    if not force and os.path.exists(_SELF_CONSISTENCY_CACHE):
        try:
            with open(_SELF_CONSISTENCY_CACHE, "r") as f:
                blob = json.load(f)
            if blob.get("fingerprint") == fp:
                _self_consistency = blob.get("speakers", {})
                return _self_consistency
        except (OSError, ValueError):
            pass

    rows = {}
    for pkl in glob.glob("*/embeddings.pkl"):
        jsonfile = os.path.join(os.path.dirname(pkl), "speaker_ids.json")
        if not os.path.exists(jsonfile):
            continue
        try:
            with open(jsonfile, "r") as f:
                ids = json.load(f)
        except (OSError, ValueError):
            continue
        for key, vec in _cached_embeddings(pkl):
            name = ids.get(key)
            if not _is_named(name):
                continue
            v = np.asarray(vec, dtype=np.float64)
            if v.ndim == 1 and v.size:
                rows.setdefault(name, []).append(v)

    out = {}
    for name, vs in rows.items():
        if len(vs) < 2:
            out[name] = [len(vs), None]
            continue
        M = np.vstack(vs)
        norms = np.linalg.norm(M, axis=1)
        M = M[norms > 0]
        norms = norms[norms > 0]
        if M.shape[0] < 2:
            out[name] = [len(vs), None]
            continue
        M = M / norms[:, None]
        S = M.dot(M.T)
        iu = np.triu_indices(S.shape[0], 1)
        out[name] = [len(vs), float(np.mean(S[iu]))]

    _self_consistency = out
    try:
        with open(_SELF_CONSISTENCY_CACHE, "w") as f:
            json.dump({"fingerprint": fp, "speakers": out}, f, indent=1,
                      sort_keys=True)
    except OSError:
        pass
    return out


def _is_named(name):
    """A resolved HUMAN name, not a diarisation placeholder or a cross-ref."""
    return (isinstance(name, str)
            and not name.startswith("SPEAKER_")
            and "_SPEAKER_" not in name
            and name != "Unidentified")


def unreliable_speakers(min_cos=None, min_n=None):
    """Named speakers whose own embeddings disagree with each other.

    Only names with enough samples to judge are returned: with fewer than
    min_n embeddings there is no evidence, and absence of evidence must not
    silently disable a real person.
    """
    min_cos = SELF_CONSISTENCY_MIN if min_cos is None else min_cos
    min_n = SELF_CONSISTENCY_MIN_N if min_n is None else min_n
    bad = set()
    for name, (n, cos) in speaker_self_consistency().items():
        if cos is not None and n >= min_n and cos < min_cos:
            bad.add(name)
    return bad


def _reference_table(exclude_file):
    """(matrix, meta) for every named reference speaker except exclude_file.

    meta[i] is (ref_yt_id, resolved_speaker_name, ref_speaker_key), in GLOB
    ORDER. The original iterated references in that order and broke ties
    with a strict '>', so preserving the order preserves which match wins.
    ref_speaker_key is additive (for provenance's "from" field only) -- it
    does not participate in scoring, ordering, or tie-breaking.
    """
    vectors, meta = [], []
    # Named people whose own embeddings disagree with each other. They are
    # dropped as REFERENCES only -- their transcripts and existing labels are
    # untouched, and unnamed SPEAKER_nn chain links still work exactly as
    # before, so cross-video linking is unaffected except that it can no
    # longer be vouched for by a blended identity.
    bad_refs = unreliable_speakers()
    for reference_file in glob.glob("*/embeddings.pkl"):
        if reference_file == exclude_file:            # don't compare to yourself
            continue
        ref_dir = os.path.dirname(reference_file)
        ref_yt_id = "_".join(ref_dir.split("_")[1:]).split(chr(92))[0]

        ref_jsonfile = os.path.join(ref_dir, "speaker_ids.json")
        if not os.path.exists(ref_jsonfile):
            continue                                  # hasn't been created yet
        try:
            with open(ref_jsonfile, "r") as fp:
                ref_speaker_ids = json.load(fp)
        except (OSError, ValueError):
            continue

        for speaker_key, vec in _cached_embeddings(reference_file):
            # this speaker has been pruned from the ID file; skip it
            if speaker_key not in ref_speaker_ids:
                continue
            if ref_speaker_ids[speaker_key] in bad_refs:
                continue          # self-inconsistent identity; see above
            vectors.append(vec)
            meta.append((ref_yt_id, ref_speaker_ids[speaker_key], speaker_key))

    if not vectors:
        return np.zeros((0, 1)), []
    return np.vstack(vectors), meta


def _similarities(matrix, query):
    """Cosine SIMILARITY against every row -- same convention as cosine()
    above, including returning 0 rather than NaN for a zero-norm vector."""
    if matrix.shape[0] == 0:
        return np.zeros(0)
    qn = np.linalg.norm(query)
    if qn == 0.0:
        return np.zeros(matrix.shape[0])
    norms = np.linalg.norm(matrix, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = matrix.dot(query) / (norms * qn)
    sims[norms == 0.0] = 0.0
    return sims


'''
This will propagate manual identifications throughout the speaker_id.json files

ALL-OR-NOTHING: every file is read and every update computed in memory
before anything is written to disk. The original wrote each file as it went,
so an exception partway through left the corpus half-propagated with no
marker that it had happened. Nothing here touches disk until the whole pass
has finished computing.

Within a pass, a file that has already been updated is read back from memory
(read_ids below), so a later file that references it sees the NEW value --
exactly what the old write-as-you-go code did. Chains still take one pass
per hop for files globbed BEFORE their source, as before.

Two guards protect hand-verified values, which is where corruption used to
spread silently:
  (a) an entry whose OWN recorded provenance source is "manual"
      (speaker_provenance.json, written by `speaker_provenance.py
      mark-manual`) is never overwritten, regardless of its current shape
  (b) a cluster key that references a speaker pruned from the target file
      (mapped_speaker not in mapped_ids) is skipped rather than raising --
      the original did mapped_ids[mapped_speaker], a KeyError that is
      latent on the current corpus (0 occurrences measured 2026-09-18) but
      aborts mid-write the moment it fires

Every value set here is recorded in the target's speaker_provenance.json as
source "propagated" with from=<cluster key>, previous=<old value>, and the
score of the source entry if it has one.

Returns a dict summarizing what happened, for callers/tests that want to
verify guards fired instead of grepping stdout.
'''
def propagate():
    files = glob.glob("*/speaker_ids.json")

    pending_speaker_ids = {}   # normpath(file) -> updated dict; only files with a change
    pending_provenance = {}    # normpath(dir)  -> updated provenance dict
    skipped_manual = []
    skipped_missing = []

    def read_ids(path):
        # a file already updated in this pass is read from memory, so a later
        # file sees an earlier file's new value (see docstring)
        key = os.path.normpath(path)
        if key in pending_speaker_ids:
            return pending_speaker_ids[key]
        with open(path, 'r') as fp:
            return json.load(fp)

    def read_provenance(directory):
        key = os.path.normpath(directory)
        if key in pending_provenance:
            return pending_provenance[key]
        return sp.load_provenance(directory)

    # ---- collect: nothing below this point writes to disk ----
    for file in files:
        update = False

        directory = os.path.dirname(file)
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]

        # read in the speaker mappings
        speaker_ids = read_ids(file)
        provenance = read_provenance(directory)

        for speaker in speaker_ids.keys():

            # reference to another file's ID, grab its (updated?) ID
            if len(speaker_ids[speaker]) > 12:
                if speaker_ids[speaker][11] == "_":
                    mapped_yt_id = speaker_ids[speaker][:11]
                    mapped_speaker = speaker_ids[speaker][12:]

                    # read in the speaker mappings
                    mapped_file = glob.glob('*' + mapped_yt_id + '/speaker_ids.json')
                    if len(mapped_file) == 1:
                        mapped_ids = read_ids(mapped_file[0])

                        # GUARD (b): referenced speaker was pruned from its
                        # file -- skip instead of KeyError-ing mid-pass
                        if mapped_speaker not in mapped_ids:
                            skipped_missing.append((file, speaker, speaker_ids[speaker]))
                            continue

                        # if it's been updated, propagate it
                        if mapped_ids[mapped_speaker] != mapped_speaker:

                            # GUARD (a): never overwrite a hand-verified entry,
                            # nor a high-confidence backfill -- see
                            # speaker_provenance.PROTECTED_SOURCES
                            if sp.is_protected(provenance, speaker):
                                skipped_manual.append((file, speaker))
                                continue

                            old_value = speaker_ids[speaker]
                            new_value = mapped_ids[mapped_speaker]

                            print(yt_id + ": " + old_value + " matches " + new_value + ")")
                            speaker_ids[speaker] = new_value
                            update = True

                            mapped_dir = os.path.dirname(mapped_file[0])
                            src_entry = read_provenance(mapped_dir).get(mapped_speaker, {})
                            provenance[speaker] = sp.make_entry(
                                new_value, "propagated",
                                score=src_entry.get("score") if isinstance(src_entry, dict) else None,
                                from_=mapped_yt_id + "_" + mapped_speaker,
                                previous=old_value,
                            )

        if update:
            pending_speaker_ids[os.path.normpath(file)] = speaker_ids
            pending_provenance[os.path.normpath(directory)] = provenance

    # ---- commit: everything above succeeded, now write it all ----
    for file, speaker_ids in pending_speaker_ids.items():
        sp.atomic_write_json(file, speaker_ids)   # same indent=4 as before

    for directory, provenance in pending_provenance.items():
        sp.save_provenance(directory, provenance)

    if skipped_manual:
        print(str(len(skipped_manual)) + " entries protected by manual provenance were left unchanged")
    if skipped_missing:
        print(str(len(skipped_missing)) + " cluster keys referenced a pruned speaker and were skipped")

    return {
        "updated_files": list(pending_speaker_ids.keys()),
        "skipped_manual": skipped_manual,
        "skipped_missing": skipped_missing,
    }

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
        # A voiceprint in voices_folder can outlive the transcript it came
        # from -- a directory gets renamed, or a speaker_ids.json is removed
        # to force a clean re-transcribe. Indexing [0] on an empty glob then
        # raised IndexError out of match_to_reference2, and because that runs
        # AFTER transcribe() succeeds but BEFORE finish_async, every newly
        # transcribed video stopped being published: the caller caught the
        # exception, skipped srt2html and push_to_git, and moved on. Two
        # meetings were transcribed and silently never published this way on
        # 2026-09-19/20, and the priority queue stopped being consulted.
        #
        # One orphaned voiceprint must not cost the whole pass.
        _json = glob.glob('*' + yt_id + '*/speaker_ids.json')
        if not _json:
            print('  no speaker_ids.json for ' + yt_id + '; skipping its voiceprint')
            embeddings.pop()
            yt_ids.pop()
            speakers.pop()
            continue
        jsonfiles.append(_json[0])
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

    # provenance sidecar: records score + source speaker for every value set
    # below; written only if speaker_ids.json is (see the end of this function)
    provenance = sp.load_provenance(dir)

    update = False
    ref_matrix, ref_meta = None, []
    for i, embedding in enumerate(embeddings.embeddings):

        # this speaker is not in the ID file; add it
        # maybe pruned, maybe never created
        if embeddings.speaker[i] not in speaker_ids.keys(): 
            speaker_ids[embeddings.speaker[i]] = embeddings.speaker[i]

        score = []

        # skip ones we've already ID'ed
        if speaker_ids[embeddings.speaker[i]][0:8] != "SPEAKER_": continue

        # Reference table is built ONCE per call, and the embeddings inside it
        # are cached across calls, so this no longer re-reads 25 MB from disk
        # for every unidentified speaker. The comparison is one matrix product
        # instead of a Python loop over 25,705 cosine calls.
        if ref_matrix is None:
            ref_matrix, ref_meta = _reference_table(embedding_file)

        sims = _similarities(ref_matrix, np.asarray(embedding, dtype=np.float64))
        for n, (ref_yt_id, ref_speaker, ref_speaker_key) in enumerate(ref_meta):
            score.append({
                "yt_id": ref_yt_id,
                "speaker": ref_speaker,
                "speaker_key": ref_speaker_key,
                "score": sims[n],
                })

        #print(embeddings.speaker[i])

        best_score = -1
        best_named_score = -1
        for match in score:
            if match["score"] > threshold:

                if match["speaker"] != (yt_id + "_" + embeddings.speaker[i]):
                   print(yt_id + ": " + embeddings.speaker[i] + " matches " + match["speaker"] + " of " + match["yt_id"] + " (" + str(match["score"]) + ")")

                if match["score"] > best_score:
                    best_score = match["score"]
                    # the specific reference speaker that produced this
                    # match, for provenance's "from" -- does not affect
                    # matching, only what gets recorded about it
                    best_match_from = match["yt_id"] + "_" + match["speaker_key"]

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
                    best_named_match_from = match["yt_id"] + "_" + match["speaker_key"]

                    # manually assigned name
                    best_named_match = match["speaker"]



        if best_named_score > threshold:
            if speaker_ids[embeddings.speaker[i]][:8] == "SPEAKER_":
                if speaker_ids[embeddings.speaker[i]] != best_named_match:
                    previous = speaker_ids[embeddings.speaker[i]]
                    speaker_ids[embeddings.speaker[i]] = best_named_match
                    update = True
                    provenance[embeddings.speaker[i]] = sp.make_entry(
                        best_named_match, "embedding_match",
                        score=best_named_score,
                        from_=best_named_match_from,
                        previous=previous,
                    )
            else:
                #print("speaker ID already assigned")
                pass
        elif best_score > threshold:
            if speaker_ids[embeddings.speaker[i]][:8] == "SPEAKER_":
                if speaker_ids[embeddings.speaker[i]] != best_match:
                    previous = speaker_ids[embeddings.speaker[i]]
                    speaker_ids[embeddings.speaker[i]] = best_match
                    update = True
                    provenance[embeddings.speaker[i]] = sp.make_entry(
                        best_match, "embedding_match",
                        score=best_score,
                        from_=best_match_from,
                        previous=previous,
                    )
            else:
                #print("speaker ID already assigned")
                pass

    if update:
        #print(json.dumps(speaker_ids, indent=4))
        with open(jsonfile, "w") as fp:
            json.dump(speaker_ids, fp, indent=4)
        sp.save_provenance(dir, provenance)

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
