"""
Apply accepted corrections from corrections_queue.json to the transcripts.

THE GAP THIS FILLS: ingest_corrections.py only classifies and queues. Until
now "accepted" meant "marked accepted in a local JSON file" -- nothing was ever
written to a transcript, so a contributor who submitted a correction and then
looked at the site saw no change and had no way to know why.

WHERE EACH KIND OF CORRECTION GOES, which is not obvious from the queue:

  text        -> the .srt block body. fix_common_errors reads the CURRENT .srt
                 and writes back, using .srt.orig only as a one-time backup, so
                 an edit here survives regeneration.

  speaker     -> usually speaker_ids.json, NOT the .srt. The .srt carries
                 "[SPEAKER_04]:" and srt2html resolves it through that map
                 (srt2html.py:472). Naming SPEAKER_04 once therefore fixes
                 every line that speaker says, and track_speakers.propagate()
                 carries it to other meetings -- which is the whole point of
                 the design and far more valuable than fixing one line.

                 BUT only when the label is currently UNNAMED. If SPEAKER_04 is
                 already named someone else, the submitter is reporting that
                 THIS LINE is misattributed, not that the name is wrong
                 everywhere; renaming globally would then corrupt every other
                 line. In that case only this block's label changes.

  split       -> the .srt, structurally: one block becomes several, each with
                 its own speaker. This is the roll-call case and the reason
                 splits cannot be expressed in speaker_ids.json at all.

  timestamp   -> the .srt block's start time.

SAFETY, in the order it is checked:
  - only status "accepted" is ever applied; "pending" needs review first
  - "truncated", "unparsed" and "none" are refused even if marked accepted
  - STALENESS: the block's current text must still match what was recorded at
    ingest. Transcripts get regenerated, and applying a correction written
    against text that has since changed would silently overwrite newer work.
  - writes are atomic (temp + replace) and blocks are renumbered, so a crash
    cannot leave a half-written SRT
  - dry run by default

Usage:
    python apply_corrections.py                 # show what would change
    python apply_corrections.py --apply
    python apply_corrections.py -i <video_id>   # one meeting
"""

import argparse
import difflib
import glob
import io
import json
import os
import re
import sys

QUEUE = "corrections_queue.json"
REFUSE = ("truncated", "unparsed", "none")

from srt_lines import (parse_srt, render_srt, find_block, line_span,
                       line_text, normalise as norm, to_timestamp)


def match_format(new_text, original_text):
    """Re-impose the original file's line endings and trailing blank line.

    Without this, applying a one-word correction rewrites every line of the
    file: these SRTs are CRLF, Python reads them as LF, and writing LF back
    produces a 4,935-line git diff for a one-line change. That buries the
    actual correction in review and throws away the byte-stability the rest of
    the pipeline works to maintain.
    """
    CR = chr(13)
    LF = chr(10)
    crlf = (CR + LF) in (original_text or "")
    text = new_text.replace(CR + LF, LF)
    if (original_text or "").endswith(LF + LF) or (original_text or "").endswith(CR + LF + CR + LF):
        if not text.endswith(LF + LF):
            text = text.rstrip(LF) + LF + LF
    return text.replace(LF, CR + LF) if crlf else text


def write_atomic(path, text, like=None):
    """Temp file + replace, so a crash cannot leave a half-written transcript."""
    if like is not None:
        text = match_format(text, like)
    tmp = path + ".apply.tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
        fp.write(text)
    os.replace(tmp, path)


# ------------------------------------------------------------------ locating

def srt_for(video_id):
    hits = [p for p in glob.glob("20??-??-??_" + video_id + "/*_" + video_id + ".srt")
            if "_aligned" not in p and "_basic" not in p]
    return hits[0] if hits else None


# ------------------------------------------------------------ speaker labels

def load_speaker_ids(directory):
    p = os.path.join(directory, "speaker_ids.json")
    if not os.path.exists(p):
        return {}, p
    with io.open(p, encoding="utf-8") as fp:
        return json.load(fp), p


def is_unnamed(label, mapping):
    """A label nobody has identified yet.

    Two shapes mean 'unknown': it maps to itself (SPEAKER_04 -> SPEAKER_04),
    or it maps to a cross-video reference left by track_speakers
    (SPEAKER_08 -> a17_UOV__Vs_SPEAKER_20), which is a machine pointer rather
    than a human name.
    """
    cur = mapping.get(label, label)
    return cur == label or bool(re.match(r"^[A-Za-z0-9_-]{6,}_SPEAKER_\d+$", cur))


def label_for_name(name, mapping):
    """Existing SPEAKER_NN for a human name, or None."""
    for k, v in mapping.items():
        if v.strip().lower() == name.strip().lower():
            return k
    return None


# ----------------------------------------------------------------- applying

