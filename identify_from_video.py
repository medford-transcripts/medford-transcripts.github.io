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
  * LIVE CAPTIONS WITH AVATAR INITIALS, and they are the best signal of all.
    When Zoom captions are on, each caption line carries the speaker's
    initials in a coloured chip. That is Zoom attributing the utterance
    directly, so unlike the active-speaker tile it has NO view-switch lag and
    works on turns far too short to move the view. On O1CMBj7JDes_SPEAKER_03
    every target strip was "weak" by duration, yet the chips read CB / EH / DE
    exactly where the SRT has the target, SPEAKER_08 and SPEAKER_05 -- against
    name tags "Christopher Bader", "Emily Hedeman", "Danielle Evans, PDS".
    Three confirmations in one tile.
  * A SLIDE IS NOT AN OVERLAY. UdfiATpNBs8_SPEAKER_12 shared a deck whose
    visible line read "10. Nicole Morell" -- a bullet in the content, not a
    Zoom label. Text inside a screen share names nothing, and reading it as a
    speaker is how the earlier title-cue pass wrote organisations in as
    people. Only the chrome Zoom draws counts.

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
STATE = os.path.join(FRAMES, "sweep.json")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# The overlay only ever occupies a band along the bottom of the frame -- the
# participant name bottom-left, "Talking: <name>" bottom-right. Cropping to
# that band and stacking a cluster's frames into ONE image is what makes a
# 277-cluster sweep affordable to read: one image per cluster-attempt instead
# of one per frame, and the strip keeps full pixel detail where a downscaled
# whole frame loses the very text being read.
STRIP_FRACTION = 0.18
# Verdicts that mean "this meeting will never name this person", so the next
# sweep should try the next meeting. "room" is the important one: the overlay
# named the camera feed, and no other timestamp in that meeting can do better.
FAILED = ("room", "blank", "share", "unreadable", "download_failed", "rejected",
          "ambiguous", "partial")
# Gallery view defeats the strip crop: several names are visible and the green
# active-speaker border -- the only thing that says which one is talking -- is
# at the TILE edge, above the band. Naming the cluster from a strip like that
# would be a one-in-four guess, which is the closed-set error §4 exists to
# avoid. So "gallery" is not a failure: it promotes the SAME attempt to a
# full-frame read, which costs nothing because the frames are already on disk.
#
# DO NOT HARVEST THE GALLERY. A gallery frame shows every participant's display
# name at once, and it is tempting to keep them as a per-meeting candidate set,
# since closed-set error falls steeply with set size. That set is an ATTENDANCE
# RECORD of people who never spoke, which PRINCIPLES.md §2 forbids outright --
# "never identify, never index, never count". Read the frame for the ACTIVE
# SPEAKER and keep nothing else from it.
#
# Measured: the first promotion did not resolve (s093VSbtp08, 12 tiles, no
# active-speaker border rendered in the broadcast encode). The tier is kept
# because it costs no download, and report() counts what it actually yields.
STAGES = ("strip", "full")
# One download covers GRAB_WINDOW seconds and ffmpeg samples it every
# GRAB_EVERY, so frame k of a slice starting at t sits at t + (k-1)*GRAB_EVERY.
# They are constants rather than defaults buried in grab() because
# frame_legend() reconstructs those times to say who was talking in each strip,
# and a legend that drifted from the grabber would mislabel every read.
GRAB_WINDOW = 12
GRAB_EVERY = 4
# Seconds of continuous speech before Zoom's active-speaker view can be trusted
# to have switched to the person talking. Below this the tile on screen may
# still be the PREVIOUS speaker, so the strip is marked weak and does not
# support a name on its own.
#
# RAISED FROM 3.0 ON DIRECT EVIDENCE. 8msxsKW1z_4_SPEAKER_26 contradicted
# itself inside one tile: a 3.9-second turn read "Talking: Alicia Hunt", while
# three strips inside a 15.6-second turn by the same cluster read "Margaret
# Moran" on both overlay formats at once. 3.9s cleared the old threshold and
# still named the previous speaker, so the threshold was wrong, not the
# overlay. A quick interjection is exactly when the view has not caught up.
MIN_TURN_FOR_VIEW = 5.0

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
# A DEVICE name is not a person either, and it does not come first: Zoom's
# default for a phone is "<owner>'s iPhone", which sails past NOT_A_PERSON
# because that anchors at the start. "MD'orsi's iPhone" named a tile in the
# very first gallery read -- it looks exactly like a two-word name.
A_DEVICE = re.compile(
    r"\b(i[Pp]hone|iPad|Android|Galaxy|Pixel|laptop|phone|tablet|"
    r"computer|desktop|pc|mac(?:book)?)\s*$", re.I)


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


