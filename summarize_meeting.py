"""
An agenda-structured executive summary for a meeting, with timestamped links.

WHY STRUCTURED JSON AND NOT PROSE. The same data feeds the page, the committee
indexes, and eventually JSON-LD; generating prose directly would mean parsing
it back out later. Rendering is srt2html's job.

WHERE THE AGENDA COMES FROM. Not the agenda PDF -- only 7% of meetings have one
matched (12% of City Council, ~0% of the boards). It comes from the transcript,
because the chair or clerk reads each item aloud as it is taken up:

    [SPEAKER_06]: 24-004, resolution to adopt standing committee rules...
    [SPEAKER_47]: 24-050 offered by Councilor Scarpelli.

So every meeting can be structured, not just the 7% with a published agenda,
and each item gets a real timestamp because every SRT block carries one.

WHAT IT DELIBERATELY DOES NOT DO:

  NO VOTE TALLIES. plan 8.3 requires cross-checking any tally against a
  deterministic roll-call extractor, and that extractor does not exist yet.
  Worse, roll-call votes are SHORT turns -- "Present", "Yes", "No" -- and
  short-turn speaker attribution measured 53-66% against a human reference,
  versus 97% on substantive speech. The most consequential thing a summary
  could say is the thing this pipeline is currently worst at. Outcomes are
  reported when stated plainly on the record ("the motion passes"); who voted
  which way is not.

  NO OPINION, NO FIRST PERSON. The recaps this format is modelled on are
  written by sitting committee members, who are entitled to a view. An archive
  is not.

  NO CLAIM BEYOND THE TRANSCRIPT. If it was not said, it does not appear.

TIMESTAMPS ARE VERIFIED, not trusted: any item whose citation falls outside the
meeting, or which the model returned without one, is dropped before writing.
A summary that links to the wrong moment is worse than one that does not link.

WHAT IT SUMMARISES FIRST. A free daily allowance makes ORDER the only lever
there is, so --all is tiered rather than date-sorted: meetings from the last
30 days, then whatever summary_priority.txt names (a meeting_type or an id, in
rank order), then the backlog newest-first. --plan shows the queue without
spending anything.

Usage:
    python summarize_meeting.py -i <yt_id> [--model claude-sonnet-5] [--dry-run]
    python summarize_meeting.py --all [--limit N]
    python summarize_meeting.py --plan 30          # the queue, no API calls
"""

import argparse
import datetime
import glob
import hashlib
import io
import json
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import requests

import srt_lines
import utils

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# A PROVIDER, NOT A MODEL. The default used to be "gemini-2.5-pro", which is
# now retired (404 "no longer available to new users"), so every run that did
# not pass --model silently produced nothing. Naming the provider and letting
# MODEL_LADDER + the live model list decide keeps working across retirements.
#
# Measured 2026-09-25, and the reason the ladder is ordered as it is:
#   3-flash-preview   OK
#   3.5-flash         503 transient capacity
#   2.5-flash         404 retired
#   3.1-pro-preview   429 even for a two-token request
#   pro-latest        429 (same model as 3.1-pro-preview)
# Pro-class is not merely throttled on this free tier, it is unavailable --
# worth knowing, because the backlog costing assumed 100 Pro requests/day.
DEFAULT_PROVIDER = "gemini"

# Two providers, because the economics differ in kind rather than degree.
# Anthropic has no free tier: the backlog costs $174 (Sonnet 5) to $348
# (Opus 5.5), halved on the Batch API. Gemini has a genuine free tier --
# Flash-class is the one actually reachable, and its allowance is the larger
# of the two -- which clears 2,232 meetings in days rather than weeks at zero
# cost.
#
# NEITHER is covered by a consumer subscription. Claude Pro covers claude.ai
# and Google One AI Premium covers gemini.google.com; both APIs are billed
# separately. The free tier is Gemini's API free tier, not the paid plan.
#
# WHAT THE FREE TIER COSTS INSTEAD: Google uses free-tier inputs to improve
# its products. That is normally disqualifying, and here it is not, because
# every byte of this prompt -- transcript text and resolved speaker names --
# is already published on the public site. Do not extend this to anything
# that is not: addresses.json, the unreviewed correction queue, voiceprints.
KEY_FILES = {
    # credentials/ only -- a secret that can live in two places eventually
    # lives in the wrong one.
    "anthropic": (os.path.join("credentials", "claude_key.txt"),),
    "gemini": (os.path.join("credentials", "gemini_key.txt"),),
    "openai": (os.path.join("credentials", "openai_key.txt"),),
}
ENV_VARS = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY"}


def provider_for(model):
    m = model.lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    return "anthropic"


def read_timeout(user, floor=600, cap=1800):
    """Seconds to wait, scaled to the size of what we are asking about.

    A FLAT 600s LOST THE LONGEST MEETINGS. A 4.5-hour joint Council/CDB
    session (~271k chars) hit the read timeout and produced nothing -- and
    that is not an outlier: 211 transcripts (9%) are that size or larger, the
    biggest 611k, against a median of 98k.

    WHY NOT SPLIT THE REQUEST IN TWO, which is the obvious alternative: every
    attempt costs quota, including the failed ones, and the free-tier
    allowance is 20 requests per model per day. Splitting doubles the cost of
    exactly the meetings that are hardest to summarise, and a split whose
    second half fails has spent two requests for nothing. Waiting longer costs
    nothing at all. Splitting stays the fallback if generous timeouts still
    fail, and it would need real work -- merging two item lists and
    synthesising one overview without double-counting.
    """
    return min(cap, floor + len(user or "") // 500)


# ---------------------------------------------------------------------------
# ADAPTIVE MODEL SELECTION
#
# A PINNED MODEL NAME IS A TIME BOMB. "gemini-2.5-pro" was the default in this
# file and is now 404 "no longer available to new users", so every run that
# did not pass --model failed -- and it failed the way things fail here, by
# quietly producing nothing rather than by complaining. Model names churn on a
# timescale of months; this archive runs for years.
#
# So the default is a PREFERENCE ORDER matched as PREFIXES against whatever
# the provider says it serves today, not a name. "gemini-3.1-pro" matches
# "gemini-3.1-pro-preview" without anyone editing this file when the preview
# suffix is dropped.
#
# THE ONE RULE: never downgrade silently. Falling from a Pro model to a nano
# one changes the product, and a reader cannot tell from the page. Every
# fallback prints, and the summary records what was asked for beside what
# actually answered.
# THE LADDER IS ALSO A QUOTA POOL, which is why the order is what it is and
# why nothing here should be collapsed to a single pinned model. The free-tier
# allowance is 20 requests/day keyed on the model FAMILY -- quotaDimensions
# says {'model': 'gemini-3-flash'} -- so the families have SEPARATE buckets and
# walking three of them is ~60 requests/day where pinning one is 20.
#
# Flash before Pro, against the usual instinct. Pro-class refuses even a
# two-token probe on this free tier, so putting it first spends real requests
# (5% of a day's output each) discovering that again every night. 3.5-flash is
# GA rather than -preview and produced the first summaries in the corpus;
# 3-flash-preview measured equivalent on the bakeoff -- 7 items each, both
# naming Fallon and both faithfully reporting the "Andrea" ASR error -- so it
# is a genuine second bucket, not a downgrade. Pro stays last rather than
# leaving, because the day this key gets billing it becomes the right choice
# and _WINNER will find it.
MODEL_LADDER = {
    # gemini-2.5-flash dropped 2026-09-28: it answers 404 "no longer
    # available to new users" on every call, and being last in the
    # ladder it is what the FAILED line reports -- so a meeting that
    # actually died of 503s and per-day caps was logged as a 404,
    # hiding the real cause.
    #
    # ONE ENTRY PER ENGINE, NOT PER NAME -- updated 2026-10-09 after Google's
    # "3.5 Flash is deprecated and auto-redirected" notice. The listing still
    # advertises the retired names, so the only way to tell an engine from an
    # alias is to ask and read modelVersion back. Measured:
    #
    #   gemini-3.5-flash       -> served by gemini-3.6-flash
    #   gemini-3.7-flash       -> served by gemini-3.8-flash
    #   gemini-3-flash-preview -> itself
    #
    # Three engines behind five names. The ladder is a QUOTA POOL, so listing
    # an alias beside its target would walk the SAME bucket twice while
    # looking like two -- which is the one assumption this design cannot
    # afford to get wrong. Hence 3.6 and 3.8 and no 3.5 or 3.7.
    #
    # 3.8 FIRST, ON THE PRIOR, which is Jason's call and the right reading of
    # the evidence we have. The bakeoff rubric is four binary claims on ONE
    # meeting: a TIE on it is weak evidence of equality, not evidence against
    # "the newer model in a family is usually better". Treating a coarse
    # measurement as decisive is its own error.
    #
    # So the order is the prior and compare_summaries.py is a VETO rather than
    # a gate: 3.8 keeps the lead unless it scores strictly WORSE than 3.6 on
    # the rubric. Cheap to unwind if it does -- every summary now records
    # which engine answered, so the ones to redo are a query, not a guess.
    #
    # Still worth remembering what the rubric showed: no Gemini flash model
    # has ever recovered the enrolment figures that Opus 5.5 gets. If those
    # numbers are the priority, the lever is the provider, not 3.6 vs 3.8.
    "gemini": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash",
               "gemini-3.1-pro", "gemini-3-pro"],
    "openai": ["gpt-5", "gpt-5-mini", "gpt-5-nano"],
    "anthropic": ["claude-opus-5-5", "claude-opus-5", "claude-sonnet-5",
                  "claude-haiku-4-5"],
}

