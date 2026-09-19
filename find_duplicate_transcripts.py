"""
Find duplicate recordings by comparing the TRANSCRIPTS, not the metadata.

WHY THIS CATCHES WHAT identify_duplicate_videos CANNOT. That function requires
the two copies to come from DIFFERENT channels -- which is right for its job
(preferring an official source over an unofficial one) but blind to a whole
class: the MCM archive holding two copies of the same meeting under
consecutive ids, a channel re-posting a trimmed version, a candidate profile
uploaded twice. Those share a channel, so the metadata rule never compares
them.

Measured on this corpus: 127 pairs at Jaccard >= 0.30, of which 94 were NOT
marked as duplicates. Several are identical (1.00) -- e.g. MCM00000931 and
MCM00000932, same title, same words, same channel.

This also matters beyond tidiness: two pages carrying the same transcript are
duplicate content, and a domain full of it is exactly what gets "crawled,
currently not indexed" in Search Console.

METHOD. Compare only transcripts whose MEETING DATES are within a few days --
two recordings of one meeting must share a date, and it keeps this from being
2.6M comparisons. Similarity is Jaccard over hashed word-5-grams via a
bottom-k sketch, which is robust to the differences that actually occur: a
different recording starts and stops at a different moment, so one copy
carries extra preamble, and the two are diarized separately so speaker labels
differ. Comparing words rather than speaker labels is the point.

A REPORT BY DEFAULT. --apply marks the lower-priority copy skip, using the
same keeper rules as identify_duplicate_videos (official source first, then
the copy that already has a transcript, then the non-Livestream one) and never
touching an entry with manual_correction or a skip it did not set.

Usage:
    python find_duplicate_transcripts.py                # report
    python find_duplicate_transcripts.py --threshold .5
    python find_duplicate_transcripts.py --apply
"""

import argparse
import collections
import datetime
import glob
import hashlib
import io
import os
import re
import sys

import srt_lines
import utils

WORD = re.compile(r"[a-z']+")

# A RAW recording and its TRIMMED version are duplicates even though their
# durations differ wildly. Mass Traction streamed council meetings off an
# over-the-air broadcast whenever he could set it up, so the livestream runs
# for hours around the meeting -- 455 minutes against a 194-minute trim of the
# same session -- and Medford Community Media does the same thing, marking it
# in the title ("Inauguration 2025" 612m vs "Inauguration 2025 -- trimmed"
# 73m). The duration guard below would call those excerpts and let both stand;
# these markers exempt them. The trimmed copy is the one worth keeping.
RAW_MARKER = re.compile(r"livestream|live stream", re.I)
TRIM_MARKER = re.compile(r"trimmed|unofficial", re.I)


def raw_trim_pair(ta, tb):
    """True if one title is marked as a raw stream or an edited version and the
    other is not.

    Asymmetry is the signal, because the conventions differ by source: Mass
    Traction pairs "[Livestream]" against "(Unofficial", while Medford
    Community Media pairs a bare title against "-- trimmed". Requiring a raw
    marker on one side would miss the second case entirely.
    """
    a_raw, b_raw = bool(RAW_MARKER.search(ta or "")), bool(RAW_MARKER.search(tb or ""))
    a_trim, b_trim = bool(TRIM_MARKER.search(ta or "")), bool(TRIM_MARKER.search(tb or ""))
    return (a_raw != b_raw) or (a_trim != b_trim)


def sketch(path, k=5, keep=400):
    """Bottom-k sketch of hashed word-k-grams: an unbiased Jaccard estimate."""
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return set()
    words = []
    for block in srt_lines.parse_srt(text):
        words.extend(WORD.findall((block["text"] or "").lower()))
    if len(words) < k + 5:
        return set()
    hashes = sorted(
        int.from_bytes(hashlib.blake2b(" ".join(words[i:i + k]).encode(),
                                       digest_size=8).digest(), "big")
        for i in range(len(words) - k + 1))
    return set(hashes[:keep])


def transcripts():
    out = {}
    for path in glob.glob("20??-??-??_*/*.srt"):
        base = os.path.basename(path)
        if base.endswith(("_basic.srt", "_aligned.srt")) or path.endswith(".orig"):
            continue
        out[base[:-4].split("_", 1)[1]] = path
    return out