def parse_meeting(video_data, yt):
    """Every block of one meeting's SRT, or [] if there is no transcript.

    Separate from speech_in() because dialogue_times() needs the speakers
    AROUND the target, not just the target's own turns.
    """
    e = video_data.get(yt) or {}
    d = "%s_%s" % (e.get("upload_date"), yt)
    p = os.path.join(d, d + ".srt")
    if not os.path.exists(p):
        return []
    try:
        with io.open(p, encoding="utf-8", errors="replace") as fp:
            return srt_lines.parse_srt(fp.read())
    except Exception:
        return []


def speech_in(video_data, yt, speaker):
    """(blocks, words, seconds) that this cluster speaks in one meeting."""
    blocks = parse_meeting(video_data, yt)
    mine = [b for b in blocks if (b.get("speaker") or "") == speaker]
    words = sum(len((b.get("text") or "").split()) for b in mine)
    secs = sum((b.get("end") or 0) - (b.get("start") or 0) for b in mine)
    return mine, words, secs


_N = r"[A-Z][a-zA-Z'\-]{1,}(?:\s+[A-Z][a-zA-Z'\-]{1,}){0,3}"
SELF_ID = [re.compile(p) for p in (
    # [Mm] rather than re.I: the flag would also make the NAME group
    # case-insensitive, and capitalisation is most of what distinguishes a
    # name from the words around it.
    # "My name's Barbara Vivian" -- the contraction, which the "is" form misses
    # entirely. Found on 6zUtu0XZLH4_SPEAKER_05, whose frames all read "Council
    # Chambers": the video route is blind in the room, and the text names her.
    r"\b[Mm]y name(?:'s| is)\s+(" + _N + r")",
    r"\bI'?m\s+(" + _N + r")\s*[,.]",
    r"(" + _N + r"),\s*\d+\s+[A-Z][a-z]+",
    # "I'm the architect, Jacob Levine, representing ..." -- the role comes
    # first and the pattern above stops at it. Found in the legend for
    # O1CMBj7JDes_SPEAKER_04, whose frames are all screen share: the video
    # route is blind there and the text names him outright. The role segment
    # is required to be lower-case so this cannot swallow a different name.
    r"\bI'?m\s+(?:the|a|an)\s+[a-z][a-z ]{2,30},\s+(" + _N + r")",
    # "This is Ben Minnix with Eagle Brook Engineering", "this is Andre LaRue,
    # the chair". The trailing with/from/comma is required so this cannot
    # swallow "This is Medford City Council" -- and plausible_name() below is
    # the backstop for whatever it does swallow.
    r"\b[Tt]his is\s+(" + _N + r")\s*(?:,|\s+(?:with|from)\b)",
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
        for hit in rx.findall(own):
            # GROUND TRUTH THAT IS WRONG CORRUPTS THE ONE NUMBER THIS SWEEP
            # PRODUCES. An earlier pass scraped a firm's logo out of a frame
            # and scored it as a name, so every hit goes through the same
            # person test the overlay reads do -- which also enforces the
            # full-name-only rule, since a lone surname cannot be checked.
            if plausible_name(hit):
                return clean_overlay_name(hit)
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


def dialogue_times(all_blocks, speaker, n=3, floor=MIN_TURN_FOR_VIEW):
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
        if e - s < floor:
            continue
        out.append((e - s, int(s + (e - s) * 0.5)))
    # longest of the genuinely conversational moments: still needs enough
    # speech for the active-speaker view to have switched to them
    out.sort(reverse=True)
    return [t for _d, t in out[:n]]


def frame_times(blocks, n=3, floor=MIN_TURN_FOR_VIEW):
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
              if ((b.get("end") or 0) - (b.get("start") or 0)) >= floor]
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


def grab(yt, seconds, dest, window=GRAB_WINDOW, every=GRAB_EVERY):
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


def clean_overlay_name(text):
    """Strip the affiliation people hang off a Zoom display name.

    Observed in the first five reads, which is why this exists: "Michael
    Barone, Jr. (RIW)", "Libby Brown | Goody Clancy", "Marta Cabral- MHS
    Principal". Without this, plausible_name() refuses all three and three good
    reads are recorded as rejections -- a silent coverage loss that would have
    looked like the overlay failing rather than the parser.

    The affiliation is dropped rather than kept: a role belongs in the roster
    files, which resolve it BY MEETING DATE, and freezing "MHS Principal" into
    a name would outlive the job.
    """
    t = (text or "").strip()
    t = re.sub(r"\s*\((?:[^()]*)\)\s*$", "", t)        # trailing (RIW)
    t = re.split(r"\s*[|/]\s*", t)[0]                  # Name | Firm
    t = re.sub(r"\s*[-–—]\s+.*$", "", t)     # Name - Role
    t = re.sub(r"(\w)-\s+.*$", r"\1", t)               # Name- Role, no space
    t = re.sub(r",\s*(Jr|Sr|II|III|IV)\.?$", r" \1", t, flags=re.I)
    # ", Chair" / ", member" / ", Ward 3" -- a role appended after a comma.
    # Done AFTER the suffix rewrite above, so "Barone, Jr." is already " Jr"
    # and cannot be eaten here.
    t = re.sub(r",.*$", "", t)
    # A personal honorific is not part of the name. Only these -- NOT civic
    # roles like "Councilor", which titles.strip_role() handles against the
    # known-names set, because a role is resolved from the rosters BY MEETING
    # DATE and must never be frozen into a speaker name.
    t = re.sub(r"^(?:Dr|Mr|Mrs|Ms|Miss|Rev|Prof|Hon|Sir|Atty)\.?\s+", "", t,
               flags=re.I)
    return t.strip().strip(",").strip()


def surname_agreement(says, name):
    """Compare the spoken name to the overlay name. (agrees, how).

    EXACT EQUALITY WOULD OVERSTATE THE ERROR RATE, which is the one number this
    sweep exists to produce. The two sources are not the same kind of thing:
    the overlay is a display name the person typed, and the transcript is what
    ASR heard them say. "Georges Fischer" against a spoken "George Fisher" is
    not the overlay being wrong -- it is the overlay CORRECTING the spelling,
    which is the same case as "Lauretta" against the ASR's "Loretta", and the
    reason the overlay is worth reading at all.

    So three outcomes, counted separately rather than collapsed: exact, variant
    (a near-identical surname, scored as agreement because it is one), and
    disagree -- a different person, which is the only real error.
    """
    import difflib
    a = (says or "").split()
    b = (name or "").split()
    if not a or not b:
        return False, "unknown"
    sa, sb = a[-1].lower().strip(".,"), b[-1].lower().strip(".,")
    if sa == sb:
        return True, "exact"
    if difflib.SequenceMatcher(None, sa, sb).ratio() >= 0.8:
        return True, "variant"
    return False, "disagree"


def plausible_name(text):
    """Is an overlay string a person? "Council Chambers" is not."""
    t = clean_overlay_name(text)
    if not t or NOT_A_PERSON.match(t) or A_DEVICE.search(t):
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+){1,3}$", t))


