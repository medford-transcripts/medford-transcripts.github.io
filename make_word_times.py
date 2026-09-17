"""
Emit per-line word timings for the in-page player, from model.pkl.

WhisperX already stores per-word start/end in model.pkl
(segments[i]["words"][j]["start"]). The transcript pages only ever showed
sentence-level timestamps, which was a deliberate busy-ness/utility trade --
but the player can highlight and seek at word granularity without showing
anything extra, so the trade no longer has to be made.

OUTPUT: <dir>/<base>.words.json, a sidecar fetched lazily by
transcript-player.js the first time someone plays. Keeping it out of the HTML
matters: the page stays exactly as lean as it is now for crawlers and Ctrl+F,
and the payload costs nothing for the majority of visitors who never hit play.

FORMAT: one array per rendered line, delta-encoded centiseconds.
    [[170,15,16,22], [1004,12,...], ...]
The WORDS THEMSELVES ARE NOT SHIPPED -- they are already in the DOM. That is
what makes this affordable: ~56 KB/page raw and ~20 KB gzipped, versus ~292 KB
for the naive [time, word] encoding.

ALIGNMENT: lines are matched to words by TIME RANGE, not by text. The rendered
text has been through fix_common_errors, so word-for-word matching against
model.pkl would drift; every word whose start falls inside a line's span
belongs to that line, which is robust to any amount of text rewriting.

Usage:
    python make_word_times.py -i <yt_id>
    python make_word_times.py --all
"""

import argparse
import glob
import json
import os
import pickle
import re
import sys

LINE_RE = re.compile(rb'<p class="line" data-t="([0-9.]+)"')


def line_starts(html_path):
    with open(html_path, "rb") as fp:
        return [float(m.group(1)) for m in LINE_RE.finditer(fp.read())]


def word_starts(model_path):
    """One start time per word, in order -- INCLUDING words WhisperX could not
    align.

    THE BUG THIS FIXES: the alignment model works on phonemes and cannot align
    numerals, so about 0.87% of words come back with no "start" -- and they are
    not random. They are figures, dates and money: "$934,439.", "2022.", "15,",
    "5.34,". Dropping them made the sidecar SHORTER than the rendered line, so
    every word after a number resolved to the wrong timing, and the error
    accumulated across the line. Measured before the fix: 17.7% of lines were
    off, by +1 to +9 words, worst on exactly the budget and roll-call lines
    people most want to click into.

    An untimed word now gets a time interpolated between its timed neighbours
    inside the same segment, so the sequence stays monotonic, stays inside the
    segment (which is what keeps time-bucketing into lines correct), and stays
    ONE ENTRY PER WORD -- which is the invariant the player's index depends on.
    """
    with open(model_path, "rb") as fp:
        model = pickle.load(fp)

    out = []
    for seg in model.get("segments", []):
        words = seg.get("words") or []
        if not words:
            continue

        times = []
        for w in words:
            t = w.get("start")
            times.append(None if t is None else float(t))

        # bracket the segment so leading/trailing gaps have something to
        # interpolate against
        seg_lo = seg.get("start")
        seg_hi = seg.get("end")
        known = [i for i, t in enumerate(times) if t is not None]

        if not known:
            # no word in this segment aligned at all: spread them evenly over
            # the segment rather than dropping the whole thing
            lo = float(seg_lo) if seg_lo is not None else 0.0
            hi = float(seg_hi) if seg_hi is not None else lo
            n = len(times)
            step = (hi - lo) / n if n and hi > lo else 0.0
            times = [lo + step * i for i in range(n)]
        else:
            first, last = known[0], known[-1]
            # leading gap
            if first > 0:
                lo = float(seg_lo) if seg_lo is not None else times[first]
                lo = min(lo, times[first])
                step = (times[first] - lo) / (first + 1)
                for i in range(first):
                    times[i] = lo + step * i
            # trailing gap
            if last < len(times) - 1:
                hi = float(seg_hi) if seg_hi is not None else times[last]
                hi = max(hi, times[last])
                n = len(times) - last
                step = (hi - times[last]) / n if n else 0.0
                for i in range(last + 1, len(times)):
                    times[i] = times[last] + step * (i - last)
            # interior gaps
            prev = first
            for i in known[1:]:
                if i > prev + 1:
                    span = (times[i] - times[prev]) / (i - prev)
                    for j in range(prev + 1, i):
                        times[j] = times[prev] + span * (j - prev)
                prev = i

        out.extend(times)

    out.sort()
    return out


def build(directory):
    base = os.path.basename(directory)
    html = os.path.join(directory, base + ".html")
    model = os.path.join(directory, "model.pkl")
    if not (os.path.exists(html) and os.path.exists(model)):
        return None

    starts = line_starts(html)
    if not starts:
        return None
    words = word_starts(model)
    if not words:
        return None

    # bucket words into lines by time; line i spans [starts[i], starts[i+1])
    rows = [[] for _ in starts]
    i = 0
    for t in words:
        while i + 1 < len(starts) and t >= starts[i + 1]:
            i += 1
        if t >= starts[i]:
            rows[i].append(t)

    # delta-encoded centiseconds
    encoded = []
    for row in rows:
        out, prev = [], 0
        for t in row:
            cs = int(round(t * 100))
            out.append(cs - prev)
            prev = cs
        encoded.append(out)

    dest = os.path.join(directory, base + ".words.json")
    blob = json.dumps(encoded, separators=(",", ":"))
    with open(dest, "w", encoding="ascii") as fp:
        fp.write(blob)
    return dest, len(starts), len(words), len(blob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--yt_id")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.yt_id:
        dirs = glob.glob("20??-??-??_" + args.yt_id)
    elif args.all:
        dirs = sorted(glob.glob("20??-??-??_*"))
    else:
        ap.error("give -i <yt_id> or --all")

    made = skipped = total = 0
    for d in dirs:
        if not os.path.isdir(d):
            continue
        r = build(d)
        if r is None:
            skipped += 1
            continue
        dest, nlines, nwords, nbytes = r
        made += 1
        total += nbytes
        if made <= 5 or args.yt_id:
            print("  %-46s %5d lines %6d words %6.1f KB"
                  % (os.path.basename(dest), nlines, nwords, nbytes / 1024.0))

    print("\nwrote %d sidecars (%.1f MB), skipped %d (no model.pkl or no page)"
          % (made, total / 1048576.0, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
