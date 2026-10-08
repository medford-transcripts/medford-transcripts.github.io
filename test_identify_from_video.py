"""Does the fallback actually advance, and does the rule outrank the read?"""
import io, json, os, sys, tempfile
sys.path.insert(0, r"C:\Users\jdeas\Documents\GitHub\medford-transcripts.github.io")
os.chdir(r"C:\Users\jdeas\Documents\GitHub\medford-transcripts.github.io")
import identify_from_video as ifv

fails = []
def ck(name, got, want):
    if got != want:
        fails.append("%s: got %r want %r" % (name, got, want))
        print("FAIL %s: got %r want %r" % (name, got, want))
    else:
        print("ok   %s" % name)

# --- isolate the state file -------------------------------------------------
tmp = tempfile.mkdtemp()
ifv.STATE = os.path.join(tmp, "sweep.json")

PH = "abcdefghijk_SPEAKER_04"
VD = {
    "abcdefghijk": {"date": "2022-06-14", "meeting_type": "CC City Council",
                    "title": "Regular Meeting", "upload_date": "2022-06-14"},
    "bbbbbbbbbbb": {"date": "2022-03-01", "meeting_type": "CC Subcommittee",
                    "title": "Resident Services Subcommittee",
                    "upload_date": "2022-03-01"},
    "ccccccccccc": {"date": "2023-01-10", "meeting_type": "CC City Council",
                    "title": "Regular Meeting", "upload_date": "2023-01-10"},
    "ddddddddddd": {"date": "2019-04-01", "meeting_type": "CC City Council",
                    "title": "Pre-Zoom", "upload_date": "2019-04-01"},
    "MCM00001234": {"date": "2022-09-09", "title": "MCM copy",
                    "upload_date": "2022-09-09"},
}
REFS = [("bbbbbbbbbbb", "SPEAKER_02"), ("ccccccccccc", "SPEAKER_07"),
        ("ddddddddddd", "SPEAKER_01"), ("MCM00001234", "SPEAKER_00")]

# ranking: pre-2020 and MCM are dropped; subcommittee comes first
ranked = ifv.meetings_for(VD, PH, REFS)
ck("ranking drops unreadable meetings", len(ranked), 3)
ck("subcommittee ranked first", ranked[0][0], "bbbbbbbbbbb")

# --- the advance ------------------------------------------------------------
rec = {"placeholder": PH, "status": "new", "attempts": []}
yt, spk = ifv.next_meeting(VD, PH, REFS, rec)
ck("first pick is the subcommittee", yt, "bbbbbbbbbbb")

rec["attempts"].append({"yt": yt, "speaker": spk, "rank": 1, "verdict": "room"})
yt2, _ = ifv.next_meeting(VD, PH, REFS, rec)
ck("a room label advances to meeting 2", yt2 != yt and yt2 in ranked[1], True)

spk2 = dict(ranked)[yt2]
rec["attempts"].append({"yt": yt2, "speaker": spk2, "rank": 2,
                        "verdict": "blank"})
yt3, spk3 = ifv.next_meeting(VD, PH, REFS, rec)
ck("advances again", yt3 not in (yt, yt2), True)

rec["attempts"].append({"yt": yt3, "speaker": spk3, "rank": 3,
                        "verdict": "room"})
yt4, _ = ifv.next_meeting(VD, PH, REFS, rec)
ck("exhausted when every readable meeting is tried", yt4, None)

# a room label is a property of the FEED, so it bars the whole meeting even
# when the cluster has a second local label in it
SPLIT = REFS + [("bbbbbbbbbbb", "SPEAKER_09")]
r_room = {"attempts": [{"yt": "bbbbbbbbbbb", "speaker": "SPEAKER_02",
                        "verdict": "room"}]}
ck("room bars the whole meeting",
   ifv.next_meeting(VD, PH, SPLIT, r_room)[0] != "bbbbbbbbbbb", True)
