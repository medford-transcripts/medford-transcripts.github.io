import json, glob
import re
import os, time, datetime
import io as _io
import contextlib
import dateutil.parser as dparser
import yt_dlp 

import ipdb

# ward geometry
from geopy.geocoders import Nominatim
from shapely.geometry import shape, Point


# ---------------------------------------------------------------- atomic write
#
# WHY THIS EXISTS. Several generators opened their destination with "w" --
# which TRUNCATES IMMEDIATELY -- and then did minutes to hours of work before
# writing anything: make_index walks every transcript, make_resolution_tracker
# parses resolution PDFs with pypdf, make_all_election_pages builds 11 year
# pages with a word count over the whole corpus. Any exception in there left a
# live page at 0 bytes.
#
# That is not hypothetical. On 2026-09-17 election/index.html and
# election/2021.html were both committed empty when a run died partway through
# 2021, and election/index.html had already shipped empty once before, on
# 2025-11-26. The blank pages reached the public site both times.
#
# Buffer first, replace last: a failed run leaves the previous good page in
# place. Stale beats blank, and a half-written page never reaches the site.

def write_atomic(path, text, encoding="utf-8", newline=None):
    """Write text to path via a temp file and os.replace (atomic on Windows)."""
    tmp = path + ".tmp"
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(tmp, "w", encoding=encoding, newline=newline) as fp:
        fp.write(text)
    os.replace(tmp, path)


@contextlib.contextmanager
def atomic_write(path, encoding="utf-8", newline=None):
    """Collect writes in memory; commit to `path` only if the body completes.

    Drop-in for `with open(path, "w") as f:` -- the body still calls f.write().
    """
    buf = _io.StringIO()
    yield buf
    write_atomic(path, buf.getvalue(), encoding=encoding, newline=newline)


'''
return all the metadata for the videos stored in video_data.json
update the creation date.
'''
def get_video_data(jsonfile='video_data.json'):

    # read info
    if os.path.exists(jsonfile):
        while os.path.exists('video_data.lock'):
            time.sleep(1)
        with open(jsonfile, 'r') as fp:
            video_data = json.load(fp)
    else: video_data = {}

    return video_data

    #filtered_video_data = {
    #    k: v for k, v in video_data.items()
    #    if not v.get("skip", False)
    #}

'''
Save updates to the video metadata back to the json file
Do it in a thread-safe way to avoid corruption 
of the metadata from simultaneous processes
'''
def save_video_data(video_data, jsonfile='video_data.json'):

    # wait until the lock is gone
    while os.path.exists('video_data.lock'):
        time.sleep(1)

    # create new lock
    with open("video_data.lock", "w") as file:
        file.write("lock")

    # save the data
    with open(jsonfile, "w") as fp:
        json.dump(video_data, fp, indent=4)

    os.remove("video_data.lock")

''' 
Update video_data.json with info from yt_id
'''
def update_video_data_one(yt_id):
    video_data = get_video_data()

    if yt_id not in video_data.keys(): 
        video_data[yt_id] = {}

    required_keys = ["upload_date","channel","title","duration","view_count","date"]
    if not all(key in video_data[yt_id].keys() for key in required_keys):
        url = "https://youtu.be/" + yt_id
        with yt_dlp.YoutubeDL() as ydl:
            try:
                info = ydl.extract_info(url, download=False)

                video_data[yt_id]["title"] = info["title"]
                video_data[yt_id]["channel"] = info["channel"]
                video_data[yt_id]["duration"] = info["duration"]

                # links and a bunch of stuff are built around the upload date, and it sometimes changes (I think livestreams update when finished). Don't update it or things break!
                if "upload_date" not in video_data[yt_id].keys():
                    video_data[yt_id]["upload_date"] = datetime.datetime.fromtimestamp(info["timestamp"]).strftime("%Y-%m-%d")

                video_data[yt_id]["view_count"] = info["view_count"]
                #video_data[yt_id]["last_update"] = 0.0

                # the meeting date is derived below, outside this block
                save_video_data(video_data)
            except:
                print(yt_id + " not ready yet")

    # ---------------------------------------------------------------------
    # MEETING DATE: DERIVED, NOT CACHED.
    #
    # This lived inside the metadata block above, and "date" is one of the
    # required_keys guarding that block -- so the date was computed ONCE and
    # never revisited. That is why hand-editing video_data.json works, but it
    # froze the parser's mistakes exactly as firmly as a human's corrections,
    # with nothing to tell the two apart. dateutil's fuzzy mode read "Mustang
    # report 2 October 7, 2016" as 2007-10-02, and that stuck for years.
    #
    # It is now recomputed every run from title_date(), which knows the formats
    # these titles actually use, so improving the parser fixes history instead
    # of leaving 2,914 entries frozen. The expensive part -- the yt_dlp
    # metadata fetch -- stays gated; this is a regex over a string already in
    # memory.
    #
    # PRECEDENCE, and the order matters:
    #   1. date_manual: true -> never touched. Declared human judgement.
    #   2. a date in the title, not later than the upload date (that guard is
    #      inherited: a title claiming a later date is a typo).
    #   3. an existing stored date -- NOT the upload date. For the 673 videos
    #      whose titles carry no date the stored value may be a hand
    #      correction, and falling through to upload_date would silently
    #      revert it. An unparseable title keeps whatever is already there.
    #   4. upload_date, for entries that have nothing else.
    if not video_data[yt_id].get("date_manual"):
        derived = title_date(video_data[yt_id].get("title"),
                             not_after=video_data[yt_id].get("upload_date"))
        new_date = (derived
                    or video_data[yt_id].get("date")
                    or video_data[yt_id].get("upload_date"))
        if new_date and new_date != video_data[yt_id].get("date"):
            video_data[yt_id]["date"] = new_date
            save_video_data(video_data)

    if "agenda" not in video_data[yt_id].keys():
        agendas = glob.glob("agendas/*.pdf") 
        
