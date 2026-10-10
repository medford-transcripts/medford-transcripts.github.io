# Resume here

Written 2026-10-08, added to 2026-10-09. Picks up where the session stopped.
Read PRINCIPLES.md first; PENDING.md holds the older backlog.

## The sitemap had stopped being written -- fixed 2026-10-09

Seven days stale, and not a scheduling problem: `make_sitemap()` globbed 2,500
files, filtered them five ways, built the whole XML tree and **never wrote
it**. 7a280f855b ("Retire sitemap.txt", 2026-10-02) deleted
`save_sitemap(sitemap_root, "./sitemap")` along with the sitemap.txt write it
meant to retire -- and that one call wrote the XML too. No exception, no log
line, sitemap.xml frozen at its 10-02 mtime while index.html and committees/
-- rebuilt in the same `do_extras` block, immediately before it -- stayed
current. 151 published pages went unadvertised.

Now writes via `utils.write_atomic` and prints `sitemap: N urls`, because a
silent generator is indistinguishable from a skipped one in a log.

**The checker should have caught it, and could not.** `check_sitemap.py`
counted the 115 `skip=True` duplicate recordings as orphans -- make_sitemap
excludes them on purpose -- so every run ended "VERDICT: sitemap has issues"
and nobody read it. Both sides now agree on what published means:

    python check_sitemap.py        # 2,416 urls, 0 orphans: "sitemap is clean"

The lesson is the one already in PRINCIPLES #4, arriving from a new direction:
a check that always fails is not a check. Worth looking at `bing_status.py`
and the other validators for the same shape.

## Gemini 3.5 deprecation: the summaries were naming the wrong author

Google's notice ("3.5 Flash deprecated, traffic auto-redirected to 3.6") turned
out to matter for provenance, not for uptime. Probed 2026-10-09, reading
`modelVersion` back off each response:

    gemini-3.5-flash        -> served by gemini-3.6-flash
    gemini-3.7-flash        -> served by gemini-3.8-flash
    gemini-3-flash-preview  -> itself

