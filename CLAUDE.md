# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

This is a civic transparency project that automatically transcribes Medford, MA government meeting videos (City Council, School Committee, etc.) from YouTube and other sources, then publishes the transcripts as a static GitHub Pages site. The pipeline covers audio download, AI transcription (WhisperX), speaker diarization and identification, HTML generation with multi-language translation, and optional "supercut" video clips of individual speakers.

## Required credentials (not committed)

- `hf_token.txt` — HuggingFace token with access to `pyannote/speaker-diarization-3.1`
- `openai_key.txt` — OpenAI key (optional; used by `supercut.py` for ChatGPT-assisted text)
- `reddit.json` — Reddit API credentials (used by `post.py`)
- `cookies.txt` — YouTube cookies (generated via `yt-dlp --cookies-from-browser firefox --cookies cookies.txt`)

## Common commands

**Run the full transcription loop (downloads + transcribes + publishes):**
```
python create_subtitles.py -c channels_to_transcribe.txt -i ids_to_transcribe.txt
```

**Transcribe specific YouTube IDs (listed one per line in `ids_to_transcribe.txt`):**
```
python create_subtitles.py -i ids_to_transcribe.txt
```

**Regenerate HTML for one video (after editing `speaker_ids.json`):**
```
python srt2html.py -i <yt_id>
```

**Regenerate all HTML (e.g., after a template change):**
```
python srt2html.py
```
To force-regenerate even up-to-date files, uncomment `last_update = 0.0` in `srt2html.py:143`.

**Rebuild transcript from saved diarization model (skips download/transcription):**
Calling `create_subtitles.rebuild_from_model(yt_id)` from a Python shell.

**Update video metadata only:**
```
python create_subtitles.py -u
```

## Architecture

### Data flow

```
YouTube / MCM Archive
       │
       ▼
create_subtitles.py   ← main pipeline orchestrator
  ├── download_audio()   → audio/<date>_<yt_id>.mp3
  ├── transcribe()       → WhisperX (large-v2): basic + aligned SRT + diarization
  ├── track_speakers     → match speaker embeddings across videos
  └── finish_async()     → srt2html + git push (runs in background thread)
       │
       ▼
srt2html.py            ← SRT → HTML converter
  ├── fix_common_errors  → pre-processes SRT before conversion
  ├── googletrans        → translates to 9 languages (es, pt, zh-cn, ht, vi, km, ru, ar, ko)
  ├── heatmap.py         → folium heat map of speakers' home addresses
  └── make_index()       → regenerates top-level index.html

scrape.py              ← scrapes civicclerk.com for agendas/minutes/resolutions PDFs
supercut.py            ← creates video mashups of a specific speaker's clips
make_committee_pages.py ← generates committees/ index grouped by meeting type
```

### Key data files

- **`video_data.json`** — central metadata store (title, date, channel, duration, `meeting_type`, `skip`, `priority`, `last_update`). Thread-safe reads/writes via lock file `video_data.lock`. Never update `upload_date` after first set — directory paths depend on it.
- **`<date>_<yt_id>/speaker_ids.json`** — maps auto-assigned diarization IDs (`SPEAKER_00`, etc.) to human names. Edit this to identify speakers; rerun `srt2html.py -i <yt_id>` to regenerate HTML. Cross-video references use the format `<yt_id>_<SPEAKER_ID>`.
- **`<date>_<yt_id>/embeddings.pkl`** / **`model.pkl`** — saved WhisperX diarization output; enables rebuilding without re-transcribing.
- **`councilors.json`** — known elected officials; used for speaker stats tables and supercut targeting.
- **`addresses.json`** — maps speaker names to addresses for heatmap generation.
- **`meeting_types.json`** — keyword lists that classify video titles into meeting types (e.g., "CC City Council", "SC School Committee").
- **`channels_to_transcribe.txt`** — YouTube channel handles to monitor.
- **`ids_to_transcribe.txt`** — specific YouTube IDs to prioritize (checked before the general queue).

