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

Usage:
    python summarize_meeting.py -i <yt_id> [--model claude-sonnet-5] [--dry-run]
    python summarize_meeting.py --all [--limit N]
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
MODEL_LADDER = {
    "gemini": ["gemini-3.1-pro", "gemini-3-pro", "gemini-3.5-flash",
               "gemini-3-flash", "gemini-2.5-flash"],
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
    """Every model for this provider is out of DAILY allowance. Stop.

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

Return ONLY valid JSON, no prose around it:
{"overview": "1-2 sentences: what this body met about and what it decided",
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
    r = requests.post(ANTHROPIC_URL, timeout=600,
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
                            "output_tokens": u.get("output_tokens")}


def ask_gemini(model, system, user, key, max_tokens=MAX_OUTPUT, attempts=3):
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
    for attempt in range(attempts):
        r = _gemini_call(model, system, user, key, max_tokens)
        if r.status_code in (500, 502, 503, 504):
            if attempt == attempts - 1:
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
        raise DailyQuotaExhausted(
            "%s: %s exhausted (resets midnight Pacific)" % (model, _quota_note(r)))
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
    return requests.post(GEMINI_URL % model, timeout=600,
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
    return text, {"input_tokens": u.get("promptTokenCount"),
                  "output_tokens": u.get("candidatesTokenCount")}


def ask_openai(model, system, user, key, max_tokens=MAX_OUTPUT):
    """Chat Completions.

    Two shapes exist and the split is by model generation, not by endpoint:
    reasoning models take max_completion_tokens and REJECT temperature, older
    ones take max_tokens. Rather than hardcode which is which -- a list that
    goes stale, as claude-sonnet-5 and gemini-2.5-pro both did within a week --
    try the modern shape and fall back on the specific complaint.
    """
    def call(body):
        return requests.post(OPENAI_URL, timeout=600,
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
                  "output_tokens": u.get("completion_tokens")}


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
    tried, last, capped = [], None, []
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
            _WINNER[provider_of(spec)] = model
            return text, usage, model
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
            tried.append("%s(%s)" % (model, status or "err"))
            last = e
    # Every candidate refused, and at least one because its DAILY allowance is
    # gone. Nothing this run does will change that, so say so in a way the
    # caller can act on rather than logging 2,232 identical failures.
    if capped:
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
    body = io.open(srt, encoding="utf-8", errors="replace").read()
    sha = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:16]

    if os.path.exists(dest) and not force:
        try:
            old = json.load(io.open(dest, encoding="utf-8"))
            if old.get("transcript_sha") == sha:
                print("%s: current" % yt_id)
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
    print("%s: %s (%.1f h, ~%dk chars)" % (yt_id, entry.get("title") or "",
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
    return out


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
    ap.add_argument("--sleep", type=float, default=None,
                    help="seconds between calls in --all. Default paces the "
                         "Gemini FREE tier (5 RPM on 2.5 Pro, 10 on Flash); "
                         "0 for paid tiers.")
    ap.add_argument("--out", help="write here instead of <base>.summary.json "
                                  "(for comparing two models side by side)")
    args = ap.parse_args()

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
    if not args.all:
        ap.error("give -i <yt_id> or --all")
    todo = [k for k, v in video_data.items()
            if not v.get("skip") and transcript_dir(k, video_data)[1]]
    todo.sort(key=lambda k: (video_data[k].get("date") or ""), reverse=True)
    # Free-tier limits are per MINUTE and per DAY, and exceeding either
    # returns 429 even when the other is fine. Pacing here is cheaper than
    # retry logic, and an unattended backlog run has no reason to hurry.
    pace = args.sleep
    if pace is None:
        pace = 13.0 if provider_for(args.model) == "gemini" else 0.0
    done = 0
    for yt_id in todo:
        if args.limit and done >= args.limit:
            break
        if done and pace:
            time.sleep(pace)
        try:
            if summarize(yt_id, args.model, args.dry_run, args.force, video_data):
                done += 1
        except DailyQuotaExhausted as e:
            # NOT "skip this one and carry on". Carrying on means walking the
            # whole ladder for every remaining meeting and failing all of them.
            print("\nSTOPPING: %s" % e)
            print("summarised %d before the cap; %d still to do."
                  % (done, len(todo) - done))
            print("Re-run after the quota resets -- already-summarised meetings"
                  " are skipped on the transcript SHA, so it resumes where it"
                  " left off.")
            return 0
        except Exception as e:
            print("  FAILED %s: %s" % (yt_id, str(e)[:160]))
    print("summarised %d" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
