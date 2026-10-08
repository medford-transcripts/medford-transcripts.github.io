"""Identify a speaker cluster from the name Zoom draws on the video.

WHY THIS AND NOT THE TRANSCRIPT. Of the top 400 unidentified cross-matched
clusters, 63 are matcher artifacts and 328 are substantive -- and 232 of those
substantive ones (71%) never say a name anywhere in their own words or in the
turn before them. identify_from_text.py cannot reach them by construction.
Zoom can: it draws the ACTIVE SPEAKER'S OWN DISPLAY NAME on the frame.

VERIFIED BEFORE BUILDING. nqVIJ3wsDWg at t=12677 reads "Talking: BDan
Fairchild", matching the "B. Daniel Fairchild" he says aloud, and the address
record agrees. 10 seconds of video is ~244 KB through yt-dlp's
--download-sections, and one ffmpeg call pulls the frame.

IT IS ALSO MORE RELIABLE THAN THE TEXT WHERE BOTH EXIST. In that same meeting
the turn before his begins "Thank you, Mr. Lessenhaupt" -- the chair thanking
the PREVIOUS speaker -- and any name-before-the-turn heuristic reads that as
naming this voice. The overlay cannot make that mistake: it names whoever is
talking at that instant.

WHAT THE SAMPLE SHOWED, which is what this script has to cope with:
  * 2020-12-01 City Council -- participant name bottom-left on a full-screen
    speaker view ("Breanna Lungo-Koehn"). The good case.
  * 2026-10-01 CDB -- "Talking: <name>" bottom-right.
  * 2022-06-14 -- "Talking: Council Chambers". Names the ROOM, not a person,
    because the feed is the in-room camera. Must be rejected, not recorded.
  * 2024-12-11 -- Zoom SCREEN SHARE of a document: no name anywhere. During
    presentations there is nothing to read, so one frame is not enough.
  * 2025-05-08 -- a CAMERA-OFF participant: Zoom fills the frame with the
    display name in huge type ("Lauretta James"). The easiest case of all, and
    common at public hearings where commenters dial in without video. That one
    read named a voice in 30 meetings, and corrected the spelling the ASR had
    as "Loretta".
  * pre-2020 -- in-person chamber video, no annotation at all. Skipped.

JASON'S STEER, 2026-10-07: after 2020 most meetings are hybrid or Zoom-only,
so a speaker at the podium does not mean the next one is too. SUBCOMMITTEE
meetings are more often fully remote, so they are the lane to start in --
especially for a cluster that appears in both a subcommittee and a main
meeting, where the subcommittee frame names the voice and the match carries it
to the main meeting.

THIS SCRIPT PROPOSES, IT DOES NOT ASSIGN. It writes frames and a manifest; a
human or a vision model reads them. Review is cheaper than correction, and a
name written against the wrong voice is a false claim about a real person.

    python identify_from_video.py --list            # ranked candidates
    python identify_from_video.py --cluster <ph>    # frames for one cluster
    python identify_from_video.py --limit 10        # frames for the top N
"""

import argparse
import collections
import glob
import io
import json
import os
import re
import subprocess
import sys

import utils
import srt_lines

FRAMES = "video_id_frames"
MANIFEST = os.path.join(FRAMES, "manifest.json")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# An 11-character video id, an underscore, the speaker key -- the same shape
# track_speakers.propagate() parses, kept identical on purpose.
CROSS = re.compile(r"^(.{11})_(SPEAKER_\d+)$")
# Only YouTube ids can be sliced cheaply; MCM/CAS/XXXXXX need their own
# downloaders, so they are out of scope here rather than silently failing.
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Below these a cluster is not a person worth naming: a wide match count on a
# few seconds of "Thank you." is the matcher latching onto generic filler, and
# short turns are where attribution is weakest anyway.
MIN_WORDS = 50
MIN_SECONDS = 20
# Zoom overlays start with remote meetings; before that the video is an
# in-person chamber camera with nothing drawn on it.
FIRST_REMOTE_DATE = "2020-03-01"

# Names the overlay gives that are not people.
NOT_A_PERSON = re.compile(
    r"^(council chambers?|chambers?|city hall|conference room|room \w+|"
    r"zoom|meeting|host|co-?host|unknown|guest|ipad|iphone|android|user)\b",
    re.I)