def load_state():
    if os.path.exists(STATE):
        try:
            with io.open(STATE, encoding="utf-8") as fp:
                return json.load(fp)
        except ValueError:
            print("  %s is not valid JSON; refusing to overwrite it" % STATE)
            raise
    return {}


def save_state(state):
    tmp = STATE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(state, fp, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, STATE)


def save_clusters(updates):
    """Merge these clusters into the file on disk, under a lock.

    A WHOLE-FILE WRITE FROM EITHER SIDE DESTROYS THE OTHER'S WORK. --sweep runs
    for hours holding the state dict in memory, and --record runs between its
    downloads; the first full run clobbered two names that had just been
    recorded, because the sweep's next save wrote back a dict loaded before
    they existed. Exactly the hazard CLAUDE.md records for create_subtitles.py
    saving all of video_data without re-reading.

    So neither side ever writes the whole file from memory: both re-read, merge
    only the clusters they actually changed, and write under the same
    owner-aware lock video_data.json uses, so a killed writer cannot wedge it.
    """
    lock = os.path.join(FRAMES, "sweep.lock")
    os.makedirs(FRAMES, exist_ok=True)
    utils.wait_for_lock(lock)
    with io.open(lock, "w", encoding="utf-8") as fp:
        fp.write(str(os.getpid()))
    try:
        state = load_state()
        state.update(updates)
        save_state(state)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    return state


