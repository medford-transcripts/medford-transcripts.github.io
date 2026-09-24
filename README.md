This website posts AI-generated transcripts of youtube videos relevant to Medford, MA local politics, including but not limited to city council meetings, school committee meetings, subcommittee meetings, campaign videos, and local news reports.

The intent is to make it easier for the public to make informed decisions, advocate for their interests, and generally engage with these meetings and be an informed electorate.

The code to generate all open source (https://github.com/medford-transcripts/medford-transcripts.github.io). It uses yt_dlp to download the audio, then uses the AI-driven whisperX (https://arxiv.org/abs/2303.00747) to transcribe it and add speaker IDs. 

I've modified WhisperX to return the speaker embeddings, and use those embeddings to match speakers between videos. Generic IDs are propagated along with the YouTube ID for consistent naming, but are replaced with user input names should the speaker_ids.json file be edited manually.

The transcriptions contain many errors (particularly in the speaker identifications), and manual corrections to the SRT files are occasionally made. Corrections will be gladly accepted, and any controversial corrections will be flagged as such. Beginning on 1/15/2025, I began saving the word-level timestamps in model.pkl and that will need to be edited to make corrections.

Translations are currently DISABLED. The googletrans library broke in a way that was worse than useless: half the target languages raised errors and the other half silently returned the English text unchanged, so ~20,000 pages were being served as `lang="ar"` or `lang="km"` with English in them. Those pages are no longer tracked or published. Older pages from before the breakage were genuinely translated. The intended path forward is to translate the short meeting summaries rather than whole transcripts -- cheap, and spot-checkable.

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

Free tier is roughly 100 requests/day on Pro-class models and 250 on Flash,
with a 1M-token context. Ample for ongoing meetings; a full backlog run takes
days rather than hours because the **daily** cap binds, not tokens.

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
| Gemini free tier | **$0** | — | **$0** |
| Claude Sonnet 5 | $174 | $87 | $0.78 |
| Claude Opus 5.5 | $348 | $174 | $1.56 |

Ongoing cost is negligible on any of them. The backlog is the only real
decision.

## 3. YouTube cookies (optional)

Only needed for age- or region-gated videos:

```
yt-dlp --cookies-from-browser firefox --cookies credentials/cookies.txt
```

This is a live YouTube session token -- anyone holding it is signed in as you.
Never commit it, and regenerate it rather than copying it between machines.

---

# Running it

```
python create_subtitles.py -c channels_to_transcribe.txt   # download + transcribe + publish
python create_subtitles.py -d                              # download audio only
python create_subtitles.py -t                              # transcribe only
python srt2html.py -i <yt_id>                              # rebuild one page
python summarize_meeting.py -i <yt_id> --model <model>      # one summary
```

In production two Windows scheduled tasks run continuously — "Download videos"
(`download.bat`, `-d`) and "Transcribe Videos" (`transcribe.bat`, `-t`). Each
wrapper loops, so killing the Python process restarts it on current code.

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
