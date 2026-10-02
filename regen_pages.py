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
import json
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


def page_is_complete(d):
    """Did this page finish being written?

    MTIME IS NOT COMPLETION. srt2html writes the head, appends the body over
    several passes and closes the document last, so a process killed partway
    leaves a file with a FRESH timestamp and a truncated body. Recovering a
    progress list from mtimes alone therefore marks half-written pages as done
    and they are never rebuilt.

    The footer is written last, so a closing </body></html> is the marker that
    the whole pass ran.
    """
    h = os.path.join(d, os.path.basename(d) + ".html")
    try:
        page = io.open(h, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    if "</body>" not in page[-400:] or "</html>" not in page[-400:]:
        return False

    # THE SIDECAR MUST MATCH THE PAGE IT INDEXES. do_one writes the html and
    # THEN builds .words.json, so a process killed between the two leaves a
    # page that passes every check above beside a sidecar built for the old
    # line count. transcript-player addresses rows by position and refuses a
    # mismatch outright, so the whole page silently drops to sentence-level
    # seeking -- which is how this was found: the owner noticed clicking a word
    # jumped to the start of its paragraph.
    #
    # Pages with no model.pkl have no sidecar at all (370 of them) and are
    # correctly line-level; only a sidecar that EXISTS and disagrees is a fault.
    w = os.path.join(d, os.path.basename(d) + ".words.json")
    if os.path.exists(w):
        try:
            rows = len(json.load(io.open(w, encoding="utf-8")))
        except Exception:
            return False
        if rows != page.count('<p class="line" data-t='):
            return False
    return True


def verify(prune=False):
    """Check every id in the progress file actually produced a finished page."""
    done = done_ids()
    # A video id can appear under TWO directories when upload_date changed after
    # the first was created -- afnvZAYk2_M is named for its meeting date in one
    # and its upload date in the other. Only one gets a page, and the other is
    # an orphan holding an srt and a model. Reporting it as "incomplete" every
    # run teaches you to ignore the check, so name it instead.
    byid = {}
    for d, yt in meeting_dirs():
        byid.setdefault(yt, []).append(d)
    bad, orphan = [], []
    for d, yt in meeting_dirs():
        if yt not in done or page_is_complete(d):
            continue
        sibling_has_page = any(page_is_complete(o) for o in byid[yt] if o != d)
        (orphan if sibling_has_page else bad).append((yt, d))
    if orphan:
        print("orphan directories (a sibling holds the published page): %d" % len(orphan))
        for yt, d in orphan:
            print("   %s" % d)
    bad = [yt for yt, d in bad]
    print("marked done: %d   incomplete: %d" % (len(done), len(bad)))
    for yt in bad[:10]:
        print("   %s" % yt)
    if bad and prune:
        keep = sorted(done - set(bad))
        for p in progress_paths():
            os.remove(p)
        with io.open(PROGRESS, "w", encoding="utf-8") as fp:
            fp.write(chr(10).join(keep) + chr(10))
        print("pruned %d; they will be rebuilt" % len(bad))
    return len(bad)


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
    ap.add_argument("--verify", action="store_true",
                    help="check the progress list against finished pages")
    ap.add_argument("--prune", action="store_true",
                    help="with --verify, drop incomplete pages so they rebuild")
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
    if args.verify:
        return 1 if verify(prune=args.prune) and not args.prune else 0
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