def strip_tile(frames, dest, fraction=STRIP_FRACTION):
    """Crop each frame to its bottom band and stack the bands into one image."""
    from PIL import Image
    strips = []
    for p in frames:
        try:
            im = Image.open(p)
        except Exception:
            continue
        w, h = im.size
        strips.append(im.crop((0, int(h * (1.0 - fraction)), w, h)).convert("RGB"))
    if not strips:
        return None
    w = max(s.size[0] for s in strips)
    gap = 3
    tile = Image.new("RGB", (w, sum(s.size[1] for s in strips)
                             + gap * (len(strips) - 1)), (255, 0, 255))
    y = 0
    for s in strips:
        tile.paste(s, (0, y))            # magenta seams, so a join between two
        y += s.size[1] + gap             # strips is never read as content
    tile.save(dest)
    return dest


def open_attempt(rec):
    """The attempt still waiting on a read, if any."""
    for a in rec.get("attempts", []):
        if a.get("verdict") is None:
            return a
    return None


def next_meeting(video_data, placeholder, refs, rec):
    """The next meeting to try for this cluster -- THIS IS THE FALLBACK.

    meetings_for() ranks every meeting the cluster speaks in; this walks that
    ranking and returns the first one not already attempted. So a cluster whose
    best meeting answered "Talking: Council Chambers" advances to its second
    meeting on the next sweep WITHOUT anyone choosing it, which is the whole
    point of keeping state: the reader only ever answers "is there a name in
    this image", and the script owns which meeting that image came from and
    when to give up.

    Measured 2026-10-07: 199 of 277 candidates (72%) have a second meeting to
    fall back to. The other 78 are single-referrer or their referrers are
    MCM/CAS-hosted, which cannot be sliced until a Castus slicer exists.

    A "room" verdict bars the WHOLE meeting, not just the speaker key that was
    tried: "Talking: Council Chambers" describes the camera feed, so no other
    timestamp or local label in that meeting can do better. Any other failure
    bars only the exact (meeting, speaker key) pair, because a cluster split
    across two keys in one meeting has two genuinely different sets of
    timestamps to land on.
    """
    dead = {a.get("yt") for a in rec.get("attempts", [])
            if a.get("verdict") == "room"}
    done = {(a.get("yt"), a.get("speaker")) for a in rec.get("attempts", [])}
    for yt, spk in meetings_for(video_data, placeholder, refs):
        if yt not in dead and (yt, spk) not in done:
            return yt, spk
    return None, None


def sample_times(video_data, yt, speaker, n):
    """Timestamps to grab: conversational moments first, spread turns to fill."""
    allb = parse_meeting(video_data, yt)
    mine = [b for b in allb if (b.get("speaker") or "") == speaker]
    times = dialogue_times(allb, speaker, n)
    if not times:
        # a cluster of consistently short turns still deserves an attempt; the
        # legend marks those strips weak so the read cannot lean on them
        times = dialogue_times(allb, speaker, n, floor=1.5)
    for t in frame_times(mine, n) or frame_times(mine, n, floor=1.5):
        if len(times) >= n:
            break
        if t not in times:
            times.append(t)
    return times, mine