MODELS_URL = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
}

_MODEL_CACHE = {}          # provider -> [ids], for one process
_DEAD = set()              # models that failed terminally in THIS process
_WINNER = {}               # provider -> the model that last actually answered
_CACHED = False            # did the last summarize() hit the cache?


def list_models(provider, key):
    """Model ids the provider says it serves, best-effort.

    Returns [] rather than raising: an unreachable listing endpoint must not
    stop a summary run that a pinned model would have completed.
    """
    if provider in _MODEL_CACHE:
        return _MODEL_CACHE[provider]
    ids = []
    try:
        if provider == "gemini":
            r = requests.get(MODELS_URL[provider], timeout=60,
                             params={"key": key, "pageSize": 200})
            ids = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                   if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        elif provider == "openai":
            r = requests.get(MODELS_URL[provider], timeout=60,
                             headers={"Authorization": "Bearer " + key})
            ids = [m["id"] for m in r.json().get("data", [])]
        else:
            r = requests.get(MODELS_URL[provider], timeout=60,
                             headers={"x-api-key": key,
                                      "anthropic-version": ANTHROPIC_VERSION})
            ids = [m["id"] for m in r.json().get("data", [])]
    except Exception as e:
        print("  could not list %s models (%s); falling back to the ladder as written"
              % (provider, str(e)[:70]))
    _MODEL_CACHE[provider] = ids
    return ids


def provider_of(spec):
    """Provider for a spec that may be a provider name OR a model id."""
    spec = (spec or DEFAULT_PROVIDER).strip()
    return spec if spec in MODEL_LADDER else provider_for(spec)


def candidates(spec, key=None):
    """Ordered model ids to try for `spec`.

    spec may be an exact model ("gemini-3-flash-preview"), a provider name
    ("gemini"), or None for the default provider. An exact name is honoured
    first and the rest of its provider's ladder follows it as fallback, so a
    retired pin degrades into a working run instead of a crash -- loudly.
    """
    spec = (spec or DEFAULT_PROVIDER).strip()
    provider = spec if spec in MODEL_LADDER else provider_for(spec)
    live = list_models(provider, key) if key else []

    out = []
    # WHAT ANSWERED LAST TIME GOES FIRST, and this is a quota decision rather
    # than a speed one. A failed ladder walk costs 16 requests for no output
    # (5 attempts each on three models, plus a 404) where a success costs 1 --
    # and on a metered free tier those rejections are the scarce resource, not
    # the wall clock. _DEAD already removes models that failed TERMINALLY, but
    # a 503 model is deliberately not blacklisted (capacity does come back),
    # so without this the ladder pays its 5-request 503 tax on every meeting
    # for a model that is congested all evening.
    if _WINNER.get(provider) and _WINNER[provider] not in _DEAD:
        out.append(_WINNER[provider])
    if spec not in MODEL_LADDER:
        out.append(spec)                       # an explicit request goes first
    for pref in MODEL_LADDER.get(provider, []):
        if live:
            # prefix match, so "gemini-3.1-pro" finds "...-preview". Shortest
            # match first: the plain id beats a -tts or -image variant.
            hits = sorted((m for m in live if m.startswith(pref)), key=len)
            hits = [m for m in hits
                    if not any(b in m for b in ("-tts", "-image", "-audio", "customtools"))]
            out.extend(hits[:1])
        else:
            out.append(pref)
    seen, ordered = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered


class ModelUnavailable(RuntimeError):
    """This model will not answer today; try the next one on the ladder."""


class DailyQuotaExhausted(RuntimeError):
    """Every model for this provider is out of DAILY allowance. Stop THIS RUN.

    "Daily" is Google's word, not a calendar day: the window rolls, so
    capacity returns through the day as earlier requests age out (measured
    2026-10-09 -- exhausted at 08:07 ET, answering freely at 23:30 ET with no
    reset in between). So this ends the RUN, not the night, and the hourly
    schedule is what turns that into throughput.

    Distinct from an ordinary failure on purpose. The --all loop treats a
    per-meeting error as "skip it and carry on", which is right for a bad
    transcript and catastrophic for an exhausted quota: it would walk the
    whole ladder for each of 2,232 remaining meetings, fail every one, and
    fill a log with activity while producing nothing. Hours of apparent work
    and no output is this codebase's signature failure; make it stop instead.
    """


def quota_violations(r):
    """[(quotaId, value)] for a 429. Google names exactly which limit broke.

    FOUR QUOTAS, NOT ONE, and they are worth telling apart because the fix
    differs. Observed ids, all -FreeTier:
        GenerateRequestsPerMinutePerProjectPerModel      RPM
        GenerateRequestsPerDayPerProjectPerModel         RPD
        GenerateContentInputTokensPerModelPerMinute      TPM
        GenerateContentInputTokensPerModelPerDay         TPD

    WHICH ONE BINDS HERE: measured 2026-09-25, gemini-3-flash violated ONLY
    RPD, with quotaValue 20. Twenty REQUESTS per day, and a two-token request
    is refused exactly like a 46k-token one -- so throughput is bounded by the
    number of calls, not their size, and every wasted retry costs 5% of the
    day's output. That is the opposite of the intuition that a token-metered
    tier would give, and it is why the retry policy matters more than prompt
    length.

    quotaDimensions also shows the limit is keyed on the model FAMILY
    ("gemini-3-flash"), not the exact id, so switching between -preview and
    the released name shares one allowance.
    """
    out = []
    try:
        details = r.json().get("error", {}).get("details", []) or []
    except ValueError:
        return out
    for d in details:
        if "QuotaFailure" not in (d.get("@type") or ""):
            continue
        for v in d.get("violations", []):
            out.append((v.get("quotaId") or "", v.get("quotaValue")))
    return out


def _per_day_quota(r):
    """True if this 429 is a per-DAY allowance rather than a short window."""
    return any("perday" in q.lower() for q, _ in quota_violations(r))


def _quota_note(r):
    """Human-readable 'which limit, and what is it' for a log line."""
    bits = []
    for q, val in quota_violations(r):
        ql = q.lower()
        kind = ("daily requests" if "requestsperday" in ql else
                "daily input tokens" if "tokens" in ql and "perday" in ql else
                "requests/min" if "requestsperminute" in ql else
                "input tokens/min" if "tokens" in ql else q)
        bits.append("%s%s" % (kind, "" if val in (None, "") else "=%s" % val))
    return ", ".join(bits) or "unspecified quota"


