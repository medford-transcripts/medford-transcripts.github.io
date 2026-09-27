This website posts AI-generated transcripts of youtube videos relevant to Medford, MA local politics, including but not limited to city council meetings, school committee meetings, subcommittee meetings, campaign videos, and local news reports.

The intent is to make it easier for the public to make informed decisions, advocate for their interests, and generally engage with these meetings and be an informed electorate.

The code to generate all open source (https://github.com/medford-transcripts/medford-transcripts.github.io). It uses yt_dlp to download the audio, then uses the AI-driven whisperX (https://arxiv.org/abs/2303.00747) to transcribe it and add speaker IDs. 

I've modified WhisperX to return the speaker embeddings, and use those embeddings to match speakers between videos. Generic IDs are propagated along with the YouTube ID for consistent naming, but are replaced with user input names should the speaker_ids.json file be edited manually.

The transcriptions contain many errors (particularly in the speaker identifications), and manual corrections to the SRT files are occasionally made. Corrections will be gladly accepted, and any controversial corrections will be flagged as such. Beginning on 1/15/2025, I began saving the word-level timestamps in model.pkl and that will need to be edited to make corrections.

Translations are currently DISABLED. The googletrans library broke in a way that was worse than useless: half the target languages raised errors and the other half silently returned the English text unchanged, so ~20,000 pages were being served as `lang="ar"` or `lang="km"` with English in them. Those pages are no longer tracked or published. Older pages from before the breakage were genuinely translated. The intended path forward is to translate the short meeting summaries rather than whole transcripts -- cheap, and spot-checkable. Those summaries now exist (below), but are deliberately English-only for the moment: translating a machine summary with a machine translator compounds two error rates, and the breakage described above is exactly what that looks like when nobody checks.

Each transcript page now opens with an **AI-generated agenda summary** -- an overview plus the items in the order they were taken up, each linking to the moment it began. It is labelled as machine-written, names the model that wrote it, and sits above the transcript, which remains the record. It reports outcomes when they are stated plainly ("the motion passes") but never says who voted which way: roll-call turns are short, and short-turn speaker attribution measures 53-66% against a human reference versus 97% on substantive speech. Timestamps are verified against the meeting's real duration before publication, and anything that falls outside is dropped rather than shown.

If you'd like to submit corrections, right-click any line on a transcript page and choose "Correct or verify this line". That opens a form pre-filled with the line you clicked; edit it and submit, or submit it unchanged to confirm the line is already right. Corrections are reviewed and applied with `ingest_corrections.py` / `apply_corrections.py`, and every change is a public commit, so a correction is exactly as visible as the original text.

Transcription runs at about **2.2x real time on CPU** -- measured over three days of real running, not estimated -- so a 1-hour meeting costs about 2.2 hours of compute. Roughly half of that is diarization, not transcription.

**These numbers are CPU-only.** This machine has no CUDA GPU, so WhisperX and pyannote both run on the processor. All three stages -- transcription, alignment and diarization -- are GPU-accelerated if one is present, and the code already selects CUDA automatically when `torch.cuda.is_available()`. A modest GPU should cut the backlog from months to days; `gpu_benchmark.py` measures exactly that on a given card before you commit to it, including whether the card has enough VRAM to hold the diarization models at all (which is what decides the real speedup -- accelerating only transcription caps out around 2x).

Sources currently monitored: the CityofMedfordMass, medfordpublicschools464, medfordcommunitymedia391, InvestinMedford and ALLMedford YouTube channels; Medford Community Media's Internet Archive collection; and MCM's Castus VOD platform, which is their primary publication and carries the boards and commissions -- Zoning Board of Appeals, Conservation, Historical, Board of Health, Community Preservation, Traffic and others -- that appear nowhere else. If there are sources missing, please let me know.

For the technically minded, you're welcome to use the source code for your own purposes (or to help me out). I tried to make it reasonably easy to follow, but it definitely takes some technical chops to get going. 

There's no reason this code, with minimial modifications, wouldn't work for other municipalities or even a much broader purpose that requires transcripts of youtube videos.

If you fork this repo with the intent of making your own page of searchable transcripts, see here for Search Engine Optimization (SEO) tips:
https://github.com/orgs/community/discussions/42375
https://www.bing.com/webmasters/tools/

---

# Setting it up

Two things are genuinely hard for a new operator: **getting a pyannote token**
(because it requires accepting model licences that are easy to miss) and
**getting LLM API keys** (because every provider splits "consumer subscription"
from "API billing" in a way that is not obvious). This section covers both.

**Everything goes in `credentials/`, which is gitignored.** Nothing here should
ever be committed. `utils.read_credential(name)` reads from `credentials/` and
nowhere else -- there is deliberately no repo-root fallback, because a secret
that can live in two places will eventually live in the wrong one, and the repo
root is where an absent-minded `git add -A` commits it.

```
credentials/
  hf_token.txt        required   HuggingFace -- diarization will not run without it
  claude_key.txt      optional   Anthropic, for summaries
  gemini_key.txt      optional   Google, for summaries
  openai_key.txt      optional   OpenAI, for summaries
  cookies.txt         optional   YouTube session, for age/region-gated videos
  google_service_account.json
                      optional   reads a PRIVATE corrections sheet
```

## 1. HuggingFace token (required — the pipeline will not diarize without it)

This is the one people get stuck on, because the token alone is not enough:
you must also accept the licence on **each** model, and the failure mode is a
confusing 401 deep inside pyannote rather than a clear message.

1. Create an account at <https://huggingface.co/join>.
2. Go to <https://huggingface.co/settings/tokens> → **New token** → type
   **Read**. Copy it.
3. **Accept the licence on both gated models**, while signed in:
   - <https://huggingface.co/pyannote/speaker-diarization-3.1>
   - <https://huggingface.co/pyannote/segmentation-3.0>

   Each shows a short form. Diarization fails without **both**, and the
   segmentation model is the one that is easy to miss because the code never
   names it.
4. Save the token to `credentials/hf_token.txt`.

Free, no card.

## 2. LLM API key (optional — only for `summarize_meeting.py`)

Summaries need exactly one of the three. Pick on cost and quality; the code
picks the provider from the model name, so there is no provider flag.

**Free tiers, precisely:**

| | free to start? | what it costs you |
|---|---|---|
| **Gemini** | **yes** -- no card, no balance | inputs used to improve Google's products |
| **OpenAI** | no -- see below | prompts + completions used for training |
| **Anthropic** | no free tier at all | -- |

Only Gemini is free *to start*. OpenAI's "free daily tokens" are generous once
unlocked -- up to 1M tokens/day on GPT-5/o-series/GPT-4.1 and 10M/day on
mini and nano -- but they are a rebate on a funded account, not a way in.
Enabling data sharing alone gets you `credit_balance_exhausted`, because the
programme also requires **Usage tier 1 (reached by paying $5) and a positive
balance**. Neither requirement is mentioned where you flip the switch.

Either free tier is acceptable for this project only because everything sent is
already published on the public site.

> **A consumer subscription is NOT API access.** Claude Pro, ChatGPT Plus and
> Google One AI Premium cover the chat websites. The APIs bill separately. This
> catches nearly everyone.

### Anthropic

1. <https://console.anthropic.com> → **API Keys** → *Create Key*. Copy it now;
   it is shown once.
2. **Billing** → add credit. No free tier; new accounts get ~$5 trial credit.
3. Save to `credentials/claude_key.txt`.

Spend is capped by your prepaid balance as long as auto-reload is off.

### Google Gemini

1. <https://aistudio.google.com/apikey> → **Create API key**.
2. **The project you choose decides whether you stay free.** A project with
   *no billing account* is free-tier, hard-capped at the daily limits, and
   cannot charge you. Choosing a billing-enabled project silently moves you to
   the paid tier. Create a fresh project if you want the guarantee.
3. Save to `credentials/gemini_key.txt`.

**The free tier is 20 requests per day, per model family.** Not 100, not 250 —
those were the `gemini-2.5` numbers, and 2.5 is now retired (the API answers
404 "no longer available to new users"). Measured 2026-09-25 by reading the
`quotaValue` Google attaches to the 429:

```
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
value:   20
dims:    {'model': 'gemini-3-flash', 'location': 'global'}
```

Three consequences, none of them obvious:

- **It is request-bound, not token-bound.** A two-token probe is refused
  exactly like a 46k-token transcript, so summary length costs nothing and
  the number of *calls* is the entire budget. Every wasted retry is 5% of a
  day's output, which is why `ask_gemini` retries 3 times and not 5.
- **The allowance is keyed on the model FAMILY** (note `dims`), so
  `-preview` and the released name share one bucket — you cannot get more by
  switching names. But *different* families have *separate* buckets, which is
  why `MODEL_LADDER` is a quota pool and not merely a fallback: walking two
  flash families gives ~40 requests a night where pinning one gives 20.
- **Pro-class is unavailable on the free tier**, not merely slow. It returns
  429 for a two-token request.

There are four quotas, and the `quotaId` says which one broke: requests and
input-tokens, each per-minute and per-day. Only the per-day ones are terminal;
the rest refill on their own. Google attaches a `retryDelay` even to the
per-day error, so the delay alone is not a signal — see `_retry_delay()`.

**Measured throughput: 36 summaries in 20 minutes**, on the first nightly run
(21 from `gemini-3-flash-preview`, 17 from `gemini-3.5-flash`). Against ~2,240
transcribed meetings that is about **two months** of nightly runs.

**Run it at night.** Not for the quota reset, which is a fixed daily allowance
whenever you spend it, but because congestion converts allowance into nothing:
every 503 is a request that buys no summary. The 3:05 AM run logged 5 retries
and **zero** 429s; a mid-afternoon attempt had every flash model returning 503
for minutes at a time and burned the budget on retries before producing
anything.

The trade: **Google uses free-tier inputs to improve its products.** That is
acceptable here only because every byte sent is already published on the public
site — transcript text and speaker names. Do not extend that reasoning to
`addresses.json`, the unreviewed correction queue, or voiceprints.

### OpenAI

1. <https://platform.openai.com/api-keys> → *Create new secret key*.
2. **Settings → Billing** → add credit (prepaid; $5 is plenty to evaluate).
3. Save to `credentials/openai_key.txt`.

**Limiting spend** — there is no single "spend limit" box, which is confusing.
Spend is bounded three ways, and the first is the one that matters:

- **Turn OFF auto-recharge** (Billing → Payment settings). Your prepaid balance
  then *is* the hard cap: when it runs out, calls fail. This is the real limit.
- **Usage limits** (Settings → Organization → Limits) set a monthly *budget*
  with a soft threshold that emails you and a hard threshold that stops calls.
- **Project budgets** cap individual projects if you use them.

**Free daily tokens** -- worth having, but they are not a free tier. Three
things must all be true, and the console tells you about only the first:

1. **Data sharing enabled** -- Settings → Data controls, and note it is set
   **per project**, so enabling it on the wrong project does nothing for a key
   belonging to another.
2. **Usage tier 1**, which you reach by having paid $5.
3. **A positive credit balance.** The free tokens do not draw from zero; with
   an empty balance every call returns `credit_balance_exhausted` no matter
   what the data-sharing toggle says.

Once all three hold: up to 1M tokens/day on GPT-5, o-series and GPT-4.1, and
10M/day on mini and nano models. Not available to Enterprise accounts or any
organization with Zero Data Retention.

### What a summary run costs

Measured over 2,232 transcripts (~78M input tokens; these transcripts are
token-dense at ~2.6 chars/token because of timestamps and numbers):

| model | whole backlog | batch API | ongoing ~10/month |
|---|---|---|---|
| Gemini free tier | **$0**, but ~2 months | — | **$0** |
| Claude Sonnet 5 | $174 | $87 | $0.78 |
| Claude Opus 5.5 | $348 | $174 | $1.56 |

**The dollar figures are not comparable across providers**, because the token
counts are not. The same meeting measured 47,749 input tokens on Anthropic,
36,326 on Gemini and 31,318 on OpenAI — the same text, three tokenisers. The
Anthropic column is ~50% higher than OpenAI's partly for that reason rather
than on price alone.

Ongoing cost is negligible on any of them — about ten meetings a month, which
the free tier absorbs comfortably. **The backlog is the only real decision**,
and it is now a time-versus-money one: free and two months, or paid and a day.

Worth weighing against a quality difference that is measured rather than
assumed. On one meeting with a human-written recap to check against, only
Opus 5.5 got all four checkable claims; the flash models named the presenter
and faithfully reported an ASR error, but dropped both enrolment figures. If
the summaries are going to serve as a retrieval index, that recall gap matters
more than prose quality, and spending on a prioritised subset may beat running
everything free.

## 3. YouTube cookies (optional)

Only needed for age- or region-gated videos:

```
yt-dlp --cookies-from-browser firefox --cookies credentials/cookies.txt
```

This is a live YouTube session token -- anyone holding it is signed in as you.
Never commit it, and regenerate it rather than copying it between machines.

## 4. Corrections (optional — the right-click "correct this line" form)

Transcripts contain errors, especially in speaker attribution, and the site
lets any reader right-click a line and submit a fix. That menu only appears if
`corrections-config.json` has a form behind it; without one the site works
normally and the menu is simply absent.

Nothing here is applied automatically. Submissions land in a local review
queue, and every accepted change becomes a public commit — a correction is
exactly as visible as the text it replaced. `TRUST.md` covers the trust model
in full; this is only the setup.

### 4a. The form

1. Create a Google Form with two questions — the corrected line, and an
   optional "who are you" / reference field.
2. **Do not enable "Collect email addresses → Verified."** Requiring a Google
   login to report a typo excludes exactly the people a civic archive exists
   to serve. The form stays open to anyone.
3. Link it to a responses spreadsheet (Responses → the Sheets icon).
4. Put the form's URL and its two `entry.NNNNN` field ids into
   `corrections-config.json`. To find the ids: open the live form, view
   source, and search for `entry.` — each question has one.

### 4b. Reading the responses

Two ways, and they differ only in how the CSV is fetched:

| | sheet sharing | credentials |
|---|---|---|
| `--url` | "anyone with the link can view" | none |
| `--sheet-id` | **Restricted (invite only)** | service-account key |
| `--csv` | anything | none — you download it by hand |

```
python ingest_corrections.py --url "https://docs.google.com/spreadsheets/d/<ID>/export?format=csv"
python ingest_corrections.py --sheet-id <ID>
python ingest_corrections.py --csv responses.csv
```

**Prefer the private sheet.** A link-shared responses sheet is an unmoderated
public text box at a stable URL, and it publishes two things people do not
expect: the free text anyone submits, and the contributor tokens that the
trusted-contributor whitelist depends on. While that sheet is readable, the
whitelist is only as strong as the secrecy of a URL.

Making the sheet private changes **nothing** for submitters — sheet sharing
and form sign-in are unrelated settings, and a private responses sheet with an
open form is the Google default.

### 4c. Service account, for a private sheet

The Sheets API needs a credential; there is no anonymous read of a restricted
sheet. Roughly five minutes:

1. <https://console.cloud.google.com> → **New Project**.

   > Consider a project SEPARATE from the one behind your Gemini key. The free
   > Gemini tier depends on that project having no billing account attached,
   > and keeping them apart means nothing you do here can affect summaries.
   > Enabling the Sheets API does not itself require billing.

2. **APIs & Services → Library** → "Google Sheets API" → **Enable**.
3. **IAM & Admin → Service Accounts → Create service account**. Skip the
   "grant access to project" step — project roles are irrelevant here.
4. Open the new account → **KEYS → Add key → Create new key → JSON**. It
   downloads once and cannot be re-downloaded; make a new key if you lose it.
5. Save it as `credentials/google_service_account.json` (gitignored).
6. **Share the sheet with the service account.** Copy `client_email` out of
   the JSON — it looks like `name@project.iam.gserviceaccount.com` — then open
   the sheet → **Share** → paste it → **Viewer** → untick "Notify people".

   This is the step people miss, and it is the one that actually grants
   access: project roles do not reach the sheet, only sharing does. Skipping
   it gives HTTP 403, and the error prints the address you need.

**Viewer, not Editor.** Ingest only reads, and the scope requested is
`spreadsheets.readonly`, so a leaked key exposes submissions rather than
allowing someone to alter or delete the submission record.

---

# Running it

```
python create_subtitles.py -c channels_to_transcribe.txt   # download + transcribe + publish
python create_subtitles.py -d                              # download audio only
python create_subtitles.py -t                              # transcribe only
python srt2html.py -i <yt_id>                              # rebuild one page
python summarize_meeting.py -i <yt_id>                     # one summary
python summarize_meeting.py --all                          # until the quota runs out
python summarize_meeting.py --list-models                  # what answers today
```

`--model` takes a PROVIDER name (`gemini`, `openai`, `anthropic`) as well as an
exact model id. Prefer the provider: the ladder then picks whichever model
actually answers, which is the whole point — the old hardcoded default is now a
404. Run `--list-models` first whenever summaries stop appearing; a silent
retirement shows up there as a ladder entry with no live match.

In production three Windows scheduled tasks run — "Download videos"
(`download.bat`, `-d`) and "Transcribe Videos" (`transcribe.bat`, `-t`), which
loop continuously, and "Summarize Meetings" (`summarize.bat`), which runs **once
nightly at 3:05 AM**. The summary job is bounded by a daily API allowance rather
than by CPU, so the useful unit of work is "spend today's quota, then stop"; it
detects the cap itself and exits cleanly instead of grinding through thousands
of meetings failing each one. It resumes the next night on its own, because each
summary is cached on the transcript SHA.

Killing the Python process restarts it on current code. It also restarts
*itself*: when a module it imported has been edited, it finishes the video in
flight, waits for the publish thread, and exits at the seam so the wrapper
reloads it. Site-wide files (`index.html`, the sitemap, the committee pages)
are held back until that happens, because regenerating them wholesale from
stale code would overwrite newer output.

## A note on how this repo is maintained

Most comments here explain **why** a thing is the way it is, usually by
recording the failure that caused it. A sample of what those comments are
about, because they set the expectation for changes:

- A hardcoded `year > 25` silently dropped every 2026 resolution for nine
  months. Nothing errored; the page simply stopped accepting new items.
- `download_mcm.add_metadata()` was never called, so no new Internet Archive
  item could ever be registered — it was assigned an id and then rejected for
  not already having one.
- A page generator opened its output with `"w"` and then did an hour of work,
  so any failure published a 0-byte page.
- Gemini reports `system_instruction` (snake_case) and `temperature` on a
  reasoning model as **HTTP 503 "experiencing high demand"**, which reads as
  capacity and is actually an unsupported field.

The through-line is that the expensive bugs here do not raise. They return
something plausible. Prefer code that fails loudly, and verify a claim against
the data before writing it down.
