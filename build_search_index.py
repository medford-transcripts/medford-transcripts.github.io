"""The archive's own search index: one small JSON file, searched in the browser.

WHY WE INDEX OURSELVES. The front page used to hand the reader's query to
Google with `site:`, under a note that said, correctly, "this only searches
pages Bing/Google have indexed, which is very incomplete". The archive is
2,376 English pages and 207 MB of transcript text; what a crawler has reached
is a fraction of it, and the project does not control which fraction. Search
is the whole point of transcribing a meeting, so it cannot be delegated to an
index nobody here can see.

WHY NOT PAGEFIND / FLEXSEARCH / ORAMA. Measured before choosing: FlexSearch
and Orama hold the entire index in the browser's memory, which is finished
before it starts at 35M words. Pagefind is the right shape -- sharded, fetched
on demand -- but it works by CRAWLING the generated HTML, and this pipeline
GENERATES that HTML from the SRTs, incrementally, per meeting. Re-scraping our
own output to recover what we had at generation time is backwards, and it
would mean a full pass over 406 MB of HTML on a box that OOM-killed three long
runs on 2026-10-08, plus tens of MB of binary index churned into a .git that
is already 8.3 GB.

So: emit the index as a byproduct of generation, like every other sidecar.

WHAT THIS TIER COVERS, and what it does not. Meeting titles, dates, bodies,
official speaker names, and the AI summaries where a meeting has one. That is
0.9 MB for 2,260 meetings -- small enough to ship whole, so the browser needs
no network round trip per keystroke and no query ever leaves the reader's
machine. It is NOT full-transcript search: the word "culvert" spoken once in
2017 is not in here. Full text is a term-sharded postings index of a different
order (50-150 MB), and the constraint there is the repo, not the browser.

WHOSE NAMES ARE SEARCHABLE. Electeds and city officials, certainly -- who said
what in the conduct of public business IS the record (PRINCIPLES #2). (The
noindex on electeds/ is not a privacy judgement and is not precedent for one:
those pages are duplicated transcript text in a second view, and asking Google
to rank 125 pages of it dilutes the domain the way the machine translations
did.)

The hard part is that a roster of officials is the WRONG cut. 1,405 distinct
full-name speakers appear in the corpus; the people presenting the high school
project are the OPM and the architects, and not one of them is an elected
official -- Matt Rice (52 meetings), Maria D'Orsi (60), Libby Brown (40), Luke
Preisner (36), Kenneth Lord (34), Kimberly Talbot (28), Matt Gulino (19),
Martine Dion (16), Brian Hilliard (14). An index that cannot find them cannot
answer "who designed this school", which is the question.

At the other end, 545 of the 1,405 appear in exactly ONE meeting: a resident
who stepped to a microphone once. Their name is already on that transcript
page, which is right -- they addressed a public body. A downloadable map from
that name to every meeting they ever spoke at is a different artifact, and it
is the one PRINCIPLES #1 refuses: it makes an individual legible to whoever
holds the index instead of making government legible to the public.

So the cut is RECURRENCE, measured, not job title: the official roster, plus
anyone who speaks across MIN_MEETINGS or more meetings. Every advisor above
clears it by a wide margin and the 545 one-off speakers do not.

WHERE THIS PROXY IS WRONG, since it is a proxy: a resident who comments at
twenty council meetings a year is indistinguishable by recurrence from a
consultant who presents at twenty, and will be indexed. That is the known
cost of not hand-maintaining a roster of 1,405 people. The escape hatch is
`search_names_exclude.txt` -- one name per line, kept out regardless -- so
being wrong about a particular person is a one-line fix and not a code change.

Usage:
    python build_search_index.py                 # write search_index.json
    python build_search_index.py --stats         # size and coverage, no write
    python build_search_index.py --min-meetings 8
    python build_search_index.py --all-speakers  # every full name
"""

import argparse
import collections
import datetime
import glob
import io
import json
import os
import sys

import utils

INDEX = "search_index.json"

# A doc with no page cannot be a search result, and a key shorter than its
# value matters at 2,260 docs: "u" (the directory stem, which is also the page
# name) carries the href, the date of publication and the id all at once.
SCHEMA_VERSION = 1


EXCLUDE_FILE = "search_names_exclude.txt"
INCLUDE_FILE = "search_names_include.txt"