def pick_date(entry):
    return (
        entry.get("date")
        or entry.get("upload_date")
        or "9999-99-99"
    )

def get_mp3filename(yt_id, video_data=None, local=False, external=False):
    audio_path_backup = "D:/medford-transcripts.github.io/audio/"
    audio_path = "audio/"

    if video_data is None:
        video_data = get_video_data()

    upload_date = video_data[yt_id]["upload_date"]


    base = upload_date + "_" + yt_id
    mp3_external = audio_path_backup + base + ".mp3"
    mp3_local = audio_path + base + ".mp3"

    if os.path.exists(mp3_external) or external: return mp3_external
    if os.path.exists(mp3_local) or local: return mp3_local
    return None 

def add_all_meeting_types(overwrite=False):
    video_data = get_video_data()

    update = False
    for yt_id in video_data.keys():

        meeting_type = get_meeting_type(video_data[yt_id])
        if "meeting_type" not in video_data[yt_id].keys():
            video_data[yt_id]["meeting_type"] = meeting_type            
            update = True

        if (meeting_type != video_data[yt_id]["meeting_type"] and overwrite) or (meeting_type != video_data[yt_id]["meeting_type"] and video_data[yt_id]["meeting_type"] is None):
            video_data[yt_id]["meeting_type"] = meeting_type            
            update = True            

    sorted_data = dict(
        sorted(
            video_data.items(),
            key=lambda item: (
                item[1].get("meeting_type") or "zzzz",
                pick_date(item[1]),
            )
        )
    )

    #nnone = 0
    #for yt_id in sorted_data.keys():
    #    if video_data[yt_id]["meeting_type"] is None: nnone += 1
    #    print(pick_date(video_data[yt_id]),  " | ", video_data[yt_id]["meeting_type"], " | ", video_data[yt_id]["channel"], " | ", video_data[yt_id]["title"])
    #
    #print(nnone)
    #print(len(video_data))

    if update:
        save_video_data(video_data)

# ------------------------------------------------------- meeting type config
#
# meeting_types.json maps a committee name to its title keywords. An entry is
# EITHER the legacy bare list:
#       "CC Board of Health": ["board of health"]
# or a dict carrying per-committee settings alongside them:
#       "CC City Council": {"keywords": [...], "link_on_front_page": true}
#
# Both shapes are accepted so adding a setting to one committee does not
# require rewriting the other sixty-three. Callers that only want keywords
# should use meeting_type_keywords() and stay indifferent to the shape.
#
# "sources" is not a committee -- it lists the pages the roster came from --
# and is excluded here. The old inline loops treated it as a keyword list, so
# a title containing one of those URLs could be typed as "sources"; no real
# title does, but the exclusion makes it impossible rather than unlikely.

MEETING_TYPES_FILE = "meeting_types.json"
_NOT_A_COMMITTEE = ("sources",)


def meeting_type_config(path=MEETING_TYPES_FILE):
    """{name: {"keywords": [...], ...}} -- both file shapes, normalised."""
    with open(path, "r", encoding="utf-8") as fp:
        raw = json.load(fp)
    out = {}
    for name, val in raw.items():
        if name in _NOT_A_COMMITTEE:
            continue
        if isinstance(val, dict):
            cfg = dict(val)
            cfg.setdefault("keywords", [])
        else:
            cfg = {"keywords": val}
        out[name] = cfg
    return out


def meeting_type_keywords(path=MEETING_TYPES_FILE):
    """{name: [keyword, ...]} -- what the title-matching callers want."""
    return {n: c["keywords"] for n, c in meeting_type_config(path).items()}


def front_page_committees(path=MEETING_TYPES_FILE):
    """Committee names flagged link_on_front_page, in file order."""
    return [n for n, c in meeting_type_config(path).items()
            if c.get("link_on_front_page")]


def committee_page(name):
    """Path of a committee's generated page (make_committee_pages:49)."""
    return "committees/" + name.replace(" ", "_") + ".html"


# --------------------------------------------------------------------- secrets
#
# Credentials live in credentials/, which is gitignored. They used to sit in
# the repo root next to the code, one filename per service, which made "is this
# safe to commit" a question you had to answer per file rather than once.
#
# credentials/ ONLY. The root fallback was removed deliberately: a secret that
# can live in two places will eventually live in the wrong one, and the repo
# root is the place where an absent-minded `git add -A` commits it.

CREDENTIAL_DIR = "credentials"