r_blank = {"attempts": [{"yt": "bbbbbbbbbbb", "speaker": "SPEAKER_02",
                         "verdict": "blank"}]}
ck("a blank leaves the meeting's other label available",
   ifv.next_meeting(VD, PH, SPLIT, r_blank), ("bbbbbbbbbbb", "SPEAKER_09"))

# a download failure must ALSO advance, not stall
rec2 = {"placeholder": PH, "status": "retry",
        "attempts": [{"yt": "bbbbbbbbbbb", "speaker": "SPEAKER_02",
                      "rank": 1, "verdict": "download_failed"}]}
ck("download failure advances too",
   ifv.next_meeting(VD, PH, REFS, rec2)[0] != "bbbbbbbbbbb", True)

# --- record(): the rule outranks the read ----------------------------------
def fresh(says=None):
    ifv.save_state({PH: {"placeholder": PH, "status": "pending_read",
                         "transcript_says": says, "meetings": 4,
                         "attempts": [{"yt": "bbbbbbbbbbb",
                                       "speaker": "SPEAKER_02", "rank": 1,
                                       "verdict": None, "name": None}]}})

fresh()
ifv.record(["%s  Laura Swan" % PH])
st = ifv.load_state()
ck("a name ends the cluster", st[PH]["status"], "named")
ck("name stored", st[PH]["name"], "Laura Swan")

fresh()
ifv.record(["%s  room" % PH])
st = ifv.load_state()
ck("room -> retry", st[PH]["status"], "retry")
ck("room verdict recorded", st[PH]["attempts"][0]["verdict"], "room")

fresh()
ifv.record(["%s  Council Chambers" % PH])
st = ifv.load_state()
ck("a room label typed as a name is REJECTED", st[PH]["attempts"][0]["verdict"],
   "rejected")
ck("rejection falls back rather than naming", st[PH]["status"], "retry")

fresh()
ifv.record(["%s  Erik" % PH])          # single word: full names only
st = ifv.load_state()
ck("single-word read rejected", st[PH]["attempts"][0]["verdict"], "rejected")

# agreement with the transcript, which is the error measurement
fresh(says="Sam Riley")
ifv.record(["%s  Sam Riley" % PH])
ck("agreement detected", ifv.load_state()[PH].get("agrees"), True)

fresh(says="Lessenhaupt Hurtubise")
ifv.record(["%s  Dan Fairchild" % PH])
ck("disagreement detected", ifv.load_state()[PH].get("agrees"), False)

# unparsed input must not silently vanish
fresh()
ck("bare placeholder is an error", ifv.record([PH]), 1)
ck("unknown placeholder is an error", ifv.record(["zzz_SPEAKER_00  Bob Smith"]), 1)

# recording twice must not double-apply
fresh()
ifv.record(["%s  Laura Swan" % PH])
ck("second record finds no open attempt", ifv.record(["%s  Other Name" % PH]), 1)
ck("name not overwritten", ifv.load_state()[PH]["name"], "Laura Swan")

# --- strip_tile -------------------------------------------------------------
from PIL import Image
pngs = []
for i, c in enumerate([(20, 30, 40), (60, 70, 80), (10, 10, 10)]):
    p = os.path.join(tmp, "f_%02d.png" % i)
    Image.new("RGB", (1280, 720), c).save(p)
    pngs.append(p)
out = ifv.strip_tile(pngs, os.path.join(tmp, "tile.png"))
w, h = Image.open(out).size
band = int(720 * (1.0 - ifv.STRIP_FRACTION))
ck("tile width is the frame width", w, 1280)
ck("tile stacks 3 bands plus seams", h, 3 * (720 - band) + 6)
ck("tile with no readable frames returns None",
   ifv.strip_tile([os.path.join(tmp, "nope.png")], os.path.join(tmp, "t2.png")),
   None)

print()
print("%d failures" % len(fails))
sys.exit(1 if fails else 0)