def cluster_counts(video_data):
    """{placeholder: [(video_id, speaker_key), ...]} for unidentified clusters."""
    out = collections.defaultdict(list)
    for f in glob.glob(os.path.join("20*_*", "speaker_ids.json")):
        yt = os.path.basename(os.path.dirname(f)).split("_", 1)[1]
        if (video_data.get(yt) or {}).get("skip"):
            continue
        try:
            with io.open(f, encoding="utf-8") as fp:
                ids = json.load(fp)
        except (ValueError, OSError):
            continue
        for k, v in ids.items():
            if CROSS.match(str(v)):
                out[str(v)].append((yt, k))
    return out


def speech_in(video_data, yt, speaker):
    """(blocks, words, seconds) that this cluster speaks in its home meeting."""
    e = video_data.get(yt) or {}
    d = "%s_%s" % (e.get("upload_date"), yt)
    p = os.path.join(d, d + ".srt")
    if not os.path.exists(p):
        return [], 0, 0.0
    try:
        with io.open(p, encoding="utf-8", errors="replace") as fp:
            blocks = srt_lines.parse_srt(fp.read())
    except Exception:
        return [], 0, 0.0
    mine = [b for b in blocks if (b.get("speaker") or "") == speaker]
    words = sum(len((b.get("text") or "").split()) for b in mine)
    secs = sum((b.get("end") or 0) - (b.get("start") or 0) for b in mine)
    return mine, words, secs


_N = r"[A-Z][a-zA-Z'\-]{1,}(?:\s+[A-Z][a-zA-Z'\-]{1,}){0,3}"
SELF_ID = [re.compile(p) for p in (
    # [Mm] rather than re.I: the flag would also make the NAME group
    # case-insensitive, and capitalisation is most of what distinguishes a
    # name from the words around it.
    r"\b[Mm]y name is\s+(" + _N + r")",
    r"\bI'?m\s+(" + _N + r")\s*[,.]",
    r"(" + _N + r"),\s*\d+\s+[A-Z][a-z]+",
)]


def transcript_says(blocks):
    """The name this cluster gives for itself, if any.

    THIS IS THE SWEEP'S OWN GROUND TRUTH. 110 of the 676 substantive
    unidentified clusters state a name in their own words. Running the video
    path over those too costs nothing extra and turns the sweep into its own
    measurement: where the frame and the transcript both produce a name, their
    agreement IS the error rate, with no separate labelling pass to arrange.

    A disagreement is informative in both directions -- the overlay carries a
    chosen display name and the transcript carries what ASR heard, so
    "Lauretta" against "Loretta" is the overlay being right, while a frame
    naming the previous speaker would be the overlay being wrong.
    """
    own = " ".join((b.get("text") or "") for b in blocks)
    for rx in SELF_ID:
        hit = rx.findall(own)
        if hit:
            return hit[0]
    return None


def is_subcommittee(entry):
    """Jason's steer: subcommittees are more often fully remote."""
    mt = (entry.get("meeting_type") or "")
    t = (entry.get("title") or "").lower()
    if re.search(r"subcommittee|advisory|task force|working group", t):
        return True
    # a main body is City Council / School Committee itself; anything else
    # under CC/MPS is a committee or commission of it
    return bool(mt.startswith(("CC ", "MPS "))
                and mt not in ("CC City Council", "MPS School Committee"))


def meetings_for(video_data, placeholder, refs):
    """Every meeting this cluster speaks in, best place to read a name first.

    THE HOME MEETING IS NOT ALWAYS THE RIGHT ONE. The home is wherever the
    placeholder happened to be minted, and if the speaker was AT THE PODIUM
    there, the overlay names the room -- "Talking: Council Chambers" -- and no
    timestamp in that meeting will ever do better, because the label describes
    the camera feed rather than the person. Measured: three of nine reads
    failed this way, and a second frame in the same meeting changed nothing.

    But a cluster referenced by 18 meetings has 18 chances, and the same person
    who sat in the chamber one week dialled in the next. So the meetings are
    ranked and tried in order: fully-remote-looking subcommittees first, then
    by date within the peak-Zoom window.
    """
    m = CROSS.match(placeholder)
    out = []
    seen = set()
    for yt, spk in [(m.group(1), m.group(2))] + list(refs):
        if (yt, spk) in seen:
            continue
        seen.add((yt, spk))
        e = video_data.get(yt) or {}
        if not YT_ID.match(yt) or yt.startswith(("MCM", "CAS", "XXXXXX")):
            continue                      # cannot be sliced yet
        date = (e.get("date") or "")[:10]
        if date < FIRST_REMOTE_DATE:
            continue                      # no overlay exists
        out.append((not is_subcommittee(e), date, yt, spk))
    out.sort()
    return [(yt, spk) for _sub, _d, yt, spk in out]


