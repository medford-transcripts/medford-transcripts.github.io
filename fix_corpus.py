"""Apply fix_common_errors' rules to the corpus, one survivable slice at a time.

WHY THIS EXISTS. New rules reach new transcriptions automatically, but an SRT
written before a rule existed keeps its old text forever -- "Councilor Pierce"
had a rule for months and still appeared in scans because the files predate it.
So a rule is only half a fix until the corpus is swept.

WHY IT IS SLICED. The whole-corpus run shares the box with diarization and kept
being killed by the OOM reaper, which picks the long-lived process. Short
invocations over slices survive; a kill costs one batch instead of the run.

IDEMPOTENT, so resuming needs no bookkeeping: applying the rules to already
corrected text is a no-op. Re-run the whole range if you lose track.

    for /L %i in (0,150,2400) do python fix_corpus.py %i 150     (cmd)
    for i in $(seq 0 150 2400); do python fix_corpus.py $i 150; done   (bash)

AFTERWARDS the pages still carry the old text. srt2html skips a page whose
last_update is newer than its .srt, and these files now have a newer mtime, so a
plain do_one() rebuilds them -- no force needed. Nothing schedules that for old
meetings, so it is a deliberate second pass.


The whole-corpus run keeps getting killed: it shares the box with diarization,
and a long-lived process is what the OOM killer picks. Short invocations over
slices survive, and a kill costs one batch rather than the run.

Idempotent -- applying the rules to already-corrected text is a no-op -- so
re-running a slice is safe and resuming needs no bookmark.

    python fix_chunk.py <offset> <count>
"""

import glob
import inspect
import io
import os
import re
import shutil
import sys

sys.path.insert(0, os.getcwd())
import fix_common_errors as F


def rules_table():
    """The ungated replace_dict, read out of the function that defines it."""
    src = inspect.getsource(F.fix_common_errors)
    i = src.index("replace_dict = {")
    i = src.index("{", i)
    depth = 0
    for k in range(i, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return eval(src[i:k + 1])
    raise SystemExit("could not read replace_dict")


def main():
    off = int(sys.argv[1])
    cnt = int(sys.argv[2])
    files = sorted(glob.glob("*/20??-??-??_???????????.srt"))
    batch = files[off:off + cnt]
    if not batch:
        print("done 0 (offset %d past the end of %d)" % (off, len(files)))
        return

    patterns = F.compile_rules(rules_table())
    dated = [(start, F.compile_rules(r))
             for start, r in sorted(F.DATED_REPLACEMENTS.items())]

    changed = 0
    for path in batch:
        m = re.search(r"(20\d\d-\d\d-\d\d)_", os.path.basename(path))
        file_date = m.group(1) if m else "9999-99-99"
        here = list(patterns)
        for start, pats in dated:
            if file_date >= start:
                here.extend(pats)
        # the .orig backup is the ORIGINAL whisper output and is made once
        if not os.path.exists(path + ".orig"):
            shutil.copyfile(path, path + ".orig")
        try:
            text = io.open(path, encoding="utf-8").read()
        except OSError:
            continue
        new = F.apply_rules(text, here)
        if new != text:
            io.open(path, "w", encoding="utf-8").write(new)
            changed += 1
    print("done %d of %d in this slice (offset %d, corpus %d)"
          % (changed, len(batch), off, len(files)))


if __name__ == "__main__":
    main()
