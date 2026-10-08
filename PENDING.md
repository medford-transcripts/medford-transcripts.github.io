# Pending

Open items with the measurement that established them, so none of this is
re-derived. Standing rule: file it here before it is compacted away.

Last updated 2026-10-08.

## Open, blocked on Jason

- **Parcel directory is lossy; re-run it.** `54 Dwyer Cr` is absent from
  `street_list_parcels.json` in both indexes (the street jumps 50 → 57), and
  no Teixeira or Fairchild appears anywhere in it, though both are on the
  address per Jason. `build_parcel_directory.py` silently drops a parcel when
  the use-code is not residential OR the owner parses as an entity
  (`LLC|TRUST|REALTY|…`), so "Teixeira Daniel Trust" would vanish.
  **Blocked:** `download.massgis.digital.mass.gov` resolves (16.15.252.219) but
  resets the connection from this machine, while `medfordma.org` returns 200 —
  so it is that host specifically. Needs the zip fetched by hand:
  `L3_SHP_M176_MEDFORD.zip`. Then re-run with per-address rejection logging.
  **Why it matters:** the parcel file is how a spoken name gets its spelling
  verified. Of 77 clusters that state a name + address, only 25 addresses were
  found and 7 names verified. That 7 is a floor set by this gap, not a measure
  of the method.

## Open, actionable