def sweep(video_data, rows, counts, limit=0, per=3):
    """Grab one attempt's frames for every cluster that is due one."""
    state = load_state()
    os.makedirs(FRAMES, exist_ok=True)
    pending, grabbed, exhausted, failed = [], 0, 0, 0
    for r in rows:
        ph = r["placeholder"]
        rec = state.setdefault(ph, {"placeholder": ph, "status": "new",
                                    "meetings": r["meetings"],
                                    "transcript_says": None, "attempts": []})
        if rec.get("status") in ("named", "exhausted"):
            continue
        if open_attempt(rec):
            pending.append(ph)             # already waiting on a read
            continue
        yt, spk = next_meeting(video_data, ph, counts.get(ph, []), rec)
        if not yt:
            # every readable meeting tried and none named them
            rec["status"] = "exhausted"
            exhausted += 1
            save_clusters({ph: rec})
            continue
        if limit and grabbed >= limit:
            break
        times, mine = sample_times(video_data, yt, spk, per)
        if rec.get("transcript_says") is None:
            rec["transcript_says"] = transcript_says(mine)
        rank = len(rec["attempts"]) + 1
        print("%s  attempt %d: %s %s t=%s"
              % (ph, rank, yt, spk, ",".join(str(t) for t in times) or "-"))
        attempt = {"yt": yt, "speaker": spk, "rank": rank,
                   "date": ((video_data.get(yt) or {}).get("date") or "")[:10],
                   "times": times, "frames": [], "tile": None,
                   "stage": "strip",
                   "verdict": None, "name": None}
        pngs = []
        for t in times:
            dest = os.path.join(FRAMES, "%s_%s_t%d.png" % (yt, spk, t))
            got = grab(yt, t, dest)
            if got:
                pngs.extend(got)
        if not pngs:
            # a failed download is a failed attempt, so the cluster falls back
            # to its next meeting rather than stalling here
            attempt["verdict"] = "download_failed"
            rec["attempts"].append(attempt)
            rec["status"] = "retry"
            failed += 1
        else:
            attempt["frames"] = pngs
            attempt["tile"] = strip_tile(
                pngs, os.path.join(FRAMES, "tile_%s_a%d.png" % (ph, rank)))
            rec["attempts"].append(attempt)
            rec["status"] = "pending_read"
            pending.append(ph)
            grabbed += 1
            print("    %d frames -> %s" % (len(pngs), attempt["tile"]))
        save_clusters({ph: rec})           # after each cluster: an interrupted
                                           # sweep loses one download, not all
    print()
    print("grabbed %d, download-failed %d, exhausted %d, awaiting a read %d"
          % (grabbed, failed, exhausted, len(pending)))
    if pending:
        print()
        print("Read each tile, then record verdicts:")
        print("  python identify_from_video.py --record - <<'EOF'")
        print("  <placeholder>  <name as the overlay spells it>")
        print("  <placeholder>  room        # overlay named the feed, not a person")
        print("  <placeholder>  blank       # screen share or no overlay")
        print("  EOF")
        print("A failed verdict advances that cluster to its next meeting on")
        print("the following --sweep. Nothing is written to speaker_ids.json")
        print("here; naming goes through apply_corrections at the cluster HOME.")
    return 0