def realign(blocks, lo, hi, turns, mapping):
    """Rebuild the block span from the corrected turns, KEEPING the original
    block boundaries wherever the text still lines up.

    Why not simply replace the span with one block per turn: the block
    boundaries inside a rendered line are the sentence-level timestamps. They
    are what every <a href> anchor on the page points at, and what the player
    falls back to when there is no word sidecar. Collapsing a six-block
    paragraph into one block to fix a typo would silently delete five working
    timestamps from that paragraph.

    So the corrected words are aligned back onto the original words with
    difflib, each corrected word inherits the block its original sat in, and a
    new block is emitted whenever either the source block OR the speaker
    changes. A small edit therefore preserves every boundary; a genuine split
    adds boundaries exactly where the speaker changes.
    """
    orig = []                      # (block_index, word)
    for bi in range(lo, hi):
        for w in re.findall(r"\S+", blocks[bi]["text"]):
            orig.append((bi, w))

    new = []                       # (turn_index, word)
    for ti, t in enumerate(turns):
        for w in re.findall(r"\S+", t["text"]):
            new.append((ti, w))

    if not new:
        return None

    sm = difflib.SequenceMatcher(
        a=[w.lower() for _, w in orig], b=[w.lower() for _, w in new],
        autojunk=False)

    owner = [None] * len(new)      # source block for each corrected word
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "replace"):
            for k in range(j1, j2):
                # proportional for replace, exact for equal
                src = i1 + (k - j1) if tag == "equal" else min(i1 + (k - j1), max(i2 - 1, i1))
                src = min(max(src, 0), len(orig) - 1) if orig else None
                owner[k] = orig[src][0] if orig else lo
        elif tag == "insert":
            for k in range(j1, j2):
                owner[k] = None    # filled below from the neighbour
    # inserted words join the preceding block, or the following one at the start
    last = None
    for k in range(len(owner)):
        if owner[k] is None:
            owner[k] = last
        else:
            last = owner[k]
    nxt = lo
    for k in range(len(owner) - 1, -1, -1):
        if owner[k] is None:
            owner[k] = nxt
        else:
            nxt = owner[k]

    # group consecutive words sharing (source block, turn)
    groups = []
    for k, (ti, w) in enumerate(new):
        key = (owner[k], ti)
        if groups and groups[-1][0] == key:
            groups[-1][1].append(w)
        else:
            groups.append((key, [w]))

    out = []
    for (bi, ti), words in groups:
        src = blocks[bi if bi is not None else lo]
        name = turns[ti]["speaker"].strip()
        label = label_for_name(name, mapping) or name
        out.append({
            "start": src["start"], "end": src["end"],
            "speaker": label, "text": " ".join(words),
        })

    # TIMING. Each output block inherits its source block's start AND END, so a
    # block that merely had a word corrected keeps its exact original timing.
    #
    # This matters more than it looks: stretching every end to the next start
    # would swallow the silence between blocks, and those gaps are real -- they
    # are pauses in the meeting. An earlier version did exactly that and
    # rewrote the timing of all 1,234 blocks in a file to fix one speaker
    # label.
    #
    # Only where ONE source block produced SEVERAL output blocks -- a genuine
    # split inside a block -- is that block's span subdivided between them.
    from itertools import groupby
    pos = 0
    for src_idx, grp in groupby(range(len(out)), key=lambda k: groups[k][0][0]):
        idxs = list(grp)
        src = blocks[src_idx if src_idx is not None else lo]
        if len(idxs) == 1:
            out[idxs[0]]["start"] = src["start"]
            out[idxs[0]]["end"] = src["end"]
            continue
        # subdivide this block's span by word count
        lo_t = src["start"]
        hi_t = src["end"] if src["end"] and src["end"] > lo_t else lo_t + 0.5
        counts = [len(out[k]["text"].split()) for k in idxs]
        total = float(sum(counts) or 1)
        acc = 0
        for n, k in enumerate(idxs):
            out[k]["start"] = lo_t + (hi_t - lo_t) * (acc / total)
            acc += counts[n]
            out[k]["end"] = lo_t + (hi_t - lo_t) * (acc / total)

    # an explicit [seconds] from the submitter overrides the inherited start
    for ti, t in enumerate(turns):
        if not t.get("time"):
            continue
        for k in range(len(out)):
            if groups[k][0][1] == ti:
                out[k]["start"] = float(t["time"])
                break

    # never let the sequence go backwards
    for i in range(1, len(out)):
        if out[i]["start"] < out[i - 1]["start"]:
            out[i]["start"] = out[i - 1]["start"]
        if out[i]["end"] is None or out[i]["end"] < out[i]["start"]:
            out[i]["end"] = out[i]["start"] + 0.5
    return out