def candidate_pairs(video_data, have, window_days=2):
    by_date = collections.defaultdict(list)
    for yt_id in have:
        entry = video_data.get(yt_id)
        if not entry:
            continue
        date = utils.meeting_date(entry)
        if date:
            by_date[date].append(yt_id)

    pairs = set()
    dates = sorted(by_date)
    for i, date in enumerate(dates):
        near = []
        for j in range(i, len(dates)):
            try:
                gap = (datetime.date.fromisoformat(dates[j])
                       - datetime.date.fromisoformat(date)).days
            except ValueError:
                continue
            if gap > window_days:
                break
            near.extend(by_date[dates[j]])
        for a in range(len(near)):
            for b in range(a + 1, len(near)):
                if near[a] != near[b]:
                    pairs.add(tuple(sorted((near[a], near[b]))))
    return sorted(pairs)


def all_pairs(sketches, max_docs=40, min_shared=40):
    """Candidate pairs WITHOUT trusting the date, via an inverted index.

    Date bucketing is fast but circular: it trusts the field we are trying to
    clean, so two copies of one meeting with different bad dates are never
    compared. Measured, that blind spot is real -- "MVTHS - Media Tech Shop
    Profile" is posted twice 11 days apart at similarity 1.00, and "Shannon
    Demos - Brooks Elementary School" 48 days apart, also 1.00.

    All-pairs over 2,282 transcripts is 2.6M comparisons; an inverted index
    makes it cheap because almost every pair shares nothing. A hash appearing
    in more than max_docs transcripts is boilerplate (procedural language, the
    pledge, roll-call phrasing) and is skipped -- it generates pairs without
    discriminating between them.
    """
    inverted = collections.defaultdict(list)
    for yt_id, sketch_set in sketches.items():
        for h in sketch_set:
            inverted[h].append(yt_id)

    shared = collections.Counter()
    for ids in inverted.values():
        if len(ids) < 2 or len(ids) > max_docs:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                shared[tuple(sorted((ids[i], ids[j])))] += 1
    return [pair for pair, n in shared.items() if n >= min_shared]


def days_apart(video_data, a, b):
    da = utils.meeting_date(video_data.get(a, {}))
    db = utils.meeting_date(video_data.get(b, {}))
    try:
        return abs((datetime.date.fromisoformat(da)
                    - datetime.date.fromisoformat(db)).days)
    except (TypeError, ValueError):
        return None