### Non-YouTube sources

- MCM Archive IDs use the prefix `MCM000` and are handled by `download_mcm.py`
- MCM Castus IDs use the prefix `CAS000` and are handled by `download_castus.py`
- Podcast/RSS feed IDs use the prefix `XXXXXX` with a zero-padded episode number

Each prefix needs a branch in **both** `srt2html.timestamp_url()` (the per-line
deep link) and `srt2html.player_source()` (the in-page player). Falling through
to the default is silent: `player_source` returned `("youtube", "CAS00000001")`
for a Castus id, so the page embedded a YouTube video that does not exist and
rendered "this video is unavailable" — which reads as a dead source rather than
a missing branch.

**Id numbering convention.** Numbers are handed out in **upload-date ascending**
order, so `MCM00000001` / `XXXXXX00001` / `CAS00000001` are the *oldest* items
and the numbers read as a timeline. `download_mcm` gets this from archive.org's
`publicdate asc`; `download_castus.enumeration_order()` does it explicitly. The
`id → source id` mapping lives in a tracked index file (`medford_index.json`,
`castus_index.json`) and **never** in `video_data.json` — video_data is a
rebuildable cache, and an id that moved when it was rebuilt would rename
published URLs underneath readers. Once minted a number is never reissued: a
later-arriving older item appends rather than shifting its neighbours, so the
ordering is a convention for new imports, not an invariant to re-establish.

**Why upload date and not meeting date.** Upload date is immutable; the meeting
date is parsed out of the title by regex and **23% of Castus titles have no
date in them** ("Medford Happenings - Laura O'Neil"), so `meeting_date()` falls
back to the upload date for 573 of 2,534 items. Keying a permanent id on a
fallible parse would let a title correction move a published URL. The cost is
that content older than its upload sorts by when it was posted: the oldest
recording in the Castus catalogue is a 2006 Vietnam Veterans speech, uploaded
2021-05-31, so it is `CAS00000654` rather than `CAS00000001`. 131 items were
uploaded more than 60 days after they were recorded.

> **DONE 2026-09-25.** The first Castus import ran this backwards (raw API
> order is newest-first), leaving the ids ~98% *descending*. `renumber_castus.py`
> fixed them during a pipeline restart: 2,532 ids remapped, 1,514 paths moved,
> 1,109 `duplicate_id` references rewritten, 0 dangling. CAS ids are now 100%
> ascending by upload date and `CAS00000001` is 2018-10-01.
>
> **If it is ever needed again**, it must run only while the pipeline is
> stopped, because `create_subtitles.py` saves its whole in-memory `video_data`
> without re-reading first, so a live loop would write every old CAS key back
> beside the new ones. The script refuses to run if it detects
> `create_subtitles.py` alive, and treats "cannot check" as unsafe.

**Long-running loops hold stale code.** `download.bat` / `transcribe.bat` import
`utils` once and run for weeks, so a fix to `identify_duplicate_videos` does not
reach them until the process restarts — and `make_committee_pages` calls that
function on every publish. A dedup repair applied from a shell was silently
reverted twice by a loop running a module imported days earlier. Restart the
scheduled tasks after changing anything the loops import.

### GitHub Pages publishing

`create_subtitles.push_to_git()` commits `20*/`, `resolutions/`, `agendas/`, `minutes/`, and `other_files/` with the message "add video" and pushes. A threading lock prevents concurrent pushes. The `header.html` template is prepended to build `index.html`.

### Speaker identification workflow

1. WhisperX assigns generic `SPEAKER_00`, `SPEAKER_01`, etc.
2. `track_speakers.match_embeddings()` compares cosine similarity of voice embeddings across videos (threshold ~0.7).
3. `track_speakers.match_to_reference2()` compares against reference voice files in `generate_reference_voices.py`.
4. `track_speakers.propagate()` propagates manual name corrections from one video's `speaker_ids.json` to all others that cross-reference it.
5. Manual corrections in `speaker_ids.json` are the ground truth; they override automatic matching.