def candidates(video_data, limit=0):
    """Ranked clusters worth spending a download on."""
    rows = []
    for ph, refs in cluster_counts(video_data).items():
        m = CROSS.match(ph)
        home_yt, speaker = m.group(1), m.group(2)
        if not YT_ID.match(home_yt) or home_yt.startswith(("MCM", "CAS", "XXXXXX")):
            continue
        e = video_data.get(home_yt) or {}
        date = (e.get("date") or "")[:10]
        if date < FIRST_REMOTE_DATE:
            continue                       # no overlay to read
        mine, words, secs = speech_in(video_data, home_yt, speaker)
        if words < MIN_WORDS or secs < MIN_SECONDS:
            continue                       # matcher artifact, not a person
        rows.append({
            "placeholder": ph,
            "home": home_yt,
            "speaker": speaker,
            "meetings": len(refs),
            "words": words,
            "seconds": round(secs, 1),
            "date": date,
            "subcommittee": is_subcommittee(e),
            "title": (e.get("title") or "")[:60],
        })
    # subcommittees first (more often remote), then by how many meetings one
    # name would clear, then by how much speech there is to land a frame on
    rows.sort(key=lambda r: (not r["subcommittee"], -r["meetings"], -r["words"]))
    return rows[:limit] if limit else rows


def dialogue_times(all_blocks, speaker, n=3):
    """Moments where the target is in CONVERSATION, not presenting.

    A SCREEN SHARE IS A MONOLOGUE, so the way to avoid landing on one is to
    pick moments that cannot be a monologue: a turn by the target with a
    DIFFERENT speaker immediately before and after it. Somebody mid-presentation
    does not get interrupted on both sides.

    This was the single biggest miss in the first sample -- 4 of 5 failures
    were screen shares, because frame_times() had taken the LONGEST turns, and
    a long turn is exactly a presentation.
    """
    out = []
    for i, b in enumerate(all_blocks):
        if (b.get("speaker") or "") != speaker:
            continue
        if i == 0 or i + 1 >= len(all_blocks):
            continue
        before = all_blocks[i - 1].get("speaker") or ""
        after = all_blocks[i + 1].get("speaker") or ""
        if before == speaker or after == speaker:
            continue                       # inside a run of their own turns
        s, e = b.get("start") or 0, b.get("end") or 0
        if e - s < 1.5:
            continue
        out.append((e - s, int(s + (e - s) * 0.5)))
    # longest of the genuinely conversational moments: still needs enough
    # speech for the active-speaker view to have switched to them
    out.sort(reverse=True)
    return [t for _d, t in out[:n]]