def apply_one(rec, blocks, mapping, report):
    """Mutate blocks/mapping for one correction. Returns applied-count delta."""
    t = float(rec["original_timestamp"])
    i = find_block(blocks, t)
    if i is None:
        report.append("    SKIP: no block at t=%s" % rec["original_timestamp"])
        return False
    span = line_span(blocks, i)
    if not span:
        return False
    lo, hi = span

    was = rec.get("original_text") or ""
    now = line_text(blocks, lo, hi)
    if was and norm(now) != norm(was):
        # tolerate the pre-srt_lines queue entries, which recorded only the
        # FIRST block of the line; anything else means the transcript moved
        if norm(blocks[lo]["text"]) != norm(was):
            report.append("    SKIP (STALE): transcript changed since queued")
            report.append("      queued : %s" % norm(was)[:66])
            report.append("      now    : %s" % norm(now)[:66])
            return False
        report.append("    (queued against one block; the rendered line spans %d)"
                      % (hi - lo))

    turns = rec.get("turns") or []
    target = rec.get("target") or []
    if not turns:
        return False

    # a speaker correction on an as-yet-unidentified voice names it globally,
    # which is what speaker_ids.json is for and what propagates across meetings
    if "speaker" in target and len(turns) == 1 and blocks[lo]["speaker"]:
        label = blocks[lo]["speaker"]
        want = turns[0]["speaker"].strip()
        if is_unnamed(label, mapping):
            mapping[label] = want
            report.append("    SPEAKER: %s -> \"%s\" in speaker_ids.json "
                          "(applies to every line by this voice)" % (label, want))

    new = realign(blocks, lo, hi, turns, mapping)
    if not new:
        return False

    before = [(b["speaker"], b["text"]) for b in blocks[lo:hi]]
    after = [(b["speaker"], b["text"]) for b in new]
    if before == after:
        report.append("    no change")
        return False

    report.append("    %d block(s) -> %d" % (hi - lo, len(new)))
    if len(new) < hi - lo:
        # the submitted text replaces the original, so anything left out is
        # deleted. Legitimate when merging blocks, destructive when accidental,
        # so never let it pass without saying so.
        report.append("    NOTE: %d block(s) dropped -- text the submission "
                      "left out is deleted" % ((hi - lo) - len(new)))
    for b in new:
        mark = " " if any(b["text"] == o[1] and b["speaker"] == o[0] for o in before) else "*"
        report.append("     %s %8.3f [%s] %s" % (mark, b["start"], b["speaker"], b["text"][:56]))

    blocks[lo:hi] = new
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("-i", "--video_id")
    ap.add_argument("--queue", default=QUEUE)
    args = ap.parse_args()

    if not os.path.exists(args.queue):
        print("no queue at %s -- run ingest_corrections.py first" % args.queue)
        return 1
    with io.open(args.queue, encoding="utf-8") as fp:
        queue = json.load(fp)
    items = queue.get("items", {})

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    todo = {}
    refused = 0
    for rid, rec in items.items():
        if rec.get("status") != "accepted":
            continue
        if any(x in (rec.get("target") or []) for x in REFUSE):
            refused += 1
            continue
        if args.video_id and rec.get("video_id") != args.video_id:
            continue
        if not rec.get("video_id") or not rec.get("original_timestamp"):
            continue
        todo.setdefault(rec["video_id"], []).append((rid, rec))

    if refused:
        print("refused %d accepted item(s) for being truncated/unparsed/no-op\n" % refused)
    if not todo:
        print("nothing to apply.")
        return 0

    applied_ids, touched = [], []
    for video_id, recs in sorted(todo.items()):
        srt = srt_for(video_id)
        print("%s  (%d correction%s)" % (video_id, len(recs), "" if len(recs) == 1 else "s"))
        if not srt:
            print("    SKIP: no transcript found\n")
            continue
        directory = os.path.dirname(srt)

        text = io.open(srt, encoding="utf-8", errors="replace").read()
        blocks = parse_srt(text)
        mapping, ids_path = load_speaker_ids(directory)
        before_map = dict(mapping)

        # latest timestamp first: a split changes block indices after it
        recs.sort(key=lambda r: -float(r[1]["original_timestamp"]))

        n = map_only = 0
        for rid, rec in recs:
            report = []
            ok = apply_one(rec, blocks, mapping, report)
            # Naming a voice in speaker_ids.json IS a real correction even when
            # no block moves -- it is the most valuable kind, because it names
            # every line that speaker says and propagates across meetings. But
            # it must NOT count as a block change, or the SRT gets rewritten
            # (and reformatted) for an edit that never touched it.
            named = mapping != before_map and not ok
            if named:
                map_only += 1
            print("  t=%s  %s" % (rec["original_timestamp"], "+".join(rec.get("target") or [])))
            for line in report:
                print(line)
            if ok or named:
                if ok:
                    n += 1
                applied_ids.append(rid)

        if args.apply and (n or mapping != before_map):
            if n:
                write_atomic(srt, render_srt(blocks), like=text)
            if mapping != before_map:
                write_atomic(ids_path,
                             json.dumps(mapping, indent=4, ensure_ascii=False) + chr(10))
            touched.append(video_id)
        print()

    print("corrections applied :", len(applied_ids))
    print("meetings touched    :", len(touched) if args.apply else 0)

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return 0

    for rid in applied_ids:
        items[rid]["status"] = "applied"
    with io.open(args.queue, "w", encoding="utf-8") as fp:
        json.dump(queue, fp, indent=2, ensure_ascii=False)

    if touched:
        print("\nNow regenerate the pages:")
        for v in touched:
            print("    python srt2html.py -i %s" % v)

    return 0


if __name__ == "__main__":
    sys.exit(main())