- **Official city-page links reach only 22 of 88 meeting types.**
  `official_body_url()` IS wired into `make_committee_pages.py:185` and 22
  committee pages carry a link, so this was never dropped — it under-matches.
  `utils._body_key()` is exact-match only, and the city names bodies
  differently from our meeting types. 18 roster bodies match nothing:
  Historic District Commission, License Commission (vs our "Liquor License
  Commission"), Parks Commission (vs "Park Commission"), Small Cell Committee,
  Library Trustees, Cemetery Trustees, Retirement, Airplane Noise Advisory,
  Commission of Trust Funds, Commission on Parking Policy, Community Fund
  Committee, Community Garden Commission, Consumer Advisory Commission, Fire
  Department Facilities Task Force, Keep Medford Beautiful, Neighborhood
  Ambassadors, Promote/Prevent/Support Behavioral Health, Civic Auditorium.
  Fix is an alias map, not fuzzy matching — "Historic District Commission" and
  "Historical Commission" are two REAL and DIFFERENT bodies, so a fuzzy match
  would conflate them.

- **Paragraph breaks land mid-sentence.** `PARA_GAP_SECONDS`/`PARA_MIN_WORDS`
  in `srt_lines.py` fire on a timing gap alone. Require sentence-ending
  punctuation on the preceding block as well.

- **Long monologues are hard to scan** — no visual anchor for who is speaking.
  Indent continuation blocks (n>1), or repeat the byline. Note: continuation
  lines carry NO `data-speaker`, which is correct (nothing for the correction
  form to rewrite) but means a repeated byline must come from the renderer,
  not the attribute.

- **11 corrections sit `accepted` but unapplied**, all from Jason's desktop
  token, 2026-09-27..29: `YV6lriLOtwQ`, `Ewo7VA32tkU` (3), `CAS00002526` (3),
  `CAS00002522`, `CAS00002523`, `MCM00001099` (2). Deliberately not applied —
  he asked only for the phone submissions.

- **40 machine roll-call proposals are `pending`** review in the queue.

## Speaker identification — measured, not yet built

Of the top 400 unidentified cross-matched clusters:

| | |
|---|---|
| thin (matcher artifacts) | 63 |
| substantive | 328 |
| → no name cue in the transcript at all | **232 (71%)** |
| → state name + address | 77 |
| → self-name, no address | 19 |
| address found in parcel file | 25 of 77 |
| owner name agrees | 7 |

- **`toid.py`'s ranking is misleading.** It sorts by how many meetings
  reference a cluster, and the top entries are artifacts:
  `U1EIl_L-LWc_SPEAKER_00` is 1 block / 17 words / 4 seconds matched into 31
  meetings; `o9F0qYH9Geo_SPEAKER_05` is 6 words of "Thank you." across 28.
  Short turns carry almost no speaker information. Rank by meetings × speech
  volume, or apply a floor (>=50 words AND >=20s) as done in the table above.

- **The Zoom overlay works and is the only route to the 71%.** Verified on
  `nqVIJ3wsDWg` t=12677: the frame reads "Talking: BDan Fairchild", matching
  his spoken "B. Daniel Fairchild". 10 s of video is ~244 KB via yt-dlp
  `--download-sections`, one ffmpeg call for the frame. It is also MORE
  reliable than the text: the transcript's own intro cue produced
  "Lessenhaupt", which was the PREVIOUS speaker being thanked.

- **Two overlay formats seen, and one blind spot.**
  - 2020-12-01 City Council: participant name bottom-left ("Breanna
    Lungo-Koehn") on a full-screen speaker view.
  - 2022-06-14: "Talking: Council Chambers" bottom-right — names the ROOM, not
    the person, when the feed is the in-room camera.
  - 2024-12-11: Zoom **screen-share** (a document) — no name anywhere. During
    presentations there is nothing to read.
  - Pre-2020 (e.g. 2019-04-01) is in-person chamber video with no annotation.

- **Jason's steer (2026-10-07):** post-2020 most meetings are hybrid or
  Zoom-only, so one speaker at the podium does not mean the next is also
  in-person. **Subcommittee meetings are more often Zoom — start there**,
  especially for a cluster that appears in both a subcommittee and a main
  meeting.

- Frame grab is ~20-40 s per meeting, dominated by throttled download
  (~20 KB/s). For production, pull ONE frame at a timestamp where the target
  cluster is known to be speaking — one frame per cluster, not per meeting.

## Also noted

- `city_council_president` has only 2 entries in `councilors.json`; the gavel
  is missing from most years.
- Orphan directory `2025-08-28_afnvZAYk2_M`.
- 363 published pages have no `.words.json` because they have no `model.pkl`.
  They never worked; regenerating cannot fix them. See the memory note.


## Face matching — measured 2026-10-07, not built

Jason's framing is wider than identification: use face as a CONFIRMATION
signal for embedding matches, to raise confidence, safely lower the match
threshold, detect blended clusters, and possibly improve diarization.

**Coverage, of 676 substantive unidentified clusters:**

| route | clusters |
|---|---|
| names itself in the transcript | 110 |
| no cue, post-2020, YouTube-hosted | 218 |
| no cue, post-2020, other host (MCM/CAS) | 229 |
| no cue, **pre-2020** | 119 |

The 119 pre-2020 have NO Zoom overlay to read -- video identification there is
face or nothing. The 229 on MCM/CAS need their own slicing path before any
video route works at all. So the Zoom overlay alone reaches at most 218, and
only the remote speakers among them.

**Confirmation opportunity, from 856 scored embedding matches:**

    min 0.701  p10 0.785  median 0.924  p90 0.993
    0.70-0.75:  54      0.85-0.90: 139
    0.75-0.80:  46      0.90-1.00: 547

~100 matches (12%) sit in the weak 0.70-0.80 tail -- exactly the band a second
signal would confirm or reject. The floor at 0.701 is the threshold itself:
nothing below was ever attempted, so a corroborating signal is what would let
it drop safely.

Also: **30,655 labels carry provenance "unknown"** against 856 embedding_match.
The unknown pool dwarfs everything and is its own problem.

**THE DESIGN THAT AVOIDS THE BIOMETRIC DATABASE.** The confirmation use case
needs face COMPARISON, not face IDENTIFICATION: "do these two speaking moments
show the same person?" is a same/different judgement inside our own corpus, and
it never requires a name/face link. If the only thing persisted is the pairwise
verdict -- which is what a speaker_ids cross-reference already is -- and the
templates are discarded, there is no face database at rest to leak, subpoena or
inherit. Naming still comes from the Zoom overlay, the transcript, or Jason.

That converts "I won't abuse this" into "this cannot be abused that way."
Jason's own words: "the only thing preventing me from doing that is my
discretion." A policy; this would be a property.

Open questions before building: scope strictly to speaking moments; decide
whether templates are ever written to disk (recommend no); keep it out of the
public repo either way, as voiceprints already are.


## Biohash the voice embeddings too — filed 2026-10-07, sequencing matters

Jason asked whether the keyed-projection idea applies to `embeddings.pkl` as
well as to any future face templates. It does, and the case is STRONGER there:

- The voiceprints already exist, on disk, today. Face templates are
  hypothetical; this is a live exposure.
- Same mathematics. Speaker embeddings are fixed-length vectors compared by
  cosine similarity, so a secret orthogonal projection preserves the metric
  and `track_speakers.match_embeddings()` works unchanged on transformed
  vectors. The 0.70 threshold keeps its meaning.
- It makes a leak CANCELABLE. Today a voiceprint leak is permanent — you
  cannot reissue someone's voice. Under a keyed projection you re-key and the
  leaked templates are inert.

**DO NOT RUN THIS WHILE THE MATCHER IS IN USE.** Every stored embedding has to
be transformed once, and every later comparison must use the same R. Mixing
transformed and untransformed vectors does not raise an error — it silently
returns wrong similarity scores, which is this project's recurring failure
shape. Requirements before starting:

  1. a version marker inside the pickle, so a mismatch is loud rather than
     silent, and the matcher refuses rather than guesses
  2. a quiet window: the transcription loop and any video sweep stopped, since
     both call the matcher
  3. R stored in `credentials/`, and NOT in the same backup as the templates —
     co-locating them collapses the entire benefit
  4. a before/after check that match scores are preserved on a held-out set;
     an orthogonal projection should reproduce them to float precision

**Consider the cheaper option first.** The durable product of the embeddings
is the `speaker_ids` cross-reference graph, not the vectors. If the vectors
are only needed to match NEW meetings against old ones, the question is
whether all of them must be retained or only a representative set per
identified person. Fewer templates beats better-protected templates, and it
is less work.

Scope note: this protects against LEAK, not against USE. Transformed
embeddings still identify speakers — that is the point, and per PRINCIPLES.md
§4 the capability is wanted. The threat it addresses is templates escaping on
their own: a bad commit, a backup, a stolen drive.

## Video sweep -- RUNNING. Automatic fallback built; 0 wrong names so far

`identify_from_video.py` is now a resumable queue, not a one-shot grab. State
in `video_id_frames/sweep.json` (gitignored with the frames -- they are
photographs of people).

    --sweep     grab one attempt per due cluster, advancing on failure
    --pending   what is awaiting a read, with a per-strip legend
    --record -  take verdicts from stdin
    --retile    rebuild tiles from frames on disk (free)
    --reground  recompute transcript ground truth and re-score
    --status    progress and the error measurement

**The fallback is automatic in the advance, not the verdict.** The reader
answers only "is there a name in this image"; the script owns which meeting
that image came from, when to retry and when to give up. A "room" verdict bars
the WHOLE meeting (the label describes the camera feed); any other failure
bars only that (meeting, speaker key) pair. VERIFIED END TO END: one cluster
read as gallery view in meeting 1 and moved itself to another, where it came
back unanimous.

**Reads are tiled strips.** One band per frame, stacked into one image with
magenta seams -- one read per cluster-attempt instead of one per frame, which
is what makes 277 candidates affordable. A camera-off frame substitutes the
CENTRE band, because Zoom puts the name card there; that one change turned six
black strips into a clean "Michael Downs".

**The legend is what made reads determinate.** Strip k of a slice starting at
t is at t + (k-1)*GRAB_EVERY, so the SRT says who was talking in each strip.
It has self-validated repeatedly: non-target strips name the speaker the SRT
has at that second ("Andre Leroux, Chair" on "this is Andre LaRue, the chair").

**MEASURED SO FAR: 29 named, 14 with transcript ground truth -- 7 exact, 7
spelling variants, 0 disagreements.** Every variant is the overlay CORRECTING
the ASR on an unusual surname (Dubrule/Dubrul, Rettenmeier/Rattenmayer,
Junghans/Anhansen, Caracci/Karachi, Champy/Champey, Zachrison/Zacherson,
Fischer/Fisher). That comparison is two noisy sources, not frame-vs-truth.

### Rules the reads established, each on evidence

- `MIN_TURN_FOR_VIEW = 5.0s`. A 3.9s turn read "Alicia Hunt" while a 15.6s turn
  by the same cluster read "Margaret Moran" on both overlay formats. Zoom
  switches the active-speaker view on SUSTAINED speech, so a short interjection
  shows the PREVIOUS speaker.
- **Live-caption avatar initials are the best signal.** They are Zoom
  attributing the utterance, so no view-switch lag, and they work on turns far
  too short to move the view. CB/EH/DE matched the SRT's three speakers exactly
  on one tile.
- **Never read text inside a screen share.** "10. Nicole Morell" was a bullet
  on a shared slide. Only the chrome Zoom draws counts.
- **Never harvest a gallery frame's roster** -- an attendance record of people
  who never spoke, forbidden by PRINCIPLES.md §2.
- Pronouns come off BEFORE the "/" split, or "Divya Anand she/her" becomes
  "Divya Anand she" -- a plausible-looking wrong name, the worst kind.
- `weak:<name>` holds a candidate seen only on short turns without publishing
  it; a repeat from a different meeting is corroboration rather than a rule
  invented to justify the first read.

### Open

- **The sweep is NOT finished.** ~92 of 277 candidates touched. Resume with
  `--sweep --limit 20` in a loop (bounded runs: one long process was killed for
  memory), then `--pending`, read, `--record -`.
- **Nothing has been written to speaker_ids.json yet.** Naming goes through
  the cluster HOME via apply_corrections so propagate() carries it.
- Coverage ceiling: screen shares and in-room cameras are blind. Of reads so
  far the common failures are screen share, "Council Chambers", and display
  names that are not full names ("Caroline", "PNoone", "Sarah M_TGE",
  "Jack's iPhone" -- rejected by A_DEVICE).
- Self-ID patterns widened from the legends (contraction, role-first, "this is
  X with Y", "for the record, X with Y"); all now pass through
  plausible_name(), which had been letting "City Hall" through as ground truth.