def _terminal_for_model(status, body):
    """Is this a 'give up on THIS model' error rather than a retryable one?

    404 = retired or misspelled. 429 that survived ask_gemini's own backoff =
    a quota that does not refill in a useful window. 503 that survived its
    retries = capacity that is not coming back promptly. All three mean move
    on; none of them mean the run is over.
    """
    return status in (404, 429, 503) or "not_found" in (body or "").lower()
# Generous ON PURPOSE. max_tokens is a guillotine, not a brief: at 2000 the
# model simply stopped mid-JSON and the reply failed to parse. Brevity is the
# prompt's job; this only has to be large enough that a well-behaved reply is
# never cut off. A 500-word summary plus JSON structure is ~1.5k tokens.
MAX_OUTPUT = 6000

SYSTEM = """You summarise transcripts of Medford, Massachusetts public meetings \
for a civic archive. The archive publishes the full transcript beside your \
summary, so readers can always check you.

Produce the agenda as it was actually taken up, in order, from what is said in \
the transcript. The chair or clerk normally announces each item as it begins.

Rules you must not break:
- Use ONLY what is in the transcript. Never infer, never supply background.
- Do not report who voted which way, and do not give vote tallies. You may \
state an outcome only if it is said plainly on the record (e.g. "the motion \
passes", "approved", "tabled", "referred to committee").
- No opinion, no recommendations, no first person. Neutral register.
- Name a speaker only when the transcript makes the attribution clear.
- BE CONCISE. This is the hard requirement. ONE sentence per item; a second \
only when the outcome genuinely needs it. The whole summary should read in \
under a minute -- roughly 250 to 500 words including the overview. Human \
recaps of these meetings run 900 to 2,000 words; yours should be a quarter \
of that, because it sits ABOVE the full transcript rather than replacing it.
- The length target is a target, not a cap. Go longer where a topic is \
genuinely consequential or contested -- a major zoning change, a budget \
decision, an ordinance with substantial public comment. Spend the extra \
sentences THERE and take them back from the routine items. Never pad \
something uncontested to reach a length.
- Lead with the decision, not the discussion. "Approved X." "Tabled Y \
because the petitioner was not present." "Referred Z to the Community \
Development Board." The detail is in the transcript underneath.
- Merge routine items. Consent agendas, licence approvals and ceremonial \
recognitions share one line unless something was contested.
- Omit procedure that carries no information: roll calls, motions to \
adjourn, recesses, and who seconded what.
- Every item needs the start time in SECONDS, taken from the [NNNN] marker at \
the start of the line where that item begins.

SUBJECT. Also return a subject line naming the ONE matter this meeting will be \
remembered for -- "Salem Street Corridor Rezoning", "Police Union Wage \
Agreement", "Elementary School Overcrowding". Rules:
- At most about eight words. A noun phrase, not a sentence: no verb, no \
trailing full stop, no date, and do not name the body -- the page already \
says which committee met and when.
- TITLE CASE: "Salem Street Corridor Rezoning", not "Salem street corridor \
rezoning". Keep acronyms exactly as spoken on the record -- ICE, CDBG, MCAS, \
ADA, MSBA, CPA -- and keep short joining words lowercase ("Rules of Order").
- RETURN AN EMPTY STRING when no single matter dominates. A regular council \
meeting that moved licences, a resolution, a wage agreement and an ordinance \
has no one subject, and guessing at one tells a reader this meeting was about \
something it was not. An empty string is the correct answer more often than \
not, and it costs nothing -- the city's own title is used instead.
- Never use a procedural heading as the subject: not "Consent Agenda", \
"Approval of Minutes", "Executive Session", "Reports of Committees" or \
"Public Participation". If that is all the meeting did, return an empty string.

Return ONLY valid JSON, no prose around it:
{"subject": "the one matter, <=8 words, or an empty string",
 "overview": "1-2 sentences: what this body met about and what it decided",
 "items": [{"title": "short agenda-style title",
            "t": <seconds, integer>,
            "summary": "ONE sentence, two at most",
            "speakers": ["names actually identified in the transcript"]}]}"""


def api_key(provider="anthropic"):
    for f in KEY_FILES[provider]:
        if os.path.exists(f):
            k = io.open(f, encoding="utf-8").read().strip()
            if k:
                return k
    k = os.environ.get(ENV_VARS[provider], "").strip()
    if k:
        return k
    raise SystemExit(
        "No %s key. Put it in %s (that directory is already gitignored) "
        "or set %s." % (provider, KEY_FILES[provider][0], ENV_VARS[provider]))


def printable(s):
    """Text that cannot crash a print on this console.

    ONE title in 2,261 is outside cp1252 (`gT4_C1uPttA`, 2025-09-27), which is
    what a Windows console and the redirected .bat logs encode in -- and the
    traceback is raised by print, so it would have killed the whole nightly
    run on reaching that one meeting rather than skipping it. Titles come
    from the city verbatim (PRINCIPLES #6) and the next import can add
    another, so the fix belongs at the output, not in the data.
    """
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    return str(s).encode(enc, "replace").decode(enc, "replace")


def transcript_dir(yt_id, video_data=None):
    video_data = video_data or utils.get_video_data()
    e = video_data.get(yt_id)
    if not e:
        return None, None
    base = (e.get("upload_date") or "") + "_" + yt_id
    srt = os.path.join(base, base + ".srt")
    return (base, srt) if os.path.exists(srt) else (base, None)


def timed_transcript(srt_path, names=None):
    """One line per block, prefixed with its start second.

    The [NNNN] marker is what lets the model cite a real timestamp, and what
    lets us verify the citation afterwards.
    """
    blocks = srt_lines.parse_srt(
        io.open(srt_path, encoding="utf-8", errors="replace").read())
    out = []
    for b in blocks:
        spk = b.get("speaker")
        who = (names or {}).get(spk, spk) or "?"
        text = re.sub(r"^\[[^\]]*\]:\s*", "", b.get("text") or "").strip()
        if text:
            out.append("[%d] %s: %s" % (int(b.get("start") or 0), who, text))
    return "\n".join(out), (blocks[-1].get("end") if blocks else 0)


def ask_anthropic(model, system, user, key, max_tokens=MAX_OUTPUT):
    r = requests.post(ANTHROPIC_URL, timeout=read_timeout(user),
                      headers={"x-api-key": key,
                               "anthropic-version": ANTHROPIC_VERSION,
                               "content-type": "application/json"},
                      json={"model": model, "max_tokens": max_tokens,
                            "system": system,
                            "messages": [{"role": "user", "content": user}]})
    if r.status_code != 200:
        raise RuntimeError("anthropic %s: %s" % (r.status_code, r.text[:300]))
    d = r.json()
    parts = [c.get("text", "") for c in d.get("content", []) if c.get("type") == "text"]
    u = d.get("usage", {})
    return "".join(parts), {"input_tokens": u.get("input_tokens"),
                            "output_tokens": u.get("output_tokens"),
                            # see _gemini_parse: record what ANSWERED
                            "model_version": d.get("model")}