def date_evidence(video_data, yt_id):
    """What the metadata says about this video's date, and how well supported.

    A LIVESTREAM'S UPLOAD DATE IS ITS MEETING DATE -- you cannot stream a
    meeting a year before it happens. That is what caught IxvjbChoNJk: titled
    "Medford, MA School Committee - Jan. 22, 2017 [Livestream]" but uploaded
    2018-01-22, the classic January year typo. Its duplicate from another
    channel is dated 2018-01-22, and the two agree on everything but the year.
    """
    entry = video_data.get(yt_id, {})
    title = entry.get("title") or ""
    from_title = utils.title_date(title, not_after=entry.get("upload_date"))
    upload = entry.get("upload_date")
    if RAW_MARKER.search(title) and upload:
        return upload, "livestream upload date"
    if from_title:
        return from_title, "title"
    return entry.get("date"), "stored"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.30,
                    help="Jaccard above which a pair is a duplicate (default 0.30)")
    ap.add_argument("--window", type=int, default=2, help="days apart to still compare")
    ap.add_argument("--all-pairs", action="store_true",
                    help="ignore dates entirely; finds duplicates whose dates are wrong")
    ap.add_argument("--min-duration-ratio", type=float, default=0.5,
                    help="shorter/longer duration below which a pair is an "
                         "excerpt, not a duplicate (default 0.5)")
    ap.add_argument("--apply", action="store_true", help="mark the loser skip")
    args = ap.parse_args()

    video_data = utils.get_video_data()
    have = transcripts()
    print("transcripts            : %d" % len(have))

    if args.all_pairs:
        sketches = {yt: sketch(path) for yt, path in sorted(have.items())}
        sketches = {k: v for k, v in sketches.items() if v}
        pairs = all_pairs(sketches)
    else:
        pairs = candidate_pairs(video_data, have, args.window)
        needed = {y for pair in pairs for y in pair}
        sketches = {yt: sketch(have[yt]) for yt in sorted(needed)}
    print("candidate pairs        : %d" % len(pairs))

    # DURATION GUARD. Jaccard alone mistakes an EXCERPT for a duplicate: a
    # 3-minute clip cut from a 52-minute meeting scored 0.71, and skipping it
    # would hide a legitimate short video rather than a redundant copy. Two
    # recordings of one meeting are close in length; a clip is not. Pairs that
    # are similar but lopsided are reported separately as excerpts and never
    # marked.
    hits, excerpts = [], []
    for a, b in pairs:
        sa, sb = sketches.get(a) or set(), sketches.get(b) or set()
        if not sa or not sb:
            continue
        score = len(sa & sb) / float(len(sa | sb))
        if score < args.threshold:
            continue
        da = (video_data.get(a, {}).get("duration") or 0)
        db = (video_data.get(b, {}).get("duration") or 0)
        ratio = (min(da, db) / float(max(da, db))) if max(da, db) else 0.0
        ta = video_data.get(a, {}).get("title")
        tb = video_data.get(b, {}).get("title")
        if ratio < args.min_duration_ratio and not raw_trim_pair(ta, tb):
            excerpts.append((score, ratio, a, b))
        else:
            hits.append((score, a, b))
    hits.sort(reverse=True)
    excerpts.sort(reverse=True)

    def linked(a, b):
        return (video_data.get(a, {}).get("duplicate_id") == b
                or video_data.get(b, {}).get("duplicate_id") == a)

    fresh = [h for h in hits if not linked(h[1], h[2])]

    # Pairs further apart than the window are still duplicates if the text says
    # so -- that is the whole point of --all-pairs -- but the dates disagree,
    # so one of them is wrong and a human should say which. Never auto-marked.
    review = [h for h in fresh
              if (days_apart(video_data, h[1], h[2]) or 0) > args.window]
    fresh = [h for h in fresh if h not in review]
    print("pairs over threshold   : %d" % len(hits))
    print("  already marked       : %d" % (len(hits) - len(fresh)))
    print("  NOT marked           : %d" % len(fresh))
    print()
    for score, a, b in fresh:
        ea, eb = video_data.get(a, {}), video_data.get(b, {})
        print("  %.2f  %-12s %-28s %s" % (score, a, (ea.get("channel") or "")[:28],
                                          (ea.get("title") or "")[:40]))
        print("        %-12s %-28s %s" % (b, (eb.get("channel") or "")[:28],
                                          (eb.get("title") or "")[:40]))

    if review:
        print()
        print("  DATES DISAGREE -- duplicates whose dates are %d+ days apart." % args.window)
        print("  One date is wrong; the text says they are the same recording.")
        for score, a, b in review:
            print()
            for yt_id in (a, b):
                entry = video_data.get(yt_id, {})
                best, why = date_evidence(video_data, yt_id)
                print("    %.2f %-12s stored %-10s -> %-10s (%-21s) %s"
                      % (score, yt_id, entry.get("date"), best, why,
                         (entry.get("title") or "")[:38]))

    if excerpts:
        print()
        print("  EXCERPTS (similar but very different length -- NOT marked):")
        for score, ratio, a, b in excerpts:
            print("  %.2f  len-ratio %.2f  %-30s | %-30s"
                  % (score, ratio, (video_data.get(a, {}).get("title") or "")[:30],
                     (video_data.get(b, {}).get("title") or "")[:30]))

    if not args.apply:
        print("\nreport only; --apply marks the lower-priority copy skip")
        return 0

    changed = 0
    for score, a, b in fresh:
        ea, eb = video_data.get(a, {}), video_data.get(b, {})
        # same keeper rules as identify_duplicate_videos
        def rank(yt_id, entry):
            title = entry.get("title") or ""
            # a raw stream loses to its trimmed version regardless of source:
            # it is hours of dead air around the same meeting
            return (1 if RAW_MARKER.search(title) else 0,
                    0 if TRIM_MARKER.search(title) else 1,
                    utils._rank((entry.get("channel") or "").strip()),
                    0 if utils.has_transcript(yt_id, entry) else 1,
                    entry.get("duration") or 0,
                    yt_id)
        keeper, loser = (a, b) if rank(a, ea) <= rank(b, eb) else (b, a)
        entry = video_data[loser]
        if entry.get("manual_correction"):
            continue
        if entry.get("skip") and not entry.get("duplicate_id"):
            continue                      # a skip this tool did not set
        entry["skip"] = True
        entry["duplicate_id"] = keeper
        entry["duplicate_method"] = "transcript_similarity"
        entry["skip_reason"] = ("duplicate of %s (transcript similarity %.2f)"
                                % (keeper, score))
        video_data[keeper]["duplicate_id"] = loser
        changed += 1

    if changed:
        fresh_data = utils.get_video_data()          # reload right before saving
        for yt_id, entry in video_data.items():
            if yt_id in fresh_data and entry.get("duplicate_id"):
                fresh_data[yt_id]["duplicate_id"] = entry["duplicate_id"]
                if entry.get("skip"):
                    fresh_data[yt_id]["skip"] = True
                    fresh_data[yt_id]["duplicate_method"] = entry.get("duplicate_method")
                    fresh_data[yt_id]["skip_reason"] = entry.get("skip_reason")
        utils.save_video_data(fresh_data)
    print("\nmarked %d duplicates" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