def record(lines):
    """Take read verdicts; a name ends the cluster, a failure triggers fallback."""
    state = load_state()
    named = failed = bad = promoted = 0
    touched = set()
    for raw in lines:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split(None, 1)         # placeholders never contain a space
        if len(parts) != 2:
            print("  ? cannot parse %r" % raw[:60])
            bad += 1
            continue
        ph, verdict = parts[0], parts[1].strip()
        rec = state.get(ph)
        touched.add(ph)
        if not rec:
            print("  ? %s is not in the sweep" % ph)
            bad += 1
            continue
        a = open_attempt(rec)
        if not a:
            print("  ? %s has no attempt awaiting a read" % ph)
            bad += 1
            continue
        low = verdict.lower()
        if low in ("gallery", "tiles") and a.get("stage", "strip") == "strip":
            # promote to a full-frame read of the SAME frames: free, and the
            # active-speaker border is the only thing that disambiguates
            a["stage"] = "full"
            promoted += 1
            continue
        if low.startswith(("partial:", "first:", "handle:")):
            # a display name that is not a full name -- "Caroline", "PNoone".
            # Real information, and too little to write a name on: keep the
            # fragment for a later closed-set resolution and fall back anyway.
            a["verdict"] = "partial"
            a["name"] = verdict.split(":", 1)[1].strip()
            rec.setdefault("fragments", []).append(a["name"])
            rec["status"] = "retry"
            failed += 1
        elif low in FAILED or low in ("none", "no", "nothing", "gallery", "tiles"):
            a["verdict"] = low if low in FAILED else "blank"
            rec["status"] = "retry"
            failed += 1
        elif plausible_name(verdict):
            a["verdict"] = "name"
            a["name"] = clean_overlay_name(verdict)
            a["overlay"] = verdict
            rec["status"] = "named"
            rec["name"] = a["name"]
            says = rec.get("transcript_says")
            if says:
                rec["agrees"], rec["agreement"] = surname_agreement(
                    says, a["name"])
            named += 1
        else:
            # plausible_name() refuses it. A room label typed in as though it
            # were a person is exactly the mistake this rule exists to catch,
            # so the read does not get the last word -- the cluster falls back.
            print("  ! %s: %r is not a plausible person; recorded as rejected"
                  % (ph, verdict[:40]))
            a["verdict"] = "rejected"
            a["name"] = verdict
            rec["status"] = "retry"
            failed += 1
    save_clusters({k: state[k] for k in touched if k in state})
    print("recorded %d names, %d failures, %d promoted to a full-frame read, "
          "%d unparsed" % (named, failed, promoted, bad))
    return 1 if bad else 0


FRAME_AT = re.compile(r"_t(\d+)_(\d+)\.png$")


def frame_legend(video_data, attempt, target):
    """Who the TRANSCRIPT says is talking in each strip, top to bottom.

    THE WINDOW CAN CROSS SPEAKERS, and when it does the tile is unreadable
    without this. O1CMBj7JDes_SPEAKER_00's second window showed three different
    people in 12 seconds -- "Sharad Bajracharya, Member", "Jacquie McPherson,
    Chair", "Amanda Centrella she/her, City Staff" -- and nothing in the image
    says which one is the cluster being named. Guessing there is precisely the
    one-in-three error §4 exists to prevent.

    But the frame times are deterministic, so the SRT can say it: strip k of a
    slice starting at t is at t + (k-1)*GRAB_EVERY, and the block covering that
    second names the speaker. The read stops being "which of these people is
    it" and becomes "what name is on the strip the target is talking in".
    """
    blocks = parse_meeting(video_data, attempt.get("yt") or "")
    out = []
    for p in attempt.get("frames") or []:
        m = FRAME_AT.search(p)
        if not m:
            continue
        t = int(m.group(1)) + (int(m.group(2)) - 1) * GRAB_EVERY
        spk, text, dur = "", "", 0.0
        for b in blocks:
            if (b.get("start") or 0) <= t <= (b.get("end") or 0):
                spk = b.get("speaker") or ""
                text = " ".join((b.get("text") or "").split())[:46]
                dur = (b.get("end") or 0) - (b.get("start") or 0)
                break
        out.append({"frame": os.path.basename(p), "t": t, "speaker": spk,
                    "is_target": spk == target, "text": text,
                    "dur": round(dur, 1),
                    # Zoom switches the active-speaker view on SUSTAINED
                    # speech, so a two-word "Thank you very much." can leave
                    # the PREVIOUS speaker's tile on screen. A strip on a turn
                    # that short names the wrong person as often as the right
                    # one -- the same place short-turn attribution already
                    # measures 53-66% against a human reference.
                    "weak": spk == target and dur < MIN_TURN_FOR_VIEW})
    return out