# ------------------------------------------------------- transient retry budget
#
# A 503 COSTS A TOKEN. Measured over 29 runs: 109 successes against 54 503s and
# 85 per-day 429s. The two failures are not alike --
#   * a per-day 429 is refused at the gate, against a bucket that is already
#     empty, so it costs wall-clock and nothing else;
#   * a 503 got PAST the gate. It spent a request and returned nothing.
# The evidence is that total requests per post-reset run stayed near constant
# (41, 26, 33) while successes swung 36 -> 21 -> 12, inversely with the 503
# count. The bucket meters requests, not successes.
#
# So retrying a 503 three times spends three tokens to maybe buy one summary.
# With refill around 2/hour, a token given away now is not replaced for half an
# hour; the next hourly run would have spent it on a meeting that succeeds.
# Bail on the first 503 and let the next run try -- it is an hour away, and
# 503s clump (the 2026-09-28 03:05 run opened at 75% failure in its first
# quarter and never recovered, while 2026-09-26 had its 503s in the middle and
# then ran clean).
#
# THE ONE EXCEPTION is a full bucket, where the arithmetic inverts. Tokens that
# would overflow before the next run are free, so spending them on retries
# costs nothing. The bucket is only full right after the daily reset at
# midnight Pacific -- which is exactly the 03:05 Eastern run -- so that run,
# and only that run, gets the old budget of 3.
# BAIL ON THE FIRST 503. Reverted to 3 earlier today and back again, so the
# reasoning is worth writing down properly.
#
# THE ARGUMENT FOR RETRYING was that unused quota expires at midnight Pacific,
# so there is nothing to save it for. That is WRONG here: it only holds if the
# day would otherwise end with quota unspent. It does not. The backlog is
# 2,105 meetings against 20-60 requests a day, so demand exceeds supply
# permanently -- every token WILL be spent, and the only question is where.
#
# And where matters, because contention varies a great deal. Measured:
#     Sat  36 summaries, 12% 503      Sun  57 at 25%      Mon  16 at 67%
# A token spent into a 67% window buys a third of what it buys at the weekend.
# Retrying three times into a bad hour converts quota that could have produced
# a summary at a quieter one into nothing at all.
#
# This is the same policy the consecutive_failures guard in main() already
# implements ("this run stops rather than spending the day's allowance on a bad
# window") -- a budget of 3 simply burns three times as much before that guard
# can trip.
#
# WHAT MISLED ME: zero summaries in the eight runs after the bail-out shipped.
# But Monday was already producing zero by 08:05, BEFORE the change landed --
# all 16 of the day's successes came from the 03:05-07:05 runs. The drought was
# weekday contention, not the budget. A before/after comparison that straddles
# a weekend boundary cannot separate the two.
TRANSIENT_ATTEMPTS = 1
RUN_STATE = os.path.join("logs", "summary_run_state.json")