# The lowest recurrence that still admits every known advisor by a wide
# margin. Measured 2026-10-09: the thinnest MHSBC presenter speaks across 14
# meetings, while 545 of 1,405 names speak in exactly one and 556 more in two
# to four. There is no natural gap to snap to between 5 and 14, so this sits
# at the low end deliberately -- missing a consultant is a hole in the record,
# while a frequent commenter being findable is a cost the exclude file can
# correct case by case.
MIN_MEETINGS = 5


def _load(path, key=None):
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except (IOError, OSError, ValueError):
        return None
    return d.get(key) if key else d


def official_names():
    """Names the archive already publishes as public figures, from four
    sources that each disagree with the others.

      councilors.json   105 electeds and candidates
      electeds/*.html   124 per-person pages supercut.py has built
      rosters.json       40 board and commission rosters, tracked
      staff_titles.json 108 city employees and their posts

    The noindex on the electeds/ pages is about DUPLICATE CONTENT, not
    privacy, so it says nothing about whether a name belongs here; all four of
    these are people acting in an official capacity (PRINCIPLES #2).

    staff_titles.json and NOT staff.json, which is gitignored for a reason
    that applies here too: it carries contact details, and one file that turns
    40 per-department pages into a mailing list is a different artifact from a
    name with a job title beside it.
    """
    names = set()
    c = _load("councilors.json")
    if isinstance(c, dict):
        names.update(n for n in c if isinstance(n, str))
    for p in glob.glob(os.path.join("electeds", "*.html")):
        names.add(os.path.splitext(os.path.basename(p))[0])
    bodies = _load("rosters.json", "bodies")
    if isinstance(bodies, dict):
        for body in bodies.values():
            for m in (body or {}).get("members") or []:
                if isinstance(m, dict) and m.get("name"):
                    names.add(str(m["name"]))
    staff = _load("staff_titles.json", "people")
    if isinstance(staff, dict):
        names.update(n for n in staff if isinstance(n, str))
    return {n.strip() for n in names if n and n.strip()}


def name_list(path):
    """One name per line, # comments ignored. Missing file is an empty set."""
    if not os.path.exists(path):
        return set()
    out = set()
    for line in io.open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def excluded_names(path=EXCLUDE_FILE):
    """Names kept out of the index by hand, whatever the measurement says.

    A recurrence threshold is a proxy and will be wrong about someone. When it
    is, the fix must be one line in a text file rather than an argument about
    the threshold -- and it must be auditable, which a code change buried in a
    diff is not.
    """
    return name_list(path)


def included_names(path=INCLUDE_FILE):
    """Names indexed regardless of how rarely they speak.

    FOUND BY SAMPLING THE EXCLUDED BAND, which is why sampling it was worth
    doing: Pat Jehlen is the state senator for Medford and appears in 4
    meetings, so no local roster carries her and no recurrence threshold
    reaches her. Officials from OUTSIDE city government are the systematic
    hole in both tests at once -- state legislators, MSBA staff, federal
    delegation -- and they are exactly who PRINCIPLES #2 means by acting in an
    official capacity.
    """
    return name_list(path)


def speakers_for(base):
    """Every full name on this meeting's page, unfiltered.

    Placeholders and cross-video references are excluded by SHAPE rather than
    by pattern: a real name has a space in it, `SPEAKER_07` and
    `kP4iRYobyr0_SPEAKER_01` do not.
    """
    path = os.path.join(base, "speaker_ids.json")
    if not os.path.exists(path):
        return set()
    try:
        d = json.load(io.open(path, encoding="utf-8"))
    except (ValueError, IOError, OSError):
        return set()
    return {n.strip() for n in d.values()
            if isinstance(n, str) and " " in n and "_SPEAKER_" not in n}


def searchable_names(per_meeting, min_meetings=MIN_MEETINGS,
                     all_speakers=False):
    """Which names may be indexed, and the policy line describing the choice.

    Officials by roster, PLUS anyone recurring across `min_meetings` or more
    meetings -- which is how the advisors and consultants get in, since none
    of them is on any roster. Minus the exclude file, always.
    """
    counts = collections.Counter()
    for names in per_meeting.values():
        counts.update(names)
    if all_speakers:
        allowed = set(counts)
        policy = "every speaker"
    else:
        officials = official_names()
        recurring = {n for n, c in counts.items() if c >= min_meetings}
        allowed = officials | recurring | included_names()
        policy = "officials and anyone speaking at %d+ meetings" % min_meetings
    # EXCLUDE WINS over every other source, including the include file: if the
    # two ever disagree about a person, the answer that keeps a name out is
    # the one that cannot do harm by being wrong.
    allowed -= excluded_names()
    # Only names that actually SPEAK somewhere: a roster carries people who
    # never appear in a transcript, and indexing them would mean a search for
    # a name returning nothing while implying the archive had looked.
    allowed &= set(counts)
    return allowed, policy