def credential_path(name):
    """Where a credential file actually is, or None."""
    p = os.path.join(CREDENTIAL_DIR, name)
    return p if os.path.exists(p) else None


def read_credential(name, required=True):
    """Contents of a credential file, stripped."""
    p = credential_path(name)
    if not p:
        if required:
            raise SystemExit(
                "Missing %s. Put it in %s/%s -- that directory is gitignored. "
                "See README.md for how to obtain it."
                % (name, CREDENTIAL_DIR, name))
        return None
    with open(p, "r", encoding="utf-8") as fp:
        return fp.read().strip()


def get_meeting_type_by_title(title):

    t = title.lower()
    meeting_type_map = meeting_type_keywords()

    # check against all keywords
    for meeting_type, keywords in meeting_type_map.items():
        if any(kw in t for kw in keywords):
            return meeting_type

def get_meeting_type(video):

    campaign_channels = ["Zac Bears","Dr. Lisa Kingsley","Justin Tseng for Medford","Matt Leming","Anna Callahan for Medford","Elect Aaron Olapade", "Invest in Medford", "ALL Medford"]
    news_channels = ["WCVB Channel 5 Boston","CBS Boston","NBC10 Boston"]

    if video["channel"].strip() in campaign_channels:
        return "Campaign"

    if video["channel"].strip() in news_channels:
        return "News"

    if video["channel"].strip() == "Medford Bytes":
        return "Medford Bytes"

    if video["channel"].strip() == "Medford Happenings":
        return "Medford Happenings"


    t = video["title"].lower()
    meeting_type_map = meeting_type_keywords()

    # some meetings can only be differentiated by channel and title
    if video["channel"].strip() == "Medford Public Schools":
        possible_meetings = ["MPS Meeting of the Whole","MPS Facilities","MPS Budget"]
        for possible_meeting in possible_meetings:
            keywords = meeting_type_map[possible_meeting]
            if any(kw in t for kw in keywords):
                return possible_meeting

    # now check the leftovers against all keywords
    for meeting_type, keywords in meeting_type_map.items():
        if any(kw in t for kw in keywords):
            return meeting_type

    return None