def frame_times(blocks, n=3):
    """Timestamps to sample, spread across turn LENGTHS rather than taking the
    longest.

    SAMPLING THE LONGEST TURNS SELECTS FOR THE ONE VIEW WITH NO NAME ON IT.
    The first version took the three longest turns, reasoning that a long turn
    is the safest place to land. Measured on nine clusters, that produced 4
    screen shares out of 5 misses: a long turn is a PRESENTATION, and while
    someone presents Zoom shows their slides, not their name card. The sampler
    was selecting against its own purpose.

    So the sample spreads instead:
      * the speaker's FIRST turn -- usually the introduction, on camera,
        before any share starts
      * a SHORT turn -- answering a question, rarely during their own share
      * a long turn, which is still the best case when nobody is sharing

    Each lands mid-block rather than at an edge, so the frame is inside the
    speech rather than on the handover.
    """
    usable = [b for b in blocks
              if ((b.get("end") or 0) - (b.get("start") or 0)) >= 1.5]
    if not usable:
        return []
    by_time = sorted(usable, key=lambda b: b.get("start") or 0)
    by_len = sorted(usable, key=lambda b: (b.get("end") or 0) - (b.get("start") or 0))
    picks, seen = [], set()
    for b in (by_time[0], by_len[len(by_len) // 3], by_len[-1]):
        s, e = b.get("start") or 0, b.get("end") or 0
        t = int(s + (e - s) * 0.5)
        if t not in seen:
            seen.add(t)
            picks.append(t)
    return picks[:n]


def grab(yt, seconds, dest, window=12, every=4):
    """Frames across a `window` of video. Returns the list written.

    SEVERAL FRAMES PER DOWNLOAD, because the download is the expensive part and
    the frames are free. A 12-second slice costs about the same as a 4-second
    one at these bitrates, and sampling it every few seconds spans a view
    change -- a share ending, the active-speaker tile switching, a name card
    appearing -- where a single frame caught whatever was on screen at one
    instant.
    """
    import yt_dlp
    tmp = dest + ".slice"
    for p in glob.glob(tmp + ".*"):
        os.remove(p)
    opts = {"format": "bestvideo[height<=720]/best[height<=720]/best",
            "outtmpl": tmp + ".%(ext)s",
            "download_ranges": yt_dlp.utils.download_range_func(
                None, [(seconds, seconds + window)]),
            "force_keyframes_at_cuts": True,
            "quiet": True, "no_warnings": True}
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.download(["https://www.youtube.com/watch?v=" + yt])
    except Exception as exc:
        print("    download failed: %s" % str(exc)[:70])
        return False
    media = glob.glob(tmp + ".*")
    if not media:
        return False
    pattern = dest.replace(".png", "_%02d.png")
    try:
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", media[0], "-vf", "fps=1/%d" % every,
                        "-frames:v", str(max(1, window // every)), pattern],
                       check=True)
    except Exception as exc:
        print("    ffmpeg failed: %s" % str(exc)[:70])
        return []
    finally:
        for p in media:
            try:
                os.remove(p)
            except OSError:
                pass
    return sorted(glob.glob(dest.replace(".png", "_*.png")))


def plausible_name(text):
    """Is an overlay string a person? "Council Chambers" is not."""
    t = (text or "").strip()
    if not t or NOT_A_PERSON.match(t):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+){1,3}$", t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="ranked candidates only")
    ap.add_argument("--cluster", help="one placeholder, e.g. abc12345678_SPEAKER_04")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--frames", type=int, default=3, help="frames per cluster")
    args = ap.parse_args()

    vd = utils.get_video_data()
    rows = candidates(vd)
    if args.cluster:
        rows = [r for r in rows if r["placeholder"] == args.cluster]
        if not rows:
            print("no candidate matches %r (too little speech, pre-2020, or "
                  "not a YouTube id)" % args.cluster)
            return 1

    if args.list or not (args.cluster or args.limit):
        print("%-26s %5s %6s %6s %-11s %-4s %s"
              % ("placeholder", "mtgs", "words", "secs", "date", "sub?", "home"))
        for r in rows[:args.limit or 40]:
            print("%-26s %5d %6d %6.0f %-11s %-4s %s"
                  % (r["placeholder"], r["meetings"], r["words"], r["seconds"],
                     r["date"], "yes" if r["subcommittee"] else "", r["title"][:34]))
        print()
        print("%d candidates (>=%d words, >=%ds, on or after %s, YouTube-hosted)"
              % (len(rows), MIN_WORDS, MIN_SECONDS, FIRST_REMOTE_DATE))
        print("subcommittees first: more often fully remote, so more likely to")
        print("carry a Zoom name overlay.")
        return 0

    todo = rows[:args.limit] if args.limit else rows
    os.makedirs(FRAMES, exist_ok=True)
    manifest = []
    if os.path.exists(MANIFEST):
        try:
            with io.open(MANIFEST, encoding="utf-8") as fp:
                manifest = json.load(fp)
        except ValueError:
            manifest = []
    done = {m["frame"] for m in manifest}

    for r in todo:
        mine, _w, _s = speech_in(vd, r["home"], r["speaker"])
        says = transcript_says(mine)
        times = frame_times(mine, args.frames)
        print("%s  (%d meetings, %s)" % (r["placeholder"], r["meetings"], r["title"][:40]))
        for t in times:
            dest = os.path.join(FRAMES, "%s_%s_t%d.png"
                                % (r["home"], r["speaker"], t))
            if dest in done or os.path.exists(dest):
                continue
            if grab(r["home"], t, dest):
                print("    frame at t=%ds -> %s" % (t, dest))
                manifest.append({"placeholder": r["placeholder"],
                                 "home": r["home"], "speaker": r["speaker"],
                                 "t": t, "frame": dest,
                                 "meetings": r["meetings"],
                                 "transcript_says": says,
                                 "read": None})
    with io.open(MANIFEST, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(manifest, fp, indent=2, ensure_ascii=False)
    print()
    print("wrote %d frames, manifest %s" % (len(manifest), MANIFEST))
    print("Read each frame and fill in \"read\". Reject anything plausible_name()")
    print("refuses -- \"Talking: Council Chambers\" names the room, not a person.")
    print("Then name the CLUSTER HOME, not the local label, so propagate()")
    print("carries it to every meeting that references the placeholder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