**Three engines behind five names, and the listing still advertises the
retired ones**, so the only way to tell an alias from an engine is to ask and
read the answer. `_gemini_parse` ignored `modelVersion` and `ask()` returned
the id it REQUESTED, so **250 summaries say "gemini-3.5-flash"** when the
recent ones were written by 3.6 -- a false claim in our own voice, printed on
the page banner (PRINCIPLES #5). All three providers now record what answered;
when it differs from what was asked, the run says so.

Those 250 labels are NOT retroactively fixable: the redirect date is unknown,
so early ones are honest and later ones are not, and there is no way to tell
them apart. Leave them; new ones are accurate.

**The ladder was also walking the same bucket twice while looking like two.**
Its whole premise is that families have separate daily allowances, so an alias
beside its target is the one mistake it cannot afford. Now one entry per
engine: 3.6, then 3.8, then 3-flash-preview, then pro. 3.6 stays first because
it is what has been writing the corpus all along -- a truthful rename, not a
change of product. **3.8-flash was unreachable before this** and is net new
allowance; it earned itself within minutes, picking up a meeting after 3.6
returned 503.

Whether 3.8 is BETTER than 3.6 is unmeasured. compare_summaries.py is the tool.

Also fixed: `--limit` counted cache hits, so with the queue now tiered (97
current meetings ahead of the first unwritten one) `--limit 8` stopped after 8
cache hits and summarised nothing. Third time that counter has been wrong in
the same direction.

### What this bought

**The MHSBC summary gap is CLOSED** -- 0 transcribed-but-unsummarised, so the
committee overview now spans 2024-05-01 to 2026-10-06 across 67 meetings
instead of starting in Feb 2025.

## The site has its own search now -- 2026-10-09

The front page used to hand the query to Google with `site:`, under a note
that said "this only searches pages Bing/Google have indexed, which is very
incomplete". True, and the problem: 2,376 English pages, 207 MB of transcript
text, an unknown fraction reached by a crawler and no way to see which
fraction. `build_search_index.py` writes `search_index.json`; the box in
`header.html` searches it in the reader's browser.

**0.89 MB, 0.17-0.19 MB gzipped, 7.3 s to build, no new dependency, no CI.**
Shipped whole, so there is no per-keystroke request and no query leaves the
reader's machine.

### Why not Pagefind, which is the obvious answer

It is the right SHAPE -- sharded, fetched on demand -- and FlexSearch/Orama
are not (they hold the whole index in browser memory, finished before they
start at 35M words). But Pagefind works by CRAWLING generated HTML, and this
pipeline GENERATES that HTML from the SRTs, per meeting, incrementally. It
would mean a full pass over 406 MB of HTML on the box that OOM-killed three
runs on 2026-10-08, and tens of MB of binary index churned into a `.git` that
is already **8.3 GB**. Emitting the index at generation time costs 7 s.

This also answers the CI question: **nothing here needs CI.** No build step,
so the 4-minutes-to-40 regression has no way to recur.

### It keeps itself current, in two places

    srt2html.make_index()      # new transcripts; front page + index together
    publish_summaries.py       # once per summary run, before it commits

The second one matters more than it looks: only **545 of 2,260** meetings have
a summary, so ~1,700 summaries are still to come and each one makes its
meeting more findable. Rebuilding per summary would cost 7.3 s each;
rebuilding once per run costs 7.3 s a night. `search_index.json` is in
`GENERATED_PATHS` and in `publish_summaries.PATHS`, so both paths publish it.

**IT WILL NOT GO LIVE BY ITSELF, and that is correct.** `srt2html.py` and
`create_subtitles.py` were both edited, so the running loop's
`sources_changed()` now holds back every `GLOBAL_REGENERATED` path --
index.html, search_index.json, committees/ -- until the process restarts,
rather than republishing them from the code it loaded days ago. To ship:
commit by hand, or restart the scheduled tasks.

### Whose names are searchable -- the part that took the measuring

**Officials by roster, plus anyone speaking at 5+ meetings, minus an exclude
file.** 465 names today. The roster alone was the wrong cut: not one of the
people presenting the high school project is an elected official, and they
clear the recurrence bar easily -- Maria D'Orsi 60 meetings, Matt Rice 52,
Libby Brown 40, Luke Preisner 36, Kenneth Lord 34, Kimberly Talbot 28, Matt
Gulino 19, Martine Dion 16, Brian Hilliard 14. Recurrence also caught 287
names no roster file has at all, including **Adam Hurtubise (577 meetings)**,
the City Clerk.

At the other end, 545 of 1,405 names speak in exactly ONE meeting -- a
resident at a microphone once. Their name stays on that transcript page, where
it belongs, and out of a downloadable map from a name to every meeting they
ever attended (PRINCIPLES #1).

Rosters read: `councilors.json`, `electeds/`, `rosters.json`,
`staff_titles.json`. **Not `staff.json`** -- gitignored because it carries
contact details, and that reason applies here too.

**The hole, found by sampling the band just below the line:** `Pat Jehlen`,
state senator for Medford, 4 meetings. Officials from OUTSIDE city government
fail both tests at once -- no local roster lists them and they appear rarely.
Hence `search_names_include.txt` (she is its first entry) alongside
`search_names_exclude.txt`, which wins over everything. Expect more of these:
MSBA staff, the federal delegation, state agency people.

**Where the proxy is wrong, and it is a proxy:** a resident commenting at
twenty council meetings a year is indistinguishable by recurrence from a
consultant presenting at twenty. The exclude file is the per-person fix;
`--min-meetings N` moves the line (2 -> 819 names, 5 -> 465, 12 -> 308).

### Tested without a browser, because there isn't one here

`node` runs the real inline script against the real index with a DOM stub --
scoring, snippets, deep links and the HTML it emits. Harness is in the
scratchpad, worth keeping if search grows:

    509 distinct result links across 8 queries, 0 broken
    73 titles contain < > & or " -- all escaped, no raw markup in output
    "culvert" -> correctly reports that full text is not searchable yet

### What it does NOT do

**Not full-transcript search.** A word spoken once in 2017 is not in here, and
the UI says so rather than implying otherwise. That is tier 2: a term-sharded
postings index from the SRTs, 50-150 MB for 35M words. The browser is fine
with that -- one or two shards per query -- and the 8.3 GB repo is not, so it
is a decision about where index artifacts live, not a library choice. Filed in
PENDING.md.

Also fixed: the two nested `form` tags on the front page (invalid markup; the
inner Bing one had been inert since it was written). The no-JS path is now a
real Google fallback in `<noscript>` using `as_sitesearch`, which works
without the JS the old `site:` suffix hack needed.

## Committee overviews -- 2026-10-09, waiting on tomorrow's free quota

The ask: a top-level "what has this body been doing" on each committee page,
tried first on the High School Building Committee. Two pieces landed; one
request has to wait, because Gemini's daily allowance was already spent at
08:07 and nothing here is worth paying for.

### 1. The summariser now has a priority order

`--all` was strictly date-descending, which keeps up and cannot fill a hole:
the Building Committee's founding months were ~1,700 meetings deep in a queue
moving 2-20 a night. It is now tiered -- last 30 days, then
`summary_priority.txt` in its own rank order, then the backlog -- and
`--plan N` prints the queue, with tiers, spending nothing:

    python summarize_meeting.py --plan 30

Measured after the change: the 8 unsummarised Building Committee meetings are
the first 8 `WANT` rows in the queue, at positions 98-105 behind 97 cache hits
that cost 3.7ms each. The hourly job reaches them seconds into its run.

**So: nothing to do but let 03:05 ET happen.** Then check:

    python summarize_meeting.py --plan 30        # expect 0 of the first 30 WANT

### 2. summarize_committee.py, written and dry-tested, never yet run live

Input is the per-meeting summaries, NOT the transcripts -- 96k chars for 58
meetings, one request. Citations are LABELS (`M07#4`) copied from the prompt,
so verification is exact set membership and a mangled number cannot become a
link to the wrong moment; an unknown label is dropped and a thread left with
no citation goes with it. Even weighting is measured, not promised: the
sidecar records how many distinct meetings were cited and the largest share
any one of them took.

Verified on a fixture with real citation labels: a bad label is dropped from
all three threads, 8 of 8 periods covered, 18 of 18 rendered links resolve to
a real page. The API call is the only untested part.

    python summarize_committee.py -c "MPS High School Building Committee" --force
    python make_committee_pages.py          # renders it above the table

**RUN THAT --force ONCE MORE AFTER 3 AM ET**, and this is the only loose end.
The overview on disk is v1 and its ten period narratives carry NO citations:
the model cited periods as whole meetings ("M09"), which is the natural unit
for "what was this quarter about", and only ITEM labels were in the index, so
verification dropped all 24. The model was right and the vocabulary was too
small. Both kinds are now citable and the renderer links a whole-meeting
citation without a #t= fragment -- but the regeneration needs a request, and
the day's gemini allowance went on the 8 backfills plus v1.

v1 is otherwise good, and its measured spread is the thing this was built to
fix: **35 citations across 28 of 67 meetings, heaviest single meeting 8.6%**.
The threads carry 5-6 citations each. Nothing about v1 is published --
`committees/*.overview.json` is deliberately NOT in the commit, and the
committee pages were not regenerated, so no reader sees an uncited period.

**Do it in that order and AFTER the backfill**, because the span today is
2025-02-11 to 2026-10-06: without those 8 meetings the overview silently omits
the committee's entire founding year, which is the one thing a reader most
needs it for.

**IT PUBLISHES ITSELF IF YOU ARE NOT WATCHING.** `committees` is in
`create_subtitles.GENERATED_PATHS`, so the next transcription publish -- every
few hours -- stages `committees/*.overview.json` and the rebuilt pages and
pushes them. Generate it when there is time to read it first, not at the end
of a session.

Three gaps it exposed are filed in PENDING.md: no two-stage pass for bodies
too big for one request (City Council), duplicate detection blind to the
one-day Castus/YouTube offset, and two MHSBC subcommittee meetings typed to
the parent body.

Also fixed in passing: one title in 2,261 is outside cp1252 (`gT4_C1uPttA`)
and `print` raised on it, which would have killed a whole nightly run on
reaching that meeting rather than skipping it. And `--self-test` had been
reporting FAIL on every run since `meeting_types.json` gained
`"label": "MCHSBC"` -- the expectation was stale, not the code. **Worth a
decision:** that label is what composes reader-facing titles, so they read
"MCHSBC: Feasibility Study Contract - 2026-08-25". The test's old expectation
was the long name. MCHSBC is what the committee calls itself and what the
COW precedent supports; it is also opaque to a reader arriving cold.

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

## Check this first: are the tables current?

A transcript page can publish without anything LINKING to it. On 2026-10-08
the 10/6 MHSBC meeting published at 22:05 while `index.html` and the committee
pages were last built at 17:44, so it was reachable only by guessing its URL.
The pipeline normally rebuilds them on publish and did not here -- possibly a
casualty of the same memory pressure that killed three other runs that
evening, possibly a real gap.

    ls -l index.html committees/index.html      # compare against the newest 20*/ page
    python -c "import srt2html; srt2html.make_index()"
    python make_committee_pages.py

Cheap to run, and an orphaned page is invisible to readers and to search.

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