def build(all_speakers=False, video_data=None, dest=INDEX, write=True,
          min_meetings=MIN_MEETINGS):
    """Assemble the index and write it. Returns (payload, bytes written).

    A FULL REBUILD, not an incremental one. Measured 2026-10-09: 7.3 s for
    2,260 meetings, nearly all of it stat calls and the 545 summary sidecars.
    Incremental updating would need a cache to invalidate and would be wrong
    every time a summary lands -- which is the COMMON case here, not the rare
    one, with ~1,700 still to come. 7 seconds against a summary run that
    spends 30-60 s per meeting on the API is not worth optimising.
    """
    video_data = video_data or utils.get_video_data()

    # TWO PASSES, because the name policy depends on the whole corpus: a name
    # is indexable when it recurs across meetings, which cannot be known while
    # reading the first one. The first pass is the only one that touches
    # speaker_ids.json, so this costs no extra I/O.
    live, per_meeting = [], {}
    for yt_id, e in video_data.items():
        if e.get("skip"):
            continue
        base = (e.get("upload_date") or "") + "_" + yt_id
        if not os.path.exists(os.path.join(base, base + ".html")):
            continue                      # nothing to link a result to
        live.append((yt_id, e, base))
        per_meeting[base] = speakers_for(base)
    allowed, policy = searchable_names(per_meeting, min_meetings, all_speakers)

    docs, with_summary = [], 0
    for yt_id, e, base in live:
        doc = {"u": base,
               "d": (e.get("date") or e.get("upload_date") or "")[:10],
               "t": e.get("title") or ""}
        body = e.get("meeting_type")
        if body:
            doc["b"] = body
        if e.get("duration"):
            doc["n"] = int(e["duration"])
        sp = sorted(per_meeting[base] & allowed)
        if sp:
            doc["s"] = sp
        spath = os.path.join(base, base + ".summary.json")
        if os.path.exists(spath):
            try:
                s = json.load(io.open(spath, encoding="utf-8"))
            except (ValueError, IOError, OSError):
                s = None
            if s:
                with_summary += 1
                if (s.get("overview") or "").strip():
                    doc["o"] = s["overview"].strip()
                # [title, seconds] so a result can deep-link to the moment,
                # using the #t= convention transcript-player already honours.
                items = [[(it.get("title") or "").strip(), int(it["t"])]
                         for it in (s.get("items") or [])
                         if it.get("t") is not None
                         and (it.get("title") or "").strip()]
                if items:
                    doc["k"] = items
        docs.append(doc)

    docs.sort(key=lambda d: (d["d"], d["u"]), reverse=True)
    payload = {
        "v": SCHEMA_VERSION,
        # The front page states its own coverage from these counts rather than
        # from hardcoded prose, so the sentence a reader sees stays true as
        # 1,700 more summaries land.
        "generated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n": len(docs),
        "with_summary": with_summary,
        # The policy is RECORDED, not just applied: a later run that
        # changes the threshold should be visibly a different choice.
        "names": policy,
        "n_names": len(allowed),
        "docs": docs,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if write:
        utils.write_atomic(dest, text)
    return payload, len(text.encode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-speakers", action="store_true",
                    help="index every full-name speaker. See WHOSE NAMES "
                         "ARE SEARCHABLE in this file.")
    ap.add_argument("--min-meetings", type=int, default=MIN_MEETINGS,
                    help="a non-roster name is indexed once it speaks at this "
                         "many meetings. Default %d" % MIN_MEETINGS)
    ap.add_argument("--stats", action="store_true",
                    help="report size and coverage; write nothing")
    ap.add_argument("-o", "--out", default=INDEX)
    args = ap.parse_args()

    payload, size = build(args.all_speakers, dest=args.out,
                          write=not args.stats,
                          min_meetings=args.min_meetings)
    import gzip
    gz = len(gzip.compress(json.dumps(payload, ensure_ascii=False,
                                      separators=(",", ":")).encode("utf-8")))
    print("%d meetings, %d with a summary (%.0f%%)"
          % (payload["n"], payload["with_summary"],
             100.0 * payload["with_summary"] / max(1, payload["n"])))
    print("%d searchable names: %s" % (payload["n_names"], payload["names"]))
    print("%.2f MB raw, %.2f MB gzipped (what a reader downloads, once)"
          % (size / 1e6, gz / 1e6))
    print("wrote %s" % args.out if not args.stats else "stats only; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
