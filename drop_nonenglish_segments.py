"""
Remove non-English segments left behind by Whisper language mis-identification.

WHAT HAPPENED (see the note at the top of is_english.py): for a period the
pipeline let Whisper auto-detect the language from the first ~30 seconds. It
gets that wrong a few percent of the time, and when it does it TRANSLATES the
rest of the meeting into the mis-detected language. Four transcripts contain
long stretches of Welsh. Nobody at a Medford City Council meeting is speaking
Welsh -- it is pure noise, not a translation of anything useful.

The pipeline now forces language="en", so this cannot recur. This is cleanup
of the existing damage.

WHY DELETE RATHER THAN RE-TRANSCRIBE: the four files are 13.2 hours of audio,
about 44 hours of compute. The Welsh is 5-15% of each file and carries no
information. Dropping those segments costs seconds.

SAFETY:
  - a segment must be BOTH long enough to classify reliably AND detected as
    non-English; short segments are never touched, because langdetect is
    unreliable on fragments and would eat legitimate one-word English lines
  - _aligned.srt is never modified and retains the complete original, so the
    raw record survives even though .srt and .srt.orig are cleaned
  - blocks are renumbered so the SRT stays valid

Usage:
    python drop_nonenglish_segments.py                 # dry run, all files
    python drop_nonenglish_segments.py --apply
    python drop_nonenglish_segments.py -i <yt_id>
"""

import argparse
import glob
import io
import os
import re
import sys

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0          # make detection deterministic
except ImportError:
    detect = None

MIN_CHARS = 40          # below this, langdetect is noise
SPEAKER_RE = re.compile(r"^\[([^\]]*)\]:\s*(.*)$", re.S)


def parse_srt(text):
    """[(index, timestamp_line, body), ...]"""
    blocks = []
    for raw in re.split(r"\r?\n\r?\n", text):
        lines = raw.strip().splitlines()
        if len(lines) < 3:
            continue
        blocks.append((lines[0], lines[1], "\n".join(lines[2:])))
    return blocks


def spoken_text(body):
    m = SPEAKER_RE.match(body.strip())
    return (m.group(2) if m else body).strip()


def is_non_english(body):
    words = spoken_text(body)
    if len(words) < MIN_CHARS:
        return False, "too short to classify"
    try:
        lang = detect(words)
    except Exception:
        return False, "undetectable"
    return lang != "en", lang


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("-i", "--yt_id")
    ap.add_argument("--show", type=int, default=4)
    args = ap.parse_args()

    if detect is None:
        print("langdetect is not installed:  pip install langdetect")
        return 1
    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    pattern = ("20??-??-??_" + args.yt_id + "/*_" + args.yt_id + ".srt"
               if args.yt_id else "20??-??-??_*/*.srt")

    total_dropped = files_changed = 0
    for srt in sorted(glob.glob(pattern)):
        base = os.path.basename(srt)
        if base.endswith((".orig",)) or "_aligned" in base or "_basic" in base:
            continue

        text = io.open(srt, encoding="utf-8", errors="replace").read()
        blocks = parse_srt(text)
        if not blocks:
            continue

        keep, dropped = [], []
        for idx, ts, body in blocks:
            bad, lang = is_non_english(body)
            (dropped if bad else keep).append((ts, body, lang))

        if not dropped:
            continue

        # only act when it is a real infestation -- one stray misdetected line
        # in an otherwise English transcript is far more likely to be a false
        # positive than a genuine language error
        if len(dropped) < 5:
            continue

        files_changed += 1
        total_dropped += len(dropped)
        print("%-34s dropping %d of %d segments" % (os.path.dirname(srt),
                                                    len(dropped), len(blocks)))
        for ts, body, lang in dropped[:args.show]:
            print("    [%s] %s" % (lang, spoken_text(body)[:88]))
        if len(dropped) > args.show:
            print("    ... and %d more" % (len(dropped) - args.show))

        if args.apply:
            out = []
            for n, (ts, body, _) in enumerate(keep, start=1):
                out.append("%d\n%s\n%s\n" % (n, ts, body))
            new_text = "\n".join(out)
            # clean the .orig too, or the next rebuild reintroduces the noise;
            # _aligned.srt still holds the complete original
            for target in (srt, srt + ".orig"):
                if not os.path.exists(target):
                    continue
                tmp = target + ".welshfix.tmp"
                with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
                    fp.write(new_text if target == srt else new_text)
                os.replace(tmp, target)

    print("\nfiles changed   :", files_changed)
    print("segments dropped:", total_dropped)
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