def pending_reads():
    """What is waiting on a read, and which image answers it.

    A strip-stage attempt is answered by its one tile. A full-stage attempt was
    promoted out of gallery view and is answered by the original frames, where
    the active-speaker border is visible -- no new download either way.
    """
    state = load_state()
    rows = []
    for ph in sorted(state):
        a = open_attempt(state[ph])
        if not a:
            continue
        stage = a.get("stage", "strip")
        imgs = [a["tile"]] if stage == "strip" and a.get("tile") else a.get("frames") or []
        rows.append((ph, stage, state[ph].get("transcript_says"), imgs))
    vd = utils.get_video_data()
    for ph, stage, says, imgs in rows:
        a = open_attempt(state[ph])
        print("%s  [%s]%s" % (ph, stage,
                              "  transcript says: %s" % says if says else ""))
        for p in imgs:
            print("    %s" % p)
        # strips run top to bottom in the same order as the frames
        for i, leg in enumerate(frame_legend(vd, a, a.get("speaker") or ""), 1):
            print("    strip %d  t=%-6d %-12s %4.1fs %s %s"
                  % (i, leg["t"], leg["speaker"] or "-", leg["dur"],
                     ("<== TARGET (weak)" if leg["weak"] else "<== TARGET")
                     if leg["is_target"] else "                 ",
                     leg["text"]))
    print()
    print("%d attempts awaiting a read" % len(rows))
    return 0


def report():
    """Where the sweep stands, and the error rate against the transcript."""
    state = load_state()
    if not state:
        print("no sweep state yet (%s)" % STATE)
        return 0
    by = collections.Counter(r.get("status") or "new" for r in state.values())
    print("clusters in sweep: %d" % len(state))
    for k in ("named", "retry", "pending_read", "exhausted", "new"):
        if by.get(k):
            print("  %-13s %4d" % (k, by[k]))
    tries = collections.Counter(len(r.get("attempts") or []) for r in state.values())
    print()
    print("attempts per cluster: %s"
          % ", ".join("%d:%d" % (k, tries[k]) for k in sorted(tries)))
    # what the fallback bought: names that came from an attempt after the first
    late = sum(1 for r in state.values() if r.get("status") == "named"
               and any(a.get("verdict") == "name" and a.get("rank", 1) > 1
                       for a in r.get("attempts") or []))
    print("named on a fallback meeting (attempt >1): %d" % late)
    rooms = sum(1 for r in state.values()
                for a in r.get("attempts") or [] if a.get("verdict") == "room")
    print("attempts that named the room instead of a person: %d" % rooms)
    # the measurement: where the frame and the transcript both produced a name
    both = [r for r in state.values() if r.get("status") == "named"
            and r.get("transcript_says")]
    print()
    if both:
        how = collections.Counter(r.get("agreement") or "unknown" for r in both)
        wrong = how.get("disagree", 0)
        print("ground truth: %d clusters named by BOTH frame and transcript"
              % len(both))
        print("  exact surname    %d" % how.get("exact", 0))
        print("  spelling variant %d   (overlay correcting the ASR, not an error)"
              % how.get("variant", 0))
        print("  DISAGREE         %d   (%.1f%% error)"
              % (wrong, 100.0 * wrong / len(both)))
        for r in both:
            if r.get("agreement") in ("variant", "disagree"):
                print("    %-9s %-26s frame %-22s transcript %s"
                      % (r.get("agreement"), r["placeholder"], r.get("name"),
                         r.get("transcript_says")))
    else:
        print("ground truth: no cluster yet named by both frame and transcript")
        print("  (that overlap IS the error rate; it grows as the sweep runs)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="ranked candidates only")
    ap.add_argument("--cluster", help="one placeholder, e.g. abc12345678_SPEAKER_04")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--frames", type=int, default=3, help="frames per cluster")
    ap.add_argument("--sweep", action="store_true",
                    help="grab one attempt per due cluster, with fallback")
    ap.add_argument("--record", metavar="FILE",
                    help="read verdicts; '-' for stdin")
    ap.add_argument("--status", action="store_true", help="sweep progress")
    ap.add_argument("--pending", action="store_true",
                    help="images awaiting a read")
    args = ap.parse_args()

    if args.status:
        return report()
    if args.pending:
        return pending_reads()
    if args.record:
        if args.record == "-":
            return record(sys.stdin)
        with io.open(args.record, encoding="utf-8") as fp:
            return record(fp)

    vd = utils.get_video_data()
    rows = candidates(vd)
    if args.cluster:
        rows = [r for r in rows if r["placeholder"] == args.cluster]
        if not rows:
            print("no candidate matches %r (too little speech, pre-2020, or "
                  "not a YouTube id)" % args.cluster)
            return 1

    if args.sweep:
        return sweep(vd, rows, cluster_counts(vd), args.limit, args.frames)

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