def _last_quota_reset(now=None):
    """The most recent midnight Pacific.

    Computed from the tz database, never from a fixed offset, so it is correct
    on a machine in any timezone and moves with DST on its own.

    MEASURED, from our own logs rather than the docs: on 2026-09-28 the run at
    00:05 UTC produced 1 summary while the run at 00:05 PDT produced 12, after
    four consecutive zero runs at 20:05/21:05/22:05/23:05 PDT. All three daily
    bursts (36, 21, 12) land at 00:05 PDT. So the reset is Pacific, not UTC.

    WHAT IS *NOT* MEASURED: whether Google follows the Pacific WALL CLOCK or
    simply pins to UTC-8 all year. Every log we have is from September, which
    is PDT, and both hypotheses predict a 07:00 UTC reset in PDT -- they differ
    only under PST, where wall clock means 08:00 UTC. This function assumes the
    wall clock. If that is wrong the cost is small and self-limiting: for the
    four winter months the elevated retry budget below would be handed to the
    23:05 PST run instead of the 00:05 PST one, wasting about two requests a
    day. Re-run the same log analysis after DST ends to settle it.
    """
    pac = ZoneInfo("America/Los_Angeles")
    now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(pac)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def transient_budget(now=None):
    """How many times to retry a 503, and record that this run happened.

    3 for the first run after the daily reset (the bucket is full, so retries
    spend capacity that would otherwise overflow), 1 for every run after it.
    Falls back to 1 -- the cautious value -- if the state file is unreadable,
    because over-spending a scarce bucket is the expensive mistake.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    reset = _last_quota_reset(now)
    first = True
    try:
        with io.open(RUN_STATE, encoding="utf-8") as f:
            prev = json.load(f).get("last_run")
        if prev:
            first = datetime.datetime.fromisoformat(prev) < reset
    except (IOError, OSError, ValueError, KeyError):
        first = False           # unknown: assume the bucket is NOT full
    try:
        os.makedirs(os.path.dirname(RUN_STATE) or ".", exist_ok=True)
        utils.write_atomic(RUN_STATE,
                           json.dumps({"last_run": now.isoformat()}, indent=1))
    except (IOError, OSError):
        pass                    # advisory only; never fail a run over it
    # 3 only on the first run after the reset, when the bucket is full and
    # tokens would otherwise overflow before the next run -- the one case
    # where spending them on retries costs nothing. 1 otherwise: see
    # TRANSIENT_ATTEMPTS for why saving them for a quieter hour beats
    # retrying into a busy one.
    return 3 if first else 1


def ask_gemini(model, system, user, key, max_tokens=MAX_OUTPUT, attempts=3,
               transient_attempts=None):
    """responseMimeType forces valid JSON, so no code fence to strip.

    RETRIES ON 5xx. Gemini's free tier returns "experiencing high demand"
    unpredictably -- measured on one meeting: 5% of the transcript succeeded,
    25% and 50% failed, and the FULL 46k-token request succeeded, all within a
    minute. It is not size, not the request shape, and not the daily quota.
    It is capacity, and the only answer is to ask again.

    AND ON A RATE-LIMIT 429, WHICH IS NOT THE SAME AS THE DAILY CAP. This
    function used to treat every 429 as terminal, on the assumption that a 429
    meant the daily quota was gone. The free tier has FOUR separate quotas --
    requests per day, requests per minute, input tokens per day, input tokens
    per minute -- and three of them refill on their own. Google says which by
    attaching RetryInfo: a per-minute limit comes back with a short retryDelay
    (17s, measured), the daily cap comes back with none. Honour the delay it
    gives and only give up when there is no delay to wait for, otherwise a
    backlog run dies on the first busy minute.
    """
    tbudget = TRANSIENT_ATTEMPTS if transient_attempts is None else transient_attempts
    transient_seen = 0
    for attempt in range(attempts):
        r = _gemini_call(model, system, user, key, max_tokens)
        if r.status_code in (500, 502, 503, 504):
            transient_seen += 1
            if transient_seen >= tbudget or attempt == attempts - 1:
                break
            wait = 5 * (2 ** attempt)
            print("    gemini %s (transient); retrying in %ds" % (r.status_code, wait))
            time.sleep(wait)
            continue
        if r.status_code == 429:
            wait = _retry_delay(r)
            if wait is None or attempt == attempts - 1:
                break               # daily cap, or out of attempts
            print("    gemini 429 (rate limit); retrying in %ds" % wait)
            time.sleep(wait)
            continue
        break
    if r.status_code == 429 and _per_day_quota(r):
        # "PER-DAY" IS A ROLLING WINDOW, NOT A CALENDAR DAY, so do not tell the
        # operator to come back at midnight. Measured 2026-10-09: every gemini
        # model reported its daily allowance gone at 08:07 ET, and at 23:30 ET
        # -- the SAME quota day Pacific, no reset in between -- 3.6 and 3.8
        # both answered a dozen requests. Capacity returns continuously as
        # earlier requests age out of the window.
        #
        # This also explains the bursts _last_quota_reset was built on
        # (36, 21, 12 all landing at 00:05 PDT) WITHOUT a calendar reset: if
        # the allowance is spent in one burst, it refills ~24h after that
        # burst, so heavy use at 00:05 makes the next opening appear at 00:05.
        # Self-reinforcing, and indistinguishable from a daily reset unless
        # you try at another hour -- which is what happened tonight.
        raise DailyQuotaExhausted(
            "%s: %s exhausted (refills continuously; retry later today)"
            % (model, _quota_note(r)))
    return _gemini_parse(r)


def _retry_delay(r, cap=120):
    """Seconds Google asks us to wait, or None if waiting cannot help.

    THE retryDelay ALONE IS A TRAP. Google attaches RetryInfo even to a
    PER-DAY quota error -- measured: GenerateRequestsPerDayPerProjectPerModel
    came back with "retryDelay: 50s", and no amount of waiting 50 seconds
    restores a daily allowance that resets at midnight Pacific. Honouring it
    blindly costs the full backoff (~4 minutes) on EVERY meeting of a backlog
    run, for a model that cannot answer until tomorrow.

    So the QuotaFailure violation decides, and RetryInfo only supplies the
    number: a quotaId naming a per-day limit is terminal, everything else is
    a short window worth waiting out.

    WHY attempts DEFAULTS TO 3 AND NOT 5. The measured daily allowance is 20
    REQUESTS per model (quotaValue on GenerateRequestsPerDayPerProjectPerModel),
    so every attempt spends 5% of a day's output whether it succeeds or not.
    Five attempts on one congested model was a quarter of the day for a single
    meeting that might still fail. The retry budget is the throughput budget.
    """
    try:
        details = r.json().get("error", {}).get("details", []) or []
    except ValueError:
        return None
    delay = None
    for d in details:
        t = d.get("@type") or ""
        if "QuotaFailure" in t:
            for v in d.get("violations", []):
                if "perday" in (v.get("quotaId") or "").lower():
                    return None          # resets at midnight, not in 50s
        elif "RetryInfo" in t:
            raw = str(d.get("retryDelay") or "").rstrip("s")
            try:
                delay = min(max(int(float(raw)), 1), cap)
            except ValueError:
                delay = None
    return delay


def _gemini_call(model, system, user, key, max_tokens):
    return requests.post(GEMINI_URL % model, timeout=read_timeout(user),
                      params={"key": key},
                      headers={"content-type": "application/json"},
                      # camelCase, and NO temperature. Both matter: the v1beta
                      # endpoint answers snake_case "system_instruction" and any
                      # "temperature" on a 3.x reasoning model with HTTP 503
                      # "experiencing high demand" -- which reads like capacity
                      # and is actually an unsupported field. Cost an hour.
                      json={"systemInstruction": {"parts": [{"text": system}]},
                            "contents": [{"parts": [{"text": user}]}],
                            "generationConfig": {
                                # Gemini 3.x spends THINKING tokens from this
                                # same budget before emitting anything, so a
                                # budget sized for the answer returns
                                # finishReason=MAX_TOKENS with empty content.
                                # Give it room; the prompt controls length.
                                "maxOutputTokens": max(max_tokens, 32000),
                                "responseMimeType": "application/json"}})


def _gemini_parse(r):
    if r.status_code != 200:
        raise RuntimeError("gemini %s: %s" % (r.status_code, r.text[:300]))
    d = r.json()
    cands = d.get("candidates") or []
    if not cands:
        raise RuntimeError("gemini returned no candidates: %s" % json.dumps(d)[:240])
    why = cands[0].get("finishReason")
    if why and why not in ("STOP", "MAX_TOKENS"):
        # SAFETY / RECITATION / OTHER -- say so rather than writing a partial
        raise RuntimeError("gemini stopped early: %s" % why)
    text = "".join(pt.get("text", "")
                   for pt in (cands[0].get("content", {}).get("parts") or []))
    if not text.strip():
        raise RuntimeError(
            "gemini returned no text (finishReason=%s). On 3.x this usually "
            "means thinking consumed maxOutputTokens." % why)
    u = d.get("usageMetadata", {})
    # modelVersion IS WHAT ANSWERED, and it is not always what was asked for.
    # Measured 2026-10-09, after Google's deprecation notice: a request for
    # gemini-3.5-flash is served by gemini-3.6-flash, and one for
    # gemini-3.7-flash by gemini-3.8-flash -- silently, HTTP 200, no warning
    # in the body. Recording the REQUESTED id made every summary since the
    # redirect name an author that did not write it, on the page banner, which
    # is a claim in our own voice about provenance (PRINCIPLES #5).
    return text, {"input_tokens": u.get("promptTokenCount"),
                  "output_tokens": u.get("candidatesTokenCount"),
                  "model_version": d.get("modelVersion")}


def ask_openai(model, system, user, key, max_tokens=MAX_OUTPUT):
    """Chat Completions.

    Two shapes exist and the split is by model generation, not by endpoint:
    reasoning models take max_completion_tokens and REJECT temperature, older
    ones take max_tokens. Rather than hardcode which is which -- a list that
    goes stale, as claude-sonnet-5 and gemini-2.5-pro both did within a week --
    try the modern shape and fall back on the specific complaint.
    """
    def call(body):
        return requests.post(OPENAI_URL, timeout=read_timeout(user),
                             headers={"Authorization": "Bearer " + key,
                                      "content-type": "application/json"},
                             json=body)

    body = {"model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_completion_tokens": max(max_tokens, 32000),
            "response_format": {"type": "json_object"}}
    r = call(body)
    if r.status_code == 400 and "max_completion_tokens" in r.text:
        body.pop("max_completion_tokens")
        body["max_tokens"] = max_tokens
        r = call(body)
    if r.status_code != 200:
        raise RuntimeError("openai %s: %s" % (r.status_code, r.text[:300]))
    d = r.json()
    ch = (d.get("choices") or [{}])[0]
    why = ch.get("finish_reason")
    text = (ch.get("message") or {}).get("content") or ""
    if not text.strip():
        raise RuntimeError("openai returned no text (finish_reason=%s); on a "
                           "reasoning model this usually means the token "
                           "budget went on reasoning" % why)
    u = d.get("usage", {})
    return text, {"input_tokens": u.get("prompt_tokens"),
                  "output_tokens": u.get("completion_tokens"),
                  # see _gemini_parse: record what ANSWERED
                  "model_version": d.get("model")}


def ask_one(model, system, user, key, max_tokens=MAX_OUTPUT):
    p = provider_for(model)
    if p == "openai":
        return ask_openai(model, system, user, key, max_tokens)
    if p == "gemini":
        return ask_gemini(model, system, user, key, max_tokens)
    return ask_anthropic(model, system, user, key, max_tokens)


def ask(spec, system, user, key, max_tokens=MAX_OUTPUT):
    """Ask the best model that will actually answer. Returns (text, usage, model).

    Walks the ladder from candidates(). A model that is retired, out of quota
    or persistently at capacity is skipped -- AUDIBLY, because dropping from a
    Pro model to a nano one changes the summary and the reader cannot tell.
    The caller records which model answered.

    Raises the LAST error when every candidate fails, rather than a synthetic
    "all models failed": the real 404 or 429 text is what tells you why.
    """
    tried, last, capped, transient = [], None, [], []
    for model in candidates(spec, key):
        # A model that already failed terminally this run is not retried. On
        # --all over 2,232 meetings the first candidate can be one whose daily
        # quota is gone; without this, every meeting pays its full retry
        # backoff (~3 minutes at a 40s retryDelay) before falling through to
        # the model that was always going to answer.
        if model in _DEAD:
            continue
        try:
            text, usage = ask_one(model, system, user, key, max_tokens)
            if tried:
                print("  NOTE: fell back to %s after %s" % (model, ", ".join(tried)))
            # _WINNER keeps the REQUESTED id, because that is what the next
            # call has to put in a URL -- an alias is a valid thing to ask
            # for, and resolving it ourselves would pin us to whatever it
            # happens to point at today.
            _WINNER[provider_of(spec)] = model
            # But what we REPORT is what answered. A provider may redirect an
            # alias silently (gemini-3.5-flash -> gemini-3.6-flash, measured
            # 2026-10-09), and this file's standing rule is that a model
            # substitution is never silent: it changes the summary and a
            # reader cannot tell from the page.
            served = usage.get("model_version") or model
            if served != model:
                print("  NOTE: %s is served by %s" % (model, served))
            return text, usage, served
        except DailyQuotaExhausted as e:
            print("  %s: daily allowance gone; trying the next model" % model)
            _DEAD.add(model)
            capped.append(model)
            tried.append("%s(day)" % model)
            last = e
            continue
        except RuntimeError as e:
            msg = str(e)
            m = re.search(r"\b(\d{3})\b", msg[:60])
            status = int(m.group(1)) if m else 0
            if not _terminal_for_model(status, msg):
                raise
            print("  %s unavailable (%s); trying the next model"
                  % (model, (str(status) if status else msg[:40])))
            # 503 is capacity and can clear within the minute, so that model
            # stays in the running for the next meeting. 404 (retired) and 429
            # (quota that outlived its own backoff) will not change today.
            if status in (404, 429):
                _DEAD.add(model)
            if status == 503:
                # capacity, not allowance: this model may well answer for
                # the next meeting, so it must not end the run
                transient.append(model)
            tried.append("%s(%s)" % (model, status or "err"))
            last = e
    # STOP ONLY IF NOTHING CAN RECOVER, which is not the same as "something
    # was capped". Measured on the second nightly run: gemini-3.5-flash had
    # genuinely spent its 20 and was blacklisted, gemini-3.1-pro was capped,
    # 2.5-flash is retired -- but gemini-3-flash-preview failed with a 503,
    # having produced only 2 summaries and so holding ~18 requests still. The
    # old test raised on `capped` alone, so one momentary capacity blip on the
    # model that still had budget ended the whole run: 20 summaries that night
    # against 36 the night before.
    #
    # A 503 means try again, so it is a reason to move to the next MEETING,
    # not to abandon the night. Only when every candidate is permanently out
    # -- per-day capped, or retired -- is there nothing left to do.
    if capped and not transient:
        raise DailyQuotaExhausted(
            "all %s models are out of daily allowance (%s)"
            % (provider_of(spec), ", ".join(capped)))
    raise last or RuntimeError("no model configured for %r" % spec)


def parse_json(text):
    """The model is told to return bare JSON; tolerate a code fence anyway."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in the reply")
    return json.loads(t[i:j + 1])


