# Resume here

Written 2026-10-08, shelved for the week. Picks up where the session stopped.
Read PRINCIPLES.md first; PENDING.md holds the older backlog.

## Where the video sweep stands

`identify_from_video.py` reads the name Zoom draws on a frame while a cluster
is speaking. It is a resumable queue; nothing about it needs re-deriving.

    python identify_from_video.py --status            # progress + error rate
    python identify_from_video.py --sweep --limit 10  # grab, with fallback
    python identify_from_video.py --pending --limit 3 # what to read next
    python identify_from_video.py --record -          # verdicts on stdin
    python identify_from_video.py --dry-run / --apply # write at cluster HOME
    python identify_from_video.py --reground          # re-derive ground truth
    python identify_from_video.py --retile            # rebuild tiles, free

**Done.** 278 candidates, every one attempted at least once (some six times).
88 named, applied and propagated: **312 speaker labels across 226 meetings**.
89 clusters exhausted every readable meeting. The read queue is empty.

**Measured.** 45 of the 88 are also named by the transcript in their own
words: 21 exact surnames, 17 spelling variants where the overlay CORRECTED the
ASR, 2 disagreements (4.4%) -- and both of those are the transcript being
wrong, not the frame ("Will Mbah" heard as "William Barr"; "Stefan Chaires" as
"Stephan Churis"). The comparison bounds BOTH sources, not the frame alone.

### The one thing to do next

**101 clusters sit in `retry`.** They have had a meeting fail and are waiting
for a grab from their next-best one. That is where the remaining names are:

    for i in $(seq 1 10); do python identify_from_video.py --sweep --limit 10 --frames 2; done
    python identify_from_video.py --pending --limit 3   # then read, then --record -

Grabs are downloads (~45 s each) and the box has been memory-tight; run them
in bounded batches like the loop above, not one long process. Three long
processes were killed for memory during this session.

When new names land: `--dry-run`, then `--apply` (idempotent -- re-running
only adds), then regenerate the affected meetings with `srt2html.py -i <id> -f`.

### 96 pages still need regenerating -- do this first

The names are in `speaker_ids.json` and propagated, but **96 meetings have
stale HTML**, so those names are not on the site yet. The regeneration run was
killed for memory partway (380 of 476 meetings are current). The exact list is
in `regen_remaining.txt`:

    while read -r id; do python srt2html.py -i "$id" -f; done < regen_remaining.txt

Regenerate when the box is quiet -- `srt2html -f` redoes the nine-language
translation per page and is what keeps getting OOM-killed. Recompute the list
any time: a meeting is stale when its `.html` is older than its
`speaker_ids.json`.

**What "quiet" means here.** The transcription process was holding **5.97 GB**
on the evening of 2026-10-08, which is what killed three long runs (this
regeneration, the footer backfill, and a sweep batch). Check with
`Get-Process python | select Id,WorkingSet64` before starting a long pass, and
prefer a loop of short bounded processes over one long one regardless.

### Do not re-litigate these; they were each paid for

- **Name the cluster HOME, never the local label.** A placeholder IS the
  cluster identity; naming locally destroys the reference.
- **`--apply` groups writes per FILE.** Three clusters can share one home
  meeting; per-cluster load-modify-write silently lost 11 of the first 50
  names, and the run reported success. Verify counts, do not trust the log.
- **`MIN_TURN_FOR_VIEW = 5.0`.** A 3.9 s turn named the previous speaker.
- **A room feed can be logged in under a PERSON'S name** (`YeIUKo9SmWU` reads
  "Kevin Harrington" while the desk nameplate says "Melanie McLaughlin"). No
  guard can reject it. The tell: the label never changes while the camera and
  speaker do.
- **Never read a slide, a chyron, a podium sign or a desk nameplate as a
  speaker.** Only the chrome Zoom draws tracks who is talking. Filed in
  PENDING.md as unmeasured signals, not spent.
- **Never harvest a gallery frame's roster** -- that is an attendance record of
  people who never spoke (PRINCIPLES.md #2).
- `plausible_name()` is the single gate for BOTH frame reads and transcript
  ground truth. Four non-people reached the ground truth before it was widened
  enough: "Sarah", "City Hall", "Headland Way", "Madam Chair". Widen the gate
  when one slips; do not special-case.

## Also landed this session

- **High School Building Project folded into the Building Committee.** One
  body, 100 meetings, 2024-02-29 to 2026-10-06. Keywords merged so new titles
  route there and the merge survives a metadata refresh.
- **Licence footer on every page** via `utils.site_footer(prefix)` -- index,
  all transcript pages, all committee pages. Backfilled into 25,111 existing
  pages by direct insertion (`backfill_footer.py`), because a full srt2html
  pass redoes nine-language translation and was killed for memory twice.

## Open, in rough priority order

1. **101 retry clusters** (above).
2. ~~The 10/6 MHSBC meeting~~ **DONE** (`CP5ho6yZUqo`). Its title says
   "10.6.25", so `title_date()` read it as **2025** and priority dropped
   ~160x, parking a two-day-old meeting at the back of the queue. Fixed with
   `date_manual: True` -- the supported override; a bare `date` edit is
   re-derived away on the next refresh. It then ran the whole way: ASR 13:24,
   alignment 14:09, diarization finished 20:47, final `.srt` 21:07, HTML
   published 22:05. Diarization took ~6.5 h on a 3h34m recording.
   Loose end: its `priority` reads 0 and I never established what zeroed it.
   It did not block anything -- the date fix is what got it picked up.
3. **40 truncated translation pages**, published and indexed as stubs (one is
   205 bytes). Pre-existing; the footer backfill surfaced them. See PENDING.md.
4. **32 corrections sit accepted-but-unapplied**, and `ingest_corrections.py`
   is still not wired into the hourly job, so a correction can sit unseen.
5. Everything else in PENDING.md -- parcel directory (blocked on a manual
   download), official-body alias map, biohashing the voice embeddings.

## Untracked files predating this session

`download_vod.py`, `migrate.py`, `update_councilors.py`, `update_vod_meta.py`
are untracked and were not written here. Decide whether they are keepers.