# ---------------------------------------------------------------------------
# TITLE STANDARDISATION -- the meeting date and a comparable "stem" of a title.
#
# Titles come from four sources with four conventions and plenty of typos:
#   "Medford City Council 09-26-17"        "Medford, MA City Council - Sep. 26, 2017"
#   "3.13.2024 MSC FY25 Budget Committee"  "Medford School Committee of the Whole 03-13-24"
# Duplicate detection keys on the MEETING date, which is in the title 81% of
# the time and is not the upload date (an unofficial channel often posts a day
# late). dateutil's fuzzy parser was reading "Episode 56" and room numbers as
# dates, so this is explicit about the formats that actually occur.
# ---------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_DATE_PATS = [
    ("ymd", re.compile(r"\b(20\d\d)[-./](\d{1,2})[-./](\d{1,2})\b")),
    ("mdY", re.compile(r"\b(\d{1,2})[-./](\d{1,2})[-./](20\d\d)\b")),
    ("mdy", re.compile(r"\b(\d{1,2})[-./](\d{1,2})[-./](\d\d)\b")),
    ("MdY", re.compile(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (20\d\d)\b")),
    ("dMY", re.compile(r"\b(\d{1,2}) ([A-Za-z]{3,9}),? (20\d\d)\b")),
    ("Mdy", re.compile(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? '?(\d\d)\b")),
    ("mmddyy", re.compile(r"\b(\d{2})(\d{2})(\d{2})\b")),
]


def title_date(title, not_after=None):
    """ISO meeting date found in a title, or None.

    not_after: the upload date. A title date LATER than the upload is a typo
    ("City Council 01-20-26" uploaded 2025-01-22), so it is ignored and the
    next candidate tried -- the same guard the original dateutil path had.
    """
    t = title or ""
    for kind, rx in _DATE_PATS:
        for m in rx.finditer(t):
            g = m.groups()
            try:
                if kind == "ymd":
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                elif kind == "mdY":
                    mo, d, y = int(g[0]), int(g[1]), int(g[2])
                elif kind in ("mdy", "mmddyy"):
                    mo, d, y = int(g[0]), int(g[1]), 2000 + int(g[2])
                elif kind in ("MdY", "Mdy"):
                    mo = _MONTHS.get(g[0].lower())
                    d, y = int(g[1]), int(g[2])
                    if y < 100:
                        y += 2000
                else:
                    d, mo, y = int(g[0]), _MONTHS.get(g[1].lower()), int(g[2])
                if mo is None:
                    continue
                iso = datetime.date(y, mo, d).isoformat()
            except (ValueError, TypeError):
                continue
            if not (2005 <= y <= 2035):
                continue
            if not_after and iso > not_after:
                continue
            return iso
    return None


def meeting_date(entry):
    """The date to dedup on: title date if it has one, else the stored date."""
    return (title_date(entry.get("title"), not_after=entry.get("upload_date"))
            or entry.get("date") or entry.get("upload_date"))


_NOISE = re.compile(
    r"\b(medford|meeting|regular|the|of|a|an|and|in|person|livestream|live|stream|"
    r"virtual|remote|via|zoom|recording|full|session|special|city|ma|mass|"
    r"unofficially|unofficial|posted|by|for|to|at|on)\b")


def title_stem(title):
    """Lowercased title with dates, punctuation and filler words removed."""
    t = (title or "").lower()
    for _, rx in _DATE_PATS:
        t = rx.sub(" ", t)
    t = re.sub(r"[^a-z0-9#]+", " ", t)
    t = _NOISE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def titles_overlap(a, b):
    """True if two titles share at least one meaningful word.

    The guard that keeps type+date from pairing different meetings. Measured
    on 76 candidate pairs: every true duplicate shared a word (Jaccard
    0.2-1.0); the two false pairs -- "#CottonSwabChallenge" vs a council
    meeting, "SEPAC" vs "Comprehensive Master Plan" -- shared none.

    NO LONGER THE WHOLE TEST -- see same_recording(), which calls this. On a
    corpus 30x larger than the one above, this predicate turned out to be
    almost pure noise: of 2,471 cross-channel candidate pairs it passed 2,395,
    and the words it passed on were "council", "committee", "school" -- the
    meeting_type's OWN name, which the grouping key had already asserted. So
    the pass side confirms nothing. Its only measurable effect was the 76
    rejections, and checking those against the transcripts showed they were
    true duplicates written as abbreviations: "msc" vs "school committee" (57
    pairs), "cpc", "councl", "mhcsbc". Hence _committee_abbreviation below.
    """
    return bool(set(title_stem(a).split()) & set(title_stem(b).split()))


# Types where (meeting_type, meeting_date) is NOT an identity for a recording,
# because the publisher issues several unrelated videos under one type on one
# day. These are still deduped -- they mirror across YouTube and Castus, which
# is how "Medford Happenings - Laura O'Neil" (Castus) went undetected against
# "Medford Happenings Episode 58 Laura O'Neill" (YouTube) -- but only on a
# positive signal, never on the key alone. See same_recording().
EPISODIC_TYPES = {"Campaign", "Medford Bytes", "Medford Happenings"}

# Types where two entries are NEVER the same recording, so there is nothing for
# dedup to find and every match would be a false one. Local news is several
# outlets shooting their OWN footage of one event: their titles overlap on the
# story ("superintendent", "high school stabbing") while the video differs, and
# both of the corpus's cross-channel News pairs match on exactly those words.
# None means no key at all -- guessing from a date is how a reader ends up
# reading the wrong meeting.
NEVER_DEDUP_TYPES = {None, "News"}


# Words that name a PROGRAMME rather than an episode. Two different instalments
# of a series share these, so they are evidence of nothing. "candidate" and
# "profile" are here because a campaign season produces many "2025 Candidate
# Profile - ..." videos from different committees on the same day.
_PROGRAMME_WORDS = {"episode", "ep", "pt", "part", "show", "promo",
                    "candidate", "profile"}


def distinctive_title_tokens(title, meeting_type):
    """Title words that could tell two videos of the same type/date apart.

    Drops the meeting_type's own words (which every title of that type
    repeats), programme words, bare numbers and single letters. For
    "Medford Happenings Episode 58 Laura O'Neill" this leaves {laura, neill};
    for the Castus mirror "Medford Happenings - Laura O'Neil", {laura, neil}.
    """
    drop = set(re.findall(r"[a-z0-9]+", (meeting_type or "").lower()))
    drop |= _PROGRAMME_WORDS
    return set(t for t in title_stem(title).split()
               if t not in drop and len(t) > 1 and not t.isdigit())


def _close(a, b):
    """One-character typo tolerance, for titles like "Councl"."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) < 5 or len(b) < 5:
        return a == b
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    for c in long:                       # one deletion
        if i < len(short) and short[i] == c:
            i += 1
    return i >= len(short)


def _committee_abbreviation(title, meeting_type):
    """True if the title says nothing except the committee's own name.

    "MSC", "CPC", "Councl", "School Committee" for an MPS School Committee
    meeting all carry zero information beyond the meeting_type, so they cannot
    be evidence that two recordings differ -- and demanding a shared word from
    them is what lost 60 of the 76 true duplicates above. A title that names a
    SUBJECT ("Salem Street CBD Continued Public Hearing") is not this, and
    still has to overlap.
    """
    words = [w for w in re.findall(r"[a-z]+", (meeting_type or "").lower()) if w]
    if not words:
        return False
    initials = "".join(w[0] for w in words)
    for t in distinctive_title_tokens(title, meeting_type):
        if any(_close(t, w) for w in words):
            continue
        # an acronym: each letter is the initial of a later type word
        i = 0
        for c in t:
            j = initials.find(c, i)
            if j < 0:
                break
            i = j + 1
        else:
            continue
        return False                     # this token names something else
    return True


def same_duration(a, b, tol=3, floor=300):
    """Same encode, to the second.

    MCM retitles on Castus -- "Medford Happenings w/ John Petrella" is
    published there as "Local Happenings Part 2" -- so titles cannot match
    those, but the durations are 709s and 709s. The floor matters: a 30-second
    campaign clip can coincide with another by chance, a 20-minute programme
    cannot. Deliberately NOT used for full meetings, where a true duplicate can
    legitimately differ 6x (a partial recording of the same council meeting
    measured 0.166 of its twin's length at 0.886 text containment).
    """
    da, db = a.get("duration"), b.get("duration")
    if not da or not db or max(da, db) < floor:
        return False
    return abs(da - db) <= tol


def same_recording(a, b):
    """Do two entries sharing meeting_type, meeting date and nothing else
    (different channels) record the same thing?

    The grouping key does nearly all the work for a MEETING: a committee meets
    once on a given evening, so a second copy of that type and date from
    another channel is that meeting. Checked against transcripts for the 33
    cross-channel pairs where both copies happen to have been transcribed, all
    33 were true duplicates (5-gram containment 0.74-1.00) -- the key produced
    no false positives at all.

    It does NOT hold for episodic content, where a programme airs a different
    guest each week, so those need a positive signal: a distinctive shared word
    or an identical duration.
    """
    mt = a.get("meeting_type")
    if mt in EPISODIC_TYPES:
        if distinctive_title_tokens(a.get("title"), mt) & \
           distinctive_title_tokens(b.get("title"), mt):
            return True
        return same_duration(a, b)
    if titles_overlap(a.get("title"), b.get("title")):
        return True
    # An abbreviation of the committee's own name is not a disagreement.
    return (_committee_abbreviation(a.get("title"), mt)
            or _committee_abbreviation(b.get("title"), mt))


def has_transcript(yt_id, entry):
    d = (entry.get("upload_date") or "") + "_" + yt_id
    return os.path.exists(os.path.join(d, d + ".srt"))


# Source preference when NEITHER copy is transcribed yet: official channels,
# then the MCM archive, then unofficial re-uploads.
# Preference when the same meeting exists in several places. Official city
# channels first, then MCM's own venues, then unofficial mirrors.
#
# MCM Castus is MCM's PRIMARY site and archive.org is periodic bulk dumps from
# it -- so Castus is more current and more complete. It still ranks BELOW MCM
# Archive here, because the question this list answers is "which copy should
# the archive point at", and archive.org is a preservation institution with
# stable URLs while Castus is an undocumented vendor API behind CloudFront.
# Prefer the durable copy where one exists; use Castus for what it does not
# have, which is most of the boards and commissions.
#
# "Medford Happenings" and "Medford Bytes" are MCM's own programme channels on
# YouTube, and Castus carries the same episodes -- usually RETITLED, so the
# YouTube copy is the one whose title names the guest. They sit above Castus
# because they are where the programme is published first, and below MCM
# Archive for the same durability reason as everything else.
# (Note the channel string in video_data is "Medford Bytes " with a trailing
# space; every caller compares .strip(), so the list holds the clean name.)
BEST_CHANNELS = ["City of Medford, Massachusetts", "Medford Public Schools",
                 "Medford Community Media", "MCM Archive",
                 "Medford Happenings", "Medford Bytes", "MCM Castus",
                 "Mass Traction-US-Medford-1 - Government",
                 "Select Medford, MA City Meetings"]
MT_CHANNEL = "Mass Traction-US-Medford-1 - Government"


def _rank(channel):
    try:
        return BEST_CHANNELS.index(channel)
    except ValueError:
        return 10


def _dedup_protected(entry):
    """Entries whose skip state is not ours to change."""
    if entry.get("manual_correction"):
        return True
    # a skip WITHOUT duplicate_id was set by a person or by the truncated-audio
    # guard, never by this function
    return bool(entry.get("skip")) and not entry.get("duplicate_id")


def _hidden_for_good(entry):
    """Hidden, by a skip this function is not allowed to lift.

    Not the same as _dedup_protected: an entry carrying manual_correction but
    NOT skipped is visible, and makes a perfectly good keeper. What disqualifies
    a keeper is being hidden with no way for this run to un-hide it.
    """
    return bool(entry.get("skip")) and _dedup_protected(entry)


# ---------------------------------------------------------------------------
# MEETING DOCUMENTS -- agendas and minutes matched to the meeting they belong to.
#
# The scraped filenames carry the same two facts the videos do, in the same
# vocabulary: a date and a committee name.
#     2024.01.17 - Committee of the Whole Agenda with Attachments.pdf
#     2024.01.17 - Committee of the Whole Report, January 17, 2024.pdf
# So the SAME classifier that types a video title types a document filename --
# measured: all 486 agenda files classify, and 458 match exactly one meeting on
# (date, meeting_type), 2 are ambiguous.
#
# The previous matcher keyed on date alone and then fuzzy-matched the title, and
# was only ever called for CC City Council, so 312 meetings had an agenda on
# disk and showed no link. Date alone is also not enough on its own: a council
# meeting and a school committee meeting on the same evening would each match
# the other's agenda.
# ---------------------------------------------------------------------------
_DOC_INDEX = {}


def _document_index(kind):
    """{(date, meeting_type): [paths]} for 'agendas' or 'minutes', cached."""
    if kind in _DOC_INDEX:
        return _DOC_INDEX[kind]
    index = {}
    for path in sorted(glob.glob(os.path.join(kind, "*"))):
        name = os.path.splitext(os.path.basename(path))[0]
        date = title_date(name)
        if not date:
            continue
        index.setdefault((date, get_meeting_type_by_title(name)), []).append(path)
    _DOC_INDEX[kind] = index
    return index


def meeting_documents(entry, kind="agendas"):
    """Paths of the agendas (or minutes) for this meeting, best first.

    Requires BOTH the date and the meeting type to agree, so a document is
    never attached to a different committee that met the same day. Returns []
    when the meeting has no type -- guessing from the date alone is how a
    reader ends up reading the wrong agenda.
    """
    mt = entry.get("meeting_type")
    if not mt:
        return []
    hits = list(_document_index(kind).get((meeting_date(entry), mt), []))
    if len(hits) > 1:
        # prefer the fuller document when a committee posts several
        hits.sort(key=lambda p: (0 if "with attachment" in p.lower() else 1, p))
    return hits


def identify_duplicate_videos(video_data=None, reset=False, apply=True):
    """Mark duplicate recordings of the same meeting so only one is transcribed.

    Same meeting_type + same MEETING date (from the title) + a different
    channel => duplicates, if same_recording() agrees. The one exception to
    "different channel": Mass Traction posts a Livestream and a recording of
    the same meeting.

    THE TEST IS NOT THE SAME FOR EVERY TYPE, and the reason is worth keeping.
    Four types used to be excluded outright, on the theory that nothing would
    duplicate them so any hit was a false positive. Castus broke that: MCM
    publishes "Medford Happenings" to YouTube AND to Castus, so
    "Medford Happenings Episode 58 Laura O'Neill" and the Castus mirror
    "Medford Happenings - Laura O'Neil" sat side by side, undetected, and the
    mirror was transcribed a second time. They are deduped now, but on a
    positive signal only -- see EPISODIC_TYPES and NEVER_DEDUP_TYPES.

    WHICH COPY IS KEPT, in order:
      1. the one that ALREADY HAS A TRANSCRIPT. The previous version applied
         channel priority alone, and had hidden 66 finished transcripts --
         Mass Traction copies transcribed before their MCM twins were ingested,
         then skipped in favour of the archive copy, which was queued to be
         transcribed AGAIN: 161 hours of audio, about 19 days of compute, to
         reproduce work already done.
      2. channel priority (BEST_CHANNELS)
      3. the non-Livestream copy

    A keeper that a previous run had skipped is un-skipped. Entries with
    manual_correction, or a skip this function did not set, are never touched.

    apply=False computes and returns the changes without mutating or saving.
    """
    own = video_data is None
    if own:
        video_data = get_video_data()

    if reset:
        for yt_id, e in video_data.items():
            if e.get("manual_correction"):
                continue
            e.pop("skip", None)
            e.pop("duplicate_id", None)

    # STALE SKIPS FROM A RULE THAT NO LONGER APPLIES. A type that leaves the
    # dedup set takes its old verdicts with it: this function stops grouping
    # those entries, so it can also never un-skip them, and a wrong hide made
    # under the previous rule would last forever with nothing to lift it.
    # That is not hypothetical -- five News videos were hidden this way, in
    # two mutual A->B->A pairs, so EVERY copy of the high-school stabbing
    # story and the superintendent's retirement was invisible. They were never
    # duplicates: local outlets shoot their own footage and merely share the
    # subject ("superintendent", "high school"), which is why News is in
    # NEVER_DEDUP_TYPES now.
    #
    # NOT untyped entries, though they are also in NEVER_DEDUP_TYPES. None has
    # been excluded by every version of this function, so a dedup skip on an
    # untyped entry was recorded while it still HAD a type -- it is a verdict
    # this function can no longer re-check, not one it has reversed. Several
    # are plainly right ("... (Unofficial)", "... (corrected version)"), and
    # lifting them would put genuine duplicates back on the site.
    stale = {}
    for yt_id, e in video_data.items():
        mt = e.get("meeting_type")
        if mt is None or mt not in NEVER_DEDUP_TYPES:
            continue
        if e.get("skip") and e.get("duplicate_id") and not _dedup_protected(e):
            stale[yt_id] = {"skip": False, "duplicate_id": e["duplicate_id"],
                            "skip_reason": "un-skipped: %s is no longer deduped"
                                           % (e.get("meeting_type") or "an untyped video")}

    groups = {}
    for yt_id, e in video_data.items():
        if e.get("meeting_type") in NEVER_DEDUP_TYPES or not e.get("title") or not e.get("channel"):
            continue
        groups.setdefault((e["meeting_type"], meeting_date(e)), []).append(yt_id)

    def prefer(yt_id):
        # SOURCE PRIORITY DECIDES THE KEEPER, not transcription state. An
        # earlier version let an already-transcribed copy win; the owner
        # reversed that: Mass Traction is retiring and official/archive
        # sources are preferred even when the unofficial copy is done.
        e = video_data[yt_id]
        return (_rank(e["channel"].strip()),
                1 if "Livestream" in (e.get("title") or "") else 0,
                yt_id)

    changes = dict(stale)  # yt_id -> {"skip": bool, "duplicate_id": str}
    pairs = 0
    for key, ids in groups.items():
        if len(ids) < 2:
            continue
        # NEVER HIDE A MEETING BEHIND A COPY THAT IS ITSELF HIDDEN. A keeper
        # skipped WITHOUT a duplicate_id was hidden by a person or by the
        # truncated-audio guard, and _dedup_protected refuses to un-skip it --
        # so pointing the other copies at it removes the meeting from the site
        # altogether. Found live: the MCM Archive copies of "Community
        # Development Board 07-14-25" and the 2021 cannabis outreach session
        # were already skipped, and the Castus copies had just been pointed at
        # them, leaving no visible copy of either. Prefer an unskippable-away
        # keeper; if every copy in the group is protected-skipped, leave the
        # whole group alone rather than pick a dead keeper.
        usable = [y for y in ids if not _hidden_for_good(video_data[y])]
        if not usable:
            continue
        keeper = min(usable, key=prefer)
        k = video_data[keeper]
        for other in ids:
            if other == keeper:
                continue
            o = video_data[other]
            same_channel = o["channel"].strip() == k["channel"].strip()
            live = ("Livestream" in (o.get("title") or "")) or ("Livestream" in (k.get("title") or ""))
            if same_channel and not (o["channel"].strip() == MT_CHANNEL and live):
                continue
            if not same_recording(o, k):
                continue
            pairs += 1
            keeper_done = has_transcript(keeper, k)
            other_done = has_transcript(other, o)
            if not _dedup_protected(o):
                # WHY, not just WHAT. A bare skip:true is indistinguishable
                # from an intentional dedup, a truncated download, or a human
                # decision -- the same "nobody wrote it down" problem as the
                # correction ledger and the speaker provenance sidecar.
                # Never hide the ONLY transcript. If the preferred copy is not
                # transcribed yet but this one is, both stay visible until the
                # keeper is done; the next run then skips this one.
                changes[other] = {"skip": bool(keeper_done or not other_done),
                                  "duplicate_id": keeper,
                                  "duplicate_method": "metadata",
                                  "skip_reason": "duplicate of %s (same type and "
                                                 "meeting date, different channel)" % keeper}
            if not _dedup_protected(k):
                c = changes.setdefault(keeper, {"skip": False, "duplicate_id": other})
                # An untranscribed keeper whose twin is already done goes to the
                # BACK of the queue: it must still be transcribed from the
                # preferred source, but behind meetings with no transcript at all.
                c["backseat"] = bool(other_done and not keeper_done)

    summary = {"pairs": pairs,
               "skipped": sum(1 for y, c in changes.items() if c["skip"] and not video_data[y].get("skip")),
               "unskipped": sum(1 for y, c in changes.items() if not c["skip"] and video_data[y].get("skip"))}
    if not apply:
        summary["changes"] = changes
        return summary

    def _apply(target):
        for yt_id, c in changes.items():
            if yt_id in target:
                target[yt_id]["skip"] = c["skip"]
                target[yt_id]["duplicate_id"] = c["duplicate_id"]
                if c["skip"]:
                    target[yt_id]["duplicate_method"] = c.get("duplicate_method", "metadata")
                    if c.get("skip_reason"):
                        target[yt_id]["skip_reason"] = c["skip_reason"]
                else:
                    # un-skipped: the reason no longer applies
                    if target[yt_id].get("duplicate_method") == "metadata":
                        target[yt_id].pop("skip_reason", None)
                if "backseat" in c:
                    if c["backseat"]:
                        target[yt_id]["backseat"] = True
                    else:
                        target[yt_id].pop("backseat", None)
    _apply(video_data)
    if own:
        fresh = get_video_data()         # reload right before saving
        _apply(fresh)
        save_video_data(fresh)
    else:
        save_video_data(video_data)
    print("duplicates: %d pairs, %d newly skipped, %d un-skipped"
          % (summary["pairs"], summary["skipped"], summary["unskipped"]))
    return summary


def update_priority(newest=False, oldest=False, popularity=False, exp_decay=False, 
    linear_decay=True, shortest=False, longest=False):

    video_data = get_video_data()

    now = datetime.datetime.now()
    priority = []
    halflife = 90.0
    for yt_id in video_data.keys():
        if "view_count" in video_data[yt_id].keys(): 
            views = video_data[yt_id]["view_count"]
        else: views = 0

        date = datetime.datetime.strptime(video_data[yt_id]["date"],'%Y-%m-%d')
        age = (now - date).total_seconds()/86400.0

        if "duration" in video_data[yt_id].keys():
            duration = video_data[yt_id]["duration"]
        else: duration = 7200.0 # default to 2 hours

        # ad hoc prioritization scheme based on popularity, age, and/or duration
        if newest:
            # prioritize by age (newest first)
            priority.append(1.0/age)
        elif oldest:
            # prioritize by age (oldest first)
            priority.append(age)
        elif popularity:
            # prioritize by popularity
            priority.append(views)
        elif exp_decay:
            # exponential decay penalizes old videos too strongly or doesn't weight new ones strongly enough
            priority.append(views*math.exp(-math.log(2.0)*age/halflife))
        elif linear_decay:
            # linear decay weakly penalizes old videos
            priority.append((views+100)*100/age)
        elif shortest:
            # prioritize shortest videos first
            priority.append(1.0/duration)
        elif longest:
            # prioritize longest videos first
            priority.append(duration)           

    # sort video_data by priority (equivalent to np.argsort)
    sort_ndx = reversed(sorted(range(len(priority)), key=priority.__getitem__))
    yt_ids = list(video_data.keys())
    sorted_dict = {}
    for k in sort_ndx:
        sorted_dict[yt_ids[k]] = video_data[yt_ids[k]]
        sorted_dict[yt_ids[k]]["priority"] = priority[k]
        # a preferred-source copy whose unofficial twin is already transcribed
        # waits behind meetings that have no transcript at all
        if sorted_dict[yt_ids[k]].get("backseat"):
            sorted_dict[yt_ids[k]]["priority"] = priority[k] * 0.01

    save_video_data(sorted_dict)

'''
update the video_data for an entire channel
'''
def update_channel(channel):

    video_data = get_video_data()
    url = "https://www.youtube.com/" + channel 
    info = yt_dlp.YoutubeDL({'extract_flat':'in_playlist'}).extract_info(url, download=False) 

    # all we're trying to do is loop through a list of all YouTube IDs in this channel
    # there must be a better way, but the structure of info is a mystery to me
    # beware: info changes between channels with only one video type vs multiple video types

    for playlist in info["entries"]:
        if "entries" in playlist.keys():
            for entry in playlist["entries"]:
                if entry["id"] not in video_data.keys():
                    try:
                        update_video_data_one(entry["id"])
                    except Exception as error:
                        print("Failed on " + entry["id"])
                        print(error)
                        print(traceback.format_exc())
        else:
            # this captures channels with only one video type (?)
            # I think "playlist" is actually a video
            try:
                update_video_data_one(playlist["id"])
            except Exception as error:
                print("Failed on " + playlist["id"])
                print(error)
                print(traceback.format_exc())

# Function to get latitude and longitude
def get_lat_lon(address):
    geolocator = Nominatim(user_agent="medfordTranscripts/1.0")
    try:
        location = geolocator.geocode(address, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"Error geocoding {address}: {e}")
    return None

def address_to_ward(address, return_district=False):

    with open("medford_wards.geojson", "r") as f:
        wards = json.load(f)

    ward_geoms = []
    # Add text labels for each wards
    for feature in wards["features"]:
        geom = shape(feature["geometry"])
        ward = str(feature["properties"].get("WARD", "")).strip()
        precinct = str(feature["properties"].get("PRECINCT", "")).strip()
        label = f"{ward}-{precinct}"

        # these define the school committee districts
        if ward == "1" or ward == "7": district = "1/7" # East?
        if ward == "2" or ward == "3": district = "2/3" # North?
        if ward == "4" or ward == "5": district = "4/5" # South?
        if ward == "6" or ward == "8": district = "6/8" # West?

        ward_geoms.append(
            {
                "geom": geom,
                "ward": ward,
                "precinct": precinct,
                "ward_precinct": label,
                "district": district,
            }
        )

    lat_lon = get_lat_lon(address)
    if lat_lon is None: return None
    lat = lat_lon[0]
    lon = lat_lon[1]

    for w in ward_geoms:
        if w["geom"].contains(Point(lon, lat)):
            if return_district: return w["district"]
            return w["ward"]

    return None

''' 
update the meta data for all videos
'''
def update_all(channel_file="channels_to_transcribe.txt", id_file="ids_to_transcribe.txt"):

    # update video data for videos already transcribed
    transcribed_files = glob.glob("*/20??-??-??_???????????.srt")
    for file in transcribed_files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        update_video_data_one(yt_id)

    # update video data for files in id_file
    if os.path.exists(id_file):
        with open(id_file) as f:
            yt_ids = f.read().splitlines()
        for yt_id in yt_ids:
            update_video_data_one(yt_id)

    # update video data for all channels
    if os.path.exists(channel_file):
        with open(channel_file) as f:
            channels = f.read().splitlines()
            # loop through every video on these channels
            for channel in channels: 
                if channel[0] == '@':
                    update_channel(channel)

    # update every entry in video_data.json
    video_data = get_video_data()
    for yt_id in video_data.keys():
        update_video_data_one(yt_id)

    identify_duplicate_videos()
    update_priority(newest=True)

'''
make a unique set of the councilors from councilors.json
'''
def get_councilors(jsonfile="councilors.json",mayor=False, city_council=False, school_committee=False, candidates=False, year=None, superintendents=False):
    with open(jsonfile, 'r') as fp:
        councilors = json.load(fp)
    return(list(set(councilors.keys())))

'''
make a unique set of the councilors in councilors.txt
'''
def get_councilors_old(file="councilors.txt",mayor=False, city_council=False, school_committee=False, candidates=False, year=None, superintendents=False):
    councilors = []
    with open(file,'r') as fp:
        for line in fp:
            entries = line.split("#")[0].strip().split(',')
            for entry in entries:
                if entry != '':
                    councilors.append(entry.strip())
    return list(set(councilors))