# A subject line only earns its place if it says something the page does not
# already say. Procedural headings are the main way a model fills the field
# when it should have declined: "Consent Agenda" is true of most meetings and
# tells a reader nothing about this one.
SUBJECT_BOILERPLATE = re.compile(
    r"^\W*(consent agenda|approval of (the )?minutes|minutes|roll call|"
    r"call to order|executive session|open session|reports? of committees|"
    r"public (participation|comment)|announcements|adjournment|"
    r"regular meeting|special meeting|committee of the whole|"
    r"meeting records[\w\s]*|routine[\w\s]*|approval of invoices|"
    r"general business|old business|new business|miscellaneous)\W*$", re.I)
SUBJECT_MAX_WORDS = 12
SUBJECT_MAX_CHARS = 80


def clean_subject(raw, meeting_type="", source_title=""):
    """The subject line, or "" when it does not earn its place.

    RETURNS "" RATHER THAN A BEST EFFORT, because the fallback -- the city's
    own title -- is always available and always defensible. A wrong subject is
    worse than no subject: it is our sentence, in our voice, telling a reader
    what a public meeting was about.

    Rejected: procedural headings, anything sentence-shaped, anything that just
    restates the body's own name, and anything long enough to be prose.
    """
    s = re.sub(r"\s+", " ", (raw or "")).strip().strip('"').strip()
    s = re.sub(r"\s*[.;,]+$", "", s)
    if not s:
        return ""
    if len(s) > SUBJECT_MAX_CHARS or len(s.split()) > SUBJECT_MAX_WORDS:
        return ""
    if SUBJECT_BOILERPLATE.match(s):
        return ""
    # just the body again, e.g. "School Committee" under MPS School Committee
    body = set(re.findall(r"[a-z]{3,}", (meeting_type or "").lower()))
    words = set(re.findall(r"[a-z]{3,}", s.lower()))
    if words and words <= body | {"medford", "city", "meeting", "committee",
                                  "commission", "board", "council", "regular",
                                  "special", "subcommittee", "session"}:
        return ""
    return s


def self_test_subject():
    """Literal assertions for clean_subject and the display-title fallback.

    Every case below is a way the field can be filled when it should have been
    declined, taken from what the summaries on disk actually contain: 49 of 246
    have a procedural heading as their FIRST item, which is exactly what a model
    reaches for when no single matter dominates.
    """
    import utils
    fails = []

    def ck(label, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (label, got, want))

    ck("real subject kept",
       clean_subject("Salem Street Corridor Rezoning", "CC City Council"),
       "Salem Street Corridor Rezoning")
    ck("empty stays empty", clean_subject("", "CC City Council"), "")
    ck("None stays empty", clean_subject(None, "CC City Council"), "")
    ck("consent agenda rejected",
       clean_subject("Consent Agenda", "MPS School Committee"), "")
    ck("approval of minutes rejected",
       clean_subject("Approval of Minutes", "CC City Council"), "")
    ck("executive session rejected",
       clean_subject("Executive Session", "MPS School Committee"), "")
    ck("procedural prose rejected",
       clean_subject("Meeting Records and Routine Procedural Matters",
                     "CC City Council"), "")
    ck("body name alone rejected",
       clean_subject("School Committee", "MPS School Committee"), "")
    ck("body plus generic words rejected",
       clean_subject("Medford City Council Regular Meeting", "CC City Council"), "")
    ck("a sentence is not a title",
       clean_subject("The committee discussed a list of copy edits and formatting "
                     "updates regarding dwellings", "CC City Council"), "")
    ck("trailing stop stripped",
       clean_subject("Police Union Wage Agreement.", "CC City Council"),
       "Police Union Wage Agreement")
    ck("quotes stripped",
       clean_subject('"Elementary School Overcrowding"', "MPS School Committee"),
       "Elementary School Overcrowding")

    base = {"title": "City Council 12-02-25", "meeting_type": "CC City Council",
            "date": "2025-12-02", "upload_date": "2025-12-03"}
    ck("composed when subject, body and a real date are all present",
       utils.display_title("x", dict(base), subject="Salem Street Corridor Rezoning"),
       "City Council: Salem Street Corridor Rezoning - 2025-12-02")
    ck("no subject falls back to the city's title",
       utils.display_title("x", dict(base), subject=""), "City Council 12-02-25")
    # 6% of committee titles carry no date, so entry["date"] IS the upload date.
    # Printing it as the meeting date would be our error, not the city's.
    nodate = {"title": "MCHSBC Full Committee Meeting",
              "meeting_type": "MPS High School Building Committee",
              "date": "2026-08-25", "upload_date": "2026-08-25"}
    ck("a guessed date falls back",
       utils.display_title("x", dict(nodate), subject="Feasibility Study Contract"),
       "MCHSBC Full Committee Meeting")
    # "MCHSBC", not "High School Building Committee": meeting_types.json sets
    # an explicit label for this body, which body_label honours over the
    # prefix-stripped type -- the same choice as COW, and for the same reason
    # (the composed titles were running to 118 characters). The expectation
    # here predated that label and had been reporting FAIL on every run.
    ck("a hand-set date is trusted",
       utils.display_title("x", dict(nodate, date_manual=True),
                           subject="Feasibility Study Contract"),
       "MCHSBC: Feasibility Study Contract - 2026-08-25")
    ck("no meeting_type falls back",
       utils.display_title("x", {"title": "Medford Happenings - Laura O'Neil",
                                 "meeting_type": "", "date": "2024-01-02",
                                 "upload_date": "2024-01-02"},
                           subject="Something"),
       "Medford Happenings - Laura O'Neil")
    ck("routing prefix stripped", utils.body_label("CC City Council"), "City Council")

    for f in fails:
        print("  FAIL %s" % f)
    print("subject self-test: %d checks, %d failed" % (18, len(fails)))
    return 1 if fails else 0


def verify(summary, duration):
    """Drop items whose timestamp cannot be real. Returns (kept, dropped)."""
    kept, dropped = [], []
    for it in summary.get("items") or []:
        t = it.get("t")
        try:
            t = int(float(t))
        except (TypeError, ValueError):
            dropped.append((it, "no timestamp"))
            continue
        if not (0 <= t <= (duration or 0) + 60):
            dropped.append((it, "timestamp %s outside 0..%s" % (t, int(duration or 0))))
            continue
        it["t"] = t
        if not (it.get("title") and it.get("summary")):
            dropped.append((it, "missing title or summary"))
            continue
        kept.append(it)
    kept.sort(key=lambda x: x["t"])
    return kept, dropped


