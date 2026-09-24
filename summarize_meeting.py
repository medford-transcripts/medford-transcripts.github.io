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
DEFAULT_MODEL = "gemini-2.5-pro"

# Two providers, because the economics differ in kind rather than degree.
# Anthropic has no free tier: the backlog costs $174 (Sonnet 5) to $348
# (Opus 5.5), halved on the Batch API. Gemini has a genuine free tier -- 100
# requests/day on 2.5 Pro, 250 on Flash -- which clears 2,232 meetings in
# roughly 9 to 22 days at zero cost.
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


def ask_gemini(model, system, user, key, max_tokens=MAX_OUTPUT):
    """responseMimeType forces valid JSON, so no code fence to strip."""
    r = requests.post(GEMINI_URL % model, timeout=600,
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


def ask(model, system, user, key, max_tokens=MAX_OUTPUT):
    p = provider_for(model)
    if p == "openai":
        return ask_openai(model, system, user, key, max_tokens)
    if p == "gemini":
        return ask_gemini(model, system, user, key, max_tokens)
    return ask_anthropic(model, system, user, key, max_tokens)


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


def summarize(yt_id, model=DEFAULT_MODEL, dry_run=False, force=False,
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

    reply, usage = ask(model, SYSTEM, header + text,
                       api_key(provider_for(model)))
    summary = parse_json(reply)
    kept, dropped = verify(summary, duration)
    for it, why in dropped:
        print("  DROPPED %-40s (%s)" % (str(it.get("title"))[:40], why))
    out = {"video_id": yt_id,
           "provider": provider_for(model),
           "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "model": model,
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
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=None,
                    help="seconds between calls in --all. Default paces the "
                         "Gemini FREE tier (5 RPM on 2.5 Pro, 10 on Flash); "
                         "0 for paid tiers.")
    ap.add_argument("--out", help="write here instead of <base>.summary.json "
                                  "(for comparing two models side by side)")
    args = ap.parse_args()

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
        except Exception as e:
            print("  FAILED %s: %s" % (yt_id, str(e)[:160]))
    print("summarised %d" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
