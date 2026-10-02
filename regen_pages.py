"""Rebuild transcript pages, resumably.

WHY FORCE IS NEEDED, and why that creates a problem. srt2html skips a page whose
last_update is newer than its .srt, which is right for a content change but wrong
for a TEMPLATE change: the paragraph breaks added in e96a6ef7c5 have to reach
pages whose transcript never changed, and those are exactly the ones the skip
test discards. So this passes force=True.

But force disables the skip, so a run killed partway would start again from
nothing -- and these runs do get killed. The box shares memory with diarization,
whose peaks took out six consecutive attempts at the name sweep. Hence a progress
file: one meeting id per line, appended after each page is written, consulted on
the next run. Resuming costs at most the page that was in flight.

WHAT THIS PASS CARRIES, all of it invisible until a page is rebuilt:
  - the corrected names from the fix_common_errors sweep (190 .srt files)
  - paragraph breaks at measured pauses
  - the line_span alignment, so a correction form opens one paragraph rather
    than a turn that can run to 7,763 words
  - BreadcrumbList / WebPage structured data on anything not yet rebuilt

do_extras is False per page because the index, committee pages and resolution
tracker are corpus-wide and would otherwise be rebuilt once per meeting. Run
them once at the end -- srt2html.make_index() and make_committee_pages.make().

    python regen_pages.py            # all of it, resuming where it stopped
    python regen_pages.py --limit 50
    python regen_pages.py --status
"""

import argparse
import glob
import sys
import io
import os
import time

PROGRESS = "regen_progress.txt"


def progress_paths():
    """Every worker's progress file.

    EACH SHARD WRITES ITS OWN. A single shared file would have four processes
    appending concurrently, and an interleaved write loses ids -- which here
    means silently rebuilding pages twice, or worse, recording one that did not
    finish. Separate files make the append safe without a lock, and reading is
    just the union.
    """
    return sorted(glob.glob(PROGRESS.replace(".txt", "*.txt")))


def meeting_dirs():
    out = []
    for p in sorted(glob.glob("*/20??-??-??_???????????.srt")):
        d = os.path.dirname(p)
        yt = os.path.basename(d).split("_", 1)[1]
        out.append((d, yt))
    return out


def done_ids():
    out = set()
    for p in progress_paths():
        try:
            out |= set(io.open(p, encoding="utf-8").read().split())
        except OSError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--status", action="store_true")
    # THE REBUILD IS CPU-BOUND AND SINGLE-THREADED: measured at 98% of one core
    # with a flat 0.54 GB working set, on a box with 8 logical cores. Memory is
    # binary here -- enough not to be killed, and nothing above that helps --
    # so the only lever on wall time is running more of them.
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    args = ap.parse_args()

    all_m = meeting_dirs()
    done = done_ids()
    todo = [(d, y) for d, y in all_m if y not in done]
    print("meetings: %d   already rebuilt: %d   remaining: %d"
          % (len(all_m), len(done), len(todo)))
    if args.status:
        return 0
    if args.workers > 1:
        import subprocess
        procs = []
        for i in range(args.workers):
            procs.append(subprocess.Popen(
                [sys.executable, __file__, "--shard", str(i),
                 "--of", str(args.workers)]))
            print("  started worker %d/%d (pid %d)"
                  % (i + 1, args.workers, procs[-1].pid), flush=True)
        rc = 0
        for p in procs:
            rc |= p.wait()
        print("all workers finished (rc=%d)" % rc)
        return rc

    # interleaved rather than blocked, so a long meeting does not land every
    # one of its neighbours on the same worker
    if args.of > 1:
        todo = [t for n, t in enumerate(todo) if n % args.of == args.shard]
    if args.limit:
        todo = todo[:args.limit]

    import srt2html
    t0 = time.time()
    ok = fail = 0
    for i, (d, yt) in enumerate(todo, 1):
        try:
            # video_data.json is written by the live transcription loop too, and
            # the atomic replace loses to whoever holds it -- WinError 5. The
            # lock is brief, so retry rather than treat a lost race as a failed
            # page. The page itself is usually already written when this fires.
            for attempt in range(4):
                try:
                    srt2html.do_one(yt, force=True, do_scrape=False,
                                    do_extras=False)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(2 + 3 * attempt)
            # appended ONLY on success, so a crash mid-page retries it
            shard_file = (PROGRESS if args.of == 1 else
                          PROGRESS.replace(".txt", "_%d.txt" % args.shard))
            with io.open(shard_file, "a", encoding="utf-8") as fp:
                fp.write(yt + "\n")
            ok += 1
        except Exception as e:
            fail += 1
            print("  FAILED %s (%s: %s)" % (yt, type(e).__name__, str(e)[:90]),
                  flush=True)
        if i % 10 == 0 or i == len(todo):
            el = time.time() - t0
            rate = el / max(1, ok)
            print("  %d/%d done, %d failed, %.1fs/page, ~%.0f min left"
                  % (i, len(todo), fail, rate, rate * (len(todo) - i) / 60.0),
                  flush=True)
    print("rebuilt %d, failed %d, in %.0f min" % (ok, fail, (time.time() - t0) / 60.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