def summarize(yt_id, model=DEFAULT_PROVIDER, dry_run=False, force=False,
              video_data=None, out_path=None):
    video_data = video_data or utils.get_video_data()
    base, srt = transcript_dir(yt_id, video_data)
    if not srt:
        print("%s: no transcript" % yt_id)
        return None
    dest = out_path or os.path.join(base, base + ".summary.json")
    global _CACHED
    _CACHED = False
    body = io.open(srt, encoding="utf-8", errors="replace").read()
    sha = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:16]

    if os.path.exists(dest) and not force:
        try:
            old = json.load(io.open(dest, encoding="utf-8"))
            if old.get("transcript_sha") == sha:
                print("%s: current" % yt_id)
                # CACHED, so no API call happened. The caller must know, or it
                # applies the rate-limit pace to a meeting it never asked about
                # -- see the pace check in main().
                _CACHED = True
                return old
        except ValueError:
            pass

    names = {}
    ids = os.path.join(base, "speaker_ids.json")
    if os.path.exists(ids):
        try:
            names = json.load(io.open(ids, encoding="utf-8"))
        except ValueError:
            pass
    text, duration = timed_transcript(srt, names)
    entry = video_data.get(yt_id) or {}
    header = ("Meeting: %s\nBody: %s\nDate: %s\n\nTranscript follows. Each line "
              "begins with [seconds].\n\n" % (entry.get("title") or "",
                                              entry.get("meeting_type") or "",
                                              entry.get("date") or ""))
    print("%s: %s (%.1f h, ~%dk chars)"
          % (yt_id, printable(entry.get("title") or ""),
             (duration or 0) / 3600.0, len(text) // 1000))
    if dry_run:
        print("  dry run; no API call")
        return None

    provider = model if model in MODEL_LADDER else provider_for(model)
    reply, usage, used = ask(model, SYSTEM, header + text, api_key(provider))
    summary = parse_json(reply)
    kept, dropped = verify(summary, duration)
    for it, why in dropped:
        print("  DROPPED %-40s (%s)" % (str(it.get("title"))[:40], why))
    out = {"video_id": yt_id,
           "provider": provider_for(used),
           "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           # WHAT ANSWERED, and what was asked for when they differ. A backlog
           # run spanning a model retirement produces summaries from two
           # models; without this the difference is invisible in the output.
           "model": used,
           "model_requested": (model if used != model else None),
           "transcript_sha": sha,
           "subject": clean_subject(summary.get("subject"),
                                    entry.get("meeting_type"),
                                    entry.get("title")),
           "overview": (summary.get("overview") or "").strip(),
           "items": kept,
           "dropped": len(dropped),
           "usage": usage}
    tmp = dest + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
        json.dump(out, fp, indent=1, ensure_ascii=False)
    os.replace(tmp, dest)
    print("  %d items, %d dropped, in/out tokens %s/%s -> %s"
          % (len(kept), len(dropped), usage.get("input_tokens"),
             usage.get("output_tokens"), dest))

    # REBUILD THE PAGE, or the summary is invisible. srt2html reads this
    # sidecar at render time, and the page was generated when the meeting was
    # transcribed -- hours or months before this runs. Without this the
    # nightly job would accumulate correct summaries that nobody can see,
    # which is the exact failure shape this codebase keeps hitting: work that
    # succeeds, logs success, and changes nothing.
    #
    # Imported lazily: srt2html pulls in whisperx-adjacent modules and a
    # --dry-run should not pay for them.
    if not out_path:
        try:
            import srt2html
            srt2html.srt2html(yt_id, force=True)
            print("  page rebuilt")
        except Exception as e:
            # never let rendering failure lose a summary that cost real quota
            print("  WARNING: summary written but page NOT rebuilt: %s" % str(e)[:120])
    return out


# WHY AN ORDER FILE AND NOT JUST A DATE SORT. --all used to be strictly
# date-descending, which is right for keeping up and useless for filling a
# hole: the High School Building Committee's founding months (Apr-Sep 2024,
# the meetings where it was constituted, wrote its rules and picked an OPM)
# sat roughly 1,700 meetings deep behind a queue that moves 2-20 a night, so
# a committee overview could not be written for the body that most needs one.
#
# A free daily allowance makes ORDER the only lever there is. Nothing here
# makes the backlog shorter; it decides what today's twenty requests buy.
PRIORITY_FILE = "summary_priority.txt"
RECENT_DAYS = 30


def read_priority(path=PRIORITY_FILE):
    """Meeting types and ids to summarise ahead of the backlog, in rank order.

    One entry per line -- a meeting_type name ("MPS High School Building
    Committee") or a bare video id -- with # comments and blanks ignored.
    File ORDER is rank, so a second body listed below MHSBC is reached only
    once MHSBC is current. Same idiom as ids_to_transcribe.txt.
    """
    if not os.path.exists(path):
        return []
    out = []
    for line in io.open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line and line not in out:
            out.append(line)
    return out


def _recent_cutoff(days=RECENT_DAYS, today=None):
    today = today or datetime.date.today()
    return (today - datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def rank(yt_id, video_data, entries, cutoff):
    """(tier, sub-rank) for the --all queue. Lower sorts earlier.

    Tier 0 recent meetings, tier 1 the priority file in its own order,
    tier 2 the backlog. A recent MHSBC meeting is tier 0, which is where it
    belongs either way.

    RECENCY IS BY MEETING DATE, not by when the transcript landed, because
    the Castus import backfills 2018 recordings continuously -- those are new
    to the archive and not news to a reader. The cost is that a meeting whose
    date was mis-parsed misses tier 0 (`10.6.25` read as 2025 and dropped the
    transcription priority ~160x before `date_manual` fixed it), so a stale
    date is now two bugs rather than one.
    """
    e = video_data.get(yt_id) or {}
    if (e.get("date") or e.get("upload_date") or "") >= cutoff:
        return (0, 0)
    for i, entry in enumerate(entries):
        if entry == yt_id or entry == e.get("meeting_type"):
            return (1, i)
    return (2, 0)


def order_todo(todo, video_data, entries, days=RECENT_DAYS, today=None):
    """todo sorted by tier, newest first inside each tier.

    Two passes rather than one composite key: date descending, then a STABLE
    sort by tier, which keeps the date order within a tier without having to
    invert a date string.
    """
    cutoff = _recent_cutoff(days, today)
    todo = sorted(todo, key=lambda k: (video_data[k].get("date")
                                       or video_data[k].get("upload_date")
                                       or ""), reverse=True)
    todo.sort(key=lambda k: rank(k, video_data, entries, cutoff))
    return todo


def report_priority(entries, video_data):
    """Warn about an entry that matches nothing.

    A typo'd committee name is silently a no-op, and silent no-ops are this
    codebase's recurring failure: the work runs, logs success, and changes
    nothing. One line at startup is the whole fix.
    """
    types = {(v.get("meeting_type") or "") for v in video_data.values()}
    for entry in entries:
        if entry in types:
            continue
        if entry in video_data:
            continue
        print("  WARNING: priority entry matches no meeting_type or id: %r"
              % entry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--id", dest="yt_id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=DEFAULT_PROVIDER,
                    help="exact model id, or a provider name "
                         "(gemini/openai/anthropic) to let the "
                         "ladder pick the best one that answers")
    ap.add_argument("--list-models", action="store_true",
                    help="show what each provider serves today, "
                         "and which the ladder would choose")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="check the subject-line rules and exit")
    ap.add_argument("--sleep", type=float, default=None,
                    help="seconds between calls in --all. Default paces the "
                         "Gemini FREE tier (5 RPM on 2.5 Pro, 10 on Flash); "
                         "0 for paid tiers.")
    ap.add_argument("--out", help="write here instead of <base>.summary.json "
                                  "(for comparing two models side by side)")
    ap.add_argument("--priority-file", default=PRIORITY_FILE,
                    help="meeting types / ids to summarise ahead of the "
                         "backlog, in rank order. Default %s" % PRIORITY_FILE)
    ap.add_argument("--recent-days", type=int, default=RECENT_DAYS,
                    help="a meeting this new goes first regardless of the "
                         "priority file. Default %d" % RECENT_DAYS)
    ap.add_argument("--plan", type=int, metavar="N", default=0,
                    help="print the first N of the --all queue with their "
                         "tiers and exit. No API calls.")
    args = ap.parse_args()
    if args.self_test:
        return self_test_subject()

    # Set once per process, before any request: how hard to retry a 503. See
    # TRANSIENT_ATTEMPTS. --list-models and --dry-run are excluded so that
    # probing the ladder does not consume the "first run after reset" credit
    # that the real run is meant to spend.
    # --plan is excluded for the same reason --list-models is: transient_budget
    # RECORDS the run, and inspecting the queue must not spend the "first run
    # after the reset" retry credit that the real run is meant to have.
    if not (args.list_models or args.dry_run or args.plan):
        global TRANSIENT_ATTEMPTS
        TRANSIENT_ATTEMPTS = transient_budget()
        if TRANSIENT_ATTEMPTS > 1:
            print("first run since the daily reset: retrying 503s up to %d times"
                  % TRANSIENT_ATTEMPTS)

    if args.list_models:
        # What the ladder would actually pick today, per provider. Run this
        # first when summaries stop appearing: a silent retirement shows up
        # here as a ladder entry with no live match.
        for provider in sorted(MODEL_LADDER):
            try:
                key = api_key(provider)
            except Exception as e:
                print("%-10s no key (%s)" % (provider, str(e)[:50]))
                continue
            live = list_models(provider, key)
            chosen = candidates(provider, key)
            print("\n%s -- %d models served" % (provider.upper(), len(live)))
            for pref in MODEL_LADDER[provider]:
                hit = next((m for m in chosen if m.startswith(pref)), None)
                print("   %-22s -> %s" % (pref, hit or "(not served)"))
            print("   would use: %s" % (chosen[0] if chosen else "NOTHING"))
            # A two-token probe of the top candidate. Costs one request, and
            # it is the only way to learn the real limit: the models listing
            # reports what is SERVED, never what is left.
            if chosen and provider == "gemini":
                try:
                    r = requests.post(GEMINI_URL % chosen[0], timeout=45,
                                      params={"key": key},
                                      headers={"content-type": "application/json"},
                                      json={"contents": [{"parts": [{"text": "hi"}]}]})
                    if r.status_code == 429:
                        print("   quota now: EXHAUSTED -- %s" % _quota_note(r))
                    else:
                        print("   quota now: answering (HTTP %s)" % r.status_code)
                except Exception as e:
                    print("   quota now: could not probe (%s)" % str(e)[:40])
        return 0

    video_data = utils.get_video_data()
    if args.yt_id:
        summarize(args.yt_id, args.model, args.dry_run, args.force, video_data,
                  args.out)
        return 0
    if not (args.all or args.plan):
        ap.error("give -i <yt_id>, --all, or --plan N")
    todo = [k for k, v in video_data.items()
            if not v.get("skip") and transcript_dir(k, video_data)[1]]
    entries = read_priority(args.priority_file)
    if entries:
        report_priority(entries, video_data)
    todo = order_todo(todo, video_data, entries, args.recent_days)

    if args.plan:
        # What today's allowance would buy, in order, and whether each is
        # already current -- a cached meeting costs nothing, so the number
        # that matters is how many UNWRITTEN ones are near the front.
        cutoff = _recent_cutoff(args.recent_days)
        labels = {0: "recent", 1: "priority", 2: "backlog"}
        pending = 0
        for yt_id in todo[:args.plan]:
            e = video_data[yt_id]
            tier, sub = rank(yt_id, video_data, entries, cutoff)
            base = transcript_dir(yt_id, video_data)[0]
            have = os.path.exists(os.path.join(base, base + ".summary.json"))
            pending += 0 if have else 1
            print("%-8s %-10s %-12s %s %s"
                  % (labels[tier] + (":%d" % sub if tier == 1 else ""),
                     e.get("date") or e.get("upload_date") or "", yt_id,
                     "have" if have else "WANT",
                     printable((e.get("title") or "")[:52])))
        print("\n%d of the first %d need a summary; %d in the queue overall."
              % (pending, min(args.plan, len(todo)), len(todo)))
        return 0
    # Free-tier limits are per MINUTE and per DAY, and exceeding either
    # returns 429 even when the other is fine. Pacing here is cheaper than
    # retry logic, and an unattended backlog run has no reason to hurry.
    pace = args.sleep
    if pace is None:
        pace = 13.0 if provider_for(args.model) == "gemini" else 0.0
    done = 0          # meetings processed, cached ones included
    made = 0          # summaries actually GENERATED this run
    consecutive_failures = 0
    for yt_id in todo:
        # LIMIT COUNTS WHAT IT GENERATES, not what it walks past. `done`
        # includes cache hits, so with the queue now TIERED -- 97 current
        # meetings ahead of the first unwritten one -- `--limit 8` used to
        # stop after 8 cache hits and summarise nothing at all. Third time
        # this counter has been wrong in the same direction (see the pacing
        # comment below and the "summarised 74" report): `done` is a scan
        # position, `made` is the work.
        if args.limit and made >= args.limit:
            break
        try:
            if summarize(yt_id, args.model, args.dry_run, args.force, video_data):
                done += 1
                if not _CACHED:
                    made += 1
            # PACE ONLY AFTER A REAL REQUEST. summarize() returns the cached
            # dict on a hit, which is truthy, so this used to sleep 13s between
            # meetings it never contacted the API about. A cache check is 3.7ms
            # -- all 2,300 take 9 seconds -- but at 13s each the scan alone
            # would be 8.3 HOURS, and an hourly run would never reach new work.
            # Measured before the fix: 57 cache hits in 13 minutes.
            if pace and not _CACHED:
                time.sleep(pace)
        except DailyQuotaExhausted as e:
            # NOT "skip this one and carry on". Carrying on means walking the
            # whole ladder for every remaining meeting and failing all of them.
            print("\nSTOPPING: %s" % e)
            # NEW summaries, not meetings walked past. `done` counts
            # cache hits too, so it reported "summarised 74" on a run that
            # generated 5 -- the same flattering arithmetic as the pacing bug.
            print("generated %d new (%d already current); %d still to do."
                  % (made, done - made, len(todo) - done))
            # NOT "wait for the reset". The per-day allowance is a rolling
            # window (see ask_gemini), so the next hourly run an hour from now
            # is a real chance rather than a formality -- which is exactly
            # what summarize.bat was already built to exploit.
            print("The allowance refills continuously, so the next hourly run"
                  " may well get through -- already-summarised meetings are"
                  " skipped on the transcript SHA, so it resumes where it left"
                  " off.")
            return 0
        except Exception as e:
            print("  FAILED %s: %s" % (yt_id, str(e)[:160]))
            # EVERY ATTEMPT COSTS QUOTA, INCLUDING THE FAILED ONES. Measured
            # 2026-09-25: three SUCCESSFUL full-transcript calls plus roughly
            # forty failed attempts exhausted the daily allowance on three
            # models. Three successes cannot reach a 20/day cap, so the
            # rejections are what spent it.
            #
            # That is why this counter exists. Continuing past a transient
            # 503 is right -- one blip should not end the night -- but a
            # SUSTAINED outage would otherwise walk the whole ladder for each
            # of 2,000+ remaining meetings, spending the entire day's
            # allowance discovering the same thing over and over. Three
            # consecutive total failures is enough to conclude the hour is
            # not workable; the next hourly run will find out if that changed.
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print("\nSTOPPING: %d meetings in a row failed outright. Every "
                      "attempt costs quota, so this run stops rather than "
                      "spending the day's allowance on a bad window."
                      % consecutive_failures)
                print("generated %d new (%d already current); %d still to do."
                      % (made, done - made, len(todo) - done))
                return 0
        else:
            consecutive_failures = 0
    print("generated %d new (%d already current)" % (made, done - made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
