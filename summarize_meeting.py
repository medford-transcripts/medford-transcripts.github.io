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

import requests

import srt_lines
import utils

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
KEY_FILES = ("claude_key.txt", "anthropic_key.txt")
MAX_OUTPUT = 2000   # 400 words needs far less; the cap keeps it honest

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
under a minute -- roughly 250 to 400 words including the overview. Human \
recaps of these meetings run 900 to 2,000 words; yours should be a quarter \
of that, because it sits ABOVE the full transcript rather than replacing it.
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


def api_key():
    for f in KEY_FILES:
        if os.path.exists(f):
            k = io.open(f, encoding="utf-8").read().strip()
            if k:
                return k
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    raise SystemExit(
        "No API key. Put it in claude_key.txt (gitignore it) or set "
        "ANTHROPIC_API_KEY.")


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


def ask(model, system, user, key, max_tokens=MAX_OUTPUT):
    r = requests.post(API_URL, timeout=600,
                      headers={"x-api-key": key,
                               "anthropic-version": API_VERSION,
                               "content-type": "application/json"},
                      json={"model": model, "max_tokens": max_tokens,
                            "system": system,
                            "messages": [{"role": "user", "content": user}]})
    if r.status_code != 200:
        raise RuntimeError("API %s: %s" % (r.status_code, r.text[:300]))
    d = r.json()
    parts = [c.get("text", "") for c in d.get("content", []) if c.get("type") == "text"]
    return "".join(parts), d.get("usage", {})


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


def summarize(yt_id, model=DEFAULT_MODEL, dry_run=False, force=False, video_data=None):
    video_data = video_data or utils.get_video_data()
    base, srt = transcript_dir(yt_id, video_data)
    if not srt:
        print("%s: no transcript" % yt_id)
        return None
    dest = os.path.join(base, base + ".summary.json")
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

    reply, usage = ask(model, SYSTEM, header + text, api_key())
    summary = parse_json(reply)
    kept, dropped = verify(summary, duration)
    for it, why in dropped:
        print("  DROPPED %-40s (%s)" % (str(it.get("title"))[:40], why))
    out = {"video_id": yt_id,
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
    args = ap.parse_args()

    video_data = utils.get_video_data()
    if args.yt_id:
        summarize(args.yt_id, args.model, args.dry_run, args.force, video_data)
        return 0
    if not args.all:
        ap.error("give -i <yt_id> or --all")
    todo = [k for k, v in video_data.items()
            if not v.get("skip") and transcript_dir(k, video_data)[1]]
    todo.sort(key=lambda k: (video_data[k].get("date") or ""), reverse=True)
    done = 0
    for yt_id in todo:
        if args.limit and done >= args.limit:
            break
        try:
            if summarize(yt_id, args.model, args.dry_run, args.force, video_data):
                done += 1
        except Exception as e:
            print("  FAILED %s: %s" % (yt_id, str(e)[:160]))
    print("summarised %d" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
