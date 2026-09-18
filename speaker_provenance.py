"""Provenance sidecar for speaker_ids.json.

WHY THIS IS A SEPARATE FILE, not a change to speaker_ids.json's shape:
speaker_ids.json is read by srt2html.py, supercut.py, toid.py, heatmap.py,
generate_reference_voices.py and track_speakers.py. Changing what its values
LOOK LIKE means auditing every one of them. This module instead writes a
PARALLEL file, <meeting_dir>/speaker_provenance.json, keyed identically to
speaker_ids.json, recording how each value got there:

    {"SPEAKER_04": {
        "value": "Mike Mastrobuoni",
        "source": "manual" | "reference_voice" | "embedding_match"
                   | "propagated" | "unknown",
        "score": 0.83,                     # cosine, when a match produced it
        "from": "MCM00001607_SPEAKER_07",  # the cluster key it was derived from
        "at": "2026-09-18T09:14:02Z",
        "previous": "MCM00001607_SPEAKER_07"
     }}

speaker_ids.json has exactly three value shapes (see toid.py / propagate()):
    "Zac Bears"                    -- a human name; identified
    "SPEAKER_06"                   -- unmatched, unidentified
    "a17_UOV__Vs_SPEAKER_20"       -- MATCHED to another meeting's speaker,
                                       not yet named (a CLUSTER KEY)

The third shape is load-bearing: it is how the archive knows "same person
across N meetings" before knowing who. Nothing in this module ever removes
or collapses it.

`is_cluster_key` below duplicates the exact structural check propagate() uses
(len > 12 and character 11 is "_") rather than inventing a new one, so
provenance's idea of "cluster key" can never disagree with propagate()'s.

"previous" is what makes a bad propagation REVERSIBLE without restoring a
backup. A shared "from" makes the blast radius of one wrong match a QUERY
(find_by_from / revert, below) instead of a guess. "manual" is an ASSERTION
that a human set this value: it is written only by an explicit human command
(`mark-manual`, or opt-in backfill) and it is what propagate()'s guard checks
before it will overwrite anything.

WHO WRITES WHAT
    track_speakers.match_embeddings  -> "embedding_match" (score, from)
    track_speakers.propagate         -> "propagated"      (score of the
                                        source entry if known, from)
    python speaker_provenance.py mark-manual <yt_id> KEY...  -> "manual"
    python speaker_provenance.py backfill    -> "unknown" for everything
                                        that has no record yet
    "reference_voice" is reserved for track_speakers.match_to_reference2 /
    generate_reference_voices; not wired in this pass.

speaker_provenance.json must never be committed -- see .gitignore. It's
derived, per-meeting, and adds ~2,280 more tracked files if it were.
"""

import glob
import json
import os
import tempfile
from datetime import datetime, timezone

SOURCES = {"manual", "reference_voice", "embedding_match", "propagated", "unknown"}

PROVENANCE_FILENAME = "speaker_provenance.json"
SPEAKER_IDS_FILENAME = "speaker_ids.json"


# ---------------------------------------------------------------------------
# value classification -- mirrors the three shapes exactly, see module doc

def is_cluster_key(value):
    """True for the third shape: '<11-char yt_id>_<referenced speaker key>'.

    This is the SAME check propagate() uses (len(value) > 12 and
    value[11] == '_'), duplicated intentionally so the two can never drift
    apart. NEVER change this independently of track_speakers.propagate().
    """
    return isinstance(value, str) and len(value) > 12 and value[11] == "_"


def is_raw_speaker(value):
    """True for the unidentified shape: 'SPEAKER_06' verbatim."""
    return isinstance(value, str) and value.startswith("SPEAKER_") and not is_cluster_key(value)


def is_named(value):
    """True only for an actual human name -- neither of the other two shapes."""
    return isinstance(value, str) and not is_cluster_key(value) and not value.startswith("SPEAKER_")


# ---------------------------------------------------------------------------
# atomic I/O

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_json(path, data):
    """Write JSON via temp file + os.replace -- never leaves a half-written
    file, even if the process dies mid-write. Same indent=4 as every other
    writer of these files, so diffs stay one-line."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".provenance.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as fp:
            json.dump(data, fp, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def provenance_path(meeting_dir):
    return os.path.join(meeting_dir, PROVENANCE_FILENAME)


def speaker_ids_path(meeting_dir):
    return os.path.join(meeting_dir, SPEAKER_IDS_FILENAME)


def _read_json(path):
    with open(path, "r") as fp:
        return json.load(fp)


def load_provenance(meeting_dir):
    """The provenance dict for one meeting dir, or {} if missing/corrupt.

    Tolerant on read: a missing or unreadable sidecar must never block
    reading speaker_ids.json (callers all treat {} as "nothing known yet").
    """
    path = provenance_path(meeting_dir)
    if not os.path.exists(path):
        return {}
    try:
        data = _read_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_provenance(meeting_dir, data):
    atomic_write_json(provenance_path(meeting_dir), data)


def make_entry(value, source, score=None, from_=None, previous=None, at=None):
    if source not in SOURCES:
        raise ValueError("unknown provenance source: " + repr(source))
    return {
        "value": value,
        "source": source,
        "score": float(score) if score is not None else None,
        "from": from_,
        "at": at or now_iso(),
        "previous": previous,
    }


def record(meeting_dir, speaker_key, value, source, score=None, from_=None,
           previous=None, provenance=None):
    """Set one entry and persist it.

    If `provenance` (an already-loaded dict) is passed in, only the in-memory
    dict is mutated and the caller is responsible for saving -- this is what
    propagate()'s collect-then-commit needs so nothing hits disk until the
    whole pass has succeeded. Otherwise this loads, updates, and atomically
    saves in one call.
    """
    owns = provenance is None
    if provenance is None:
        provenance = load_provenance(meeting_dir)
    provenance[speaker_key] = make_entry(value, source, score=score, from_=from_, previous=previous)
    if owns:
        save_provenance(meeting_dir, provenance)
    return provenance


def is_manual(provenance, speaker_key):
    """The guard predicate propagate() uses: True only if this key has a
    recorded provenance whose source is exactly "manual"."""
    entry = provenance.get(speaker_key)
    return isinstance(entry, dict) and entry.get("source") == "manual"


# ---------------------------------------------------------------------------
# locating meeting directories

def yt_id_from_dir(meeting_dir):
    """'2024-09-20_MCM00001481' -> 'MCM00001481' (mirrors the split used
    throughout track_speakers.py, but via os.path so it isn't sensitive to
    the OS path separator)."""
    base = os.path.basename(os.path.normpath(meeting_dir))
    parts = base.split("_", 1)
    return parts[1] if len(parts) > 1 else base


def find_meeting_dir(yt_id, root="."):
    """The single meeting dir for a yt_id, using the same '*<yt_id>/' glob
    propagate() uses. Returns None unless exactly one matches."""
    hits = glob.glob(os.path.join(root, "*" + yt_id, SPEAKER_IDS_FILENAME))
    if len(hits) != 1:
        return None
    return os.path.normpath(os.path.dirname(hits[0]))


def _resolve_dir(target, root="."):
    """Accept either a meeting dir path or a bare yt_id."""
    if os.path.isdir(target):
        return target
    return find_meeting_dir(target, root=root)


# ---------------------------------------------------------------------------
# backfill

def load_manual_correction_ids(path="manual_corrections.json"):
    """yt_ids listed by find_manual_edits.py as containing hand-edited .srt
    TEXT. That is not the same thing as a hand-verified speaker name, which
    is why backfill() only consults this list when explicitly asked to."""
    if not os.path.exists(path):
        return set()
    try:
        data = _read_json(path)
    except (OSError, ValueError):
        return set()
    return set(data.get("ids", {}).keys())


def backfill(root=".", manual_corrections_path="manual_corrections.json",
             mark_manual_from_corrections=False):
    """Seed speaker_provenance.json for every existing speaker_ids.json.

    CONSERVATIVE BY DESIGN: every entry not already recorded gets source
    "unknown" -- we cannot tell how it was set, so we do not claim to.

    With mark_manual_from_corrections=True, a plain name (is_named) inside a
    video listed in manual_corrections.json is marked "manual" instead. This
    is OFF by default because that file records .srt text edits, not speaker
    naming: a name in one of those files may still have come from
    match_embeddings. It is the only upgrade permitted at all, and it is the
    operator's call to make.

    Idempotent and non-destructive: an entry that already has a provenance
    record (written by match_embeddings/propagate since this shipped, or by
    a previous backfill run) is never touched.
    """
    manual_ids = load_manual_correction_ids(manual_corrections_path) if mark_manual_from_corrections else set()
    pattern = os.path.join(root, "*", SPEAKER_IDS_FILENAME)

    summary = {
        "files_scanned": 0,
        "files_touched": 0,
        "files_unreadable": 0,
        "entries_unknown": 0,
        "entries_manual": 0,
    }

    for speaker_file in glob.glob(pattern):
        meeting_dir = os.path.normpath(os.path.dirname(speaker_file))
        summary["files_scanned"] += 1

        try:
            speaker_ids = _read_json(speaker_file)
        except (OSError, ValueError):
            summary["files_unreadable"] += 1
            continue
        if not isinstance(speaker_ids, dict):
            summary["files_unreadable"] += 1
            continue

        provenance = load_provenance(meeting_dir)
        yt_id = yt_id_from_dir(meeting_dir)
        changed = False

        for speaker_key, value in speaker_ids.items():
            if speaker_key in provenance:
                continue  # never clobber an existing record

            if is_named(value) and yt_id in manual_ids:
                source = "manual"
                summary["entries_manual"] += 1
            else:
                source = "unknown"
                summary["entries_unknown"] += 1

            provenance[speaker_key] = make_entry(value, source)
            changed = True

        if changed:
            save_provenance(meeting_dir, provenance)
            summary["files_touched"] += 1

    return summary


# ---------------------------------------------------------------------------
# drift / manual marking

def drift(meeting_dir):
    """Entries whose on-disk speaker_ids.json value differs from (or has no)
    provenance record -- i.e. was changed by something that did not record
    itself: a text editor, srt2html re-creation, an old script.

    Returns [{"speaker_key", "value", "recorded"}]. Report only; nothing is
    inferred from it automatically (see mark_manual)."""
    try:
        speaker_ids = _read_json(speaker_ids_path(meeting_dir))
    except (OSError, ValueError):
        return []
    provenance = load_provenance(meeting_dir)
    out = []
    for speaker_key, value in speaker_ids.items():
        entry = provenance.get(speaker_key)
        recorded = entry.get("value") if isinstance(entry, dict) else None
        if entry is None or recorded != value:
            out.append({"speaker_key": speaker_key, "value": value, "recorded": recorded})
    return out


def mark_manual(meeting_dir, speaker_keys):
    """Record the CURRENT on-disk value of each key as source "manual".

    This is the one deliberate path by which "manual" enters a sidecar going
    forward: a human edited speaker_ids.json and is now saying so. The value
    is read from disk, never passed in, so the record can't disagree with the
    file. Keys absent from speaker_ids.json are reported, not invented.
    """
    speaker_ids = _read_json(speaker_ids_path(meeting_dir))
    provenance = load_provenance(meeting_dir)
    marked, missing = [], []
    for speaker_key in speaker_keys:
        if speaker_key not in speaker_ids:
            missing.append(speaker_key)
            continue
        old = provenance.get(speaker_key, {})
        if old.get("value") != speaker_ids[speaker_key]:
            previous = old.get("value")
        else:
            previous = old.get("previous")
        provenance[speaker_key] = make_entry(speaker_ids[speaker_key], "manual", previous=previous)
        marked.append(speaker_key)
    if marked:
        save_provenance(meeting_dir, provenance)
    return {"marked": marked, "missing": missing}


# ---------------------------------------------------------------------------
# report / rollback

def _iter_provenance(root="."):
    for prov_file in glob.glob(os.path.join(root, "*", PROVENANCE_FILENAME)):
        try:
            provenance = _read_json(prov_file)
        except (OSError, ValueError):
            continue
        if isinstance(provenance, dict):
            yield os.path.normpath(os.path.dirname(prov_file)), provenance


def find_by_from(cluster_key, root="."):
    """Every provenance entry, anywhere in the archive, whose "from" is
    `cluster_key` -- the blast radius of one match against that cluster."""
    matches = []
    for meeting_dir, provenance in _iter_provenance(root):
        for speaker_key, entry in provenance.items():
            if isinstance(entry, dict) and entry.get("from") == cluster_key:
                matches.append({
                    "meeting_dir": meeting_dir,
                    "speaker_key": speaker_key,
                    "current_value": entry.get("value"),
                    "previous": entry.get("previous"),
                    "source": entry.get("source"),
                    "score": entry.get("score"),
                    "at": entry.get("at"),
                })
    return matches


def find_members(cluster_key, root="."):
    """Every speaker_ids.json entry whose VALUE is `cluster_key` -- the still
    unnamed members of that cluster. Reads speaker_ids.json directly so it
    works before any provenance exists."""
    members = []
    for speaker_file in glob.glob(os.path.join(root, "*", SPEAKER_IDS_FILENAME)):
        try:
            speaker_ids = _read_json(speaker_file)
        except (OSError, ValueError):
            continue
        if not isinstance(speaker_ids, dict):
            continue
        for speaker_key, value in speaker_ids.items():
            if value == cluster_key:
                members.append({"meeting_dir": os.path.normpath(os.path.dirname(speaker_file)), "speaker_key": speaker_key})
    return members


def report(cluster_key, root="."):
    """What one cluster key touches: the entries derived FROM it (provenance
    "from") and the entries still holding it as their VALUE."""
    return {
        "cluster_key": cluster_key,
        "derived": find_by_from(cluster_key, root=root),
        "members": find_members(cluster_key, root=root),
    }


def revert(cluster_key, root=".", apply=False, lock=False):
    """List (and, with apply=True, perform) reverting every entry traced to
    `cluster_key` back to its recorded "previous" value.

    Default is a dry run (apply=False): nothing is written, only reported.

    Safety: an entry is only reverted if its on-disk speaker_ids.json value
    still equals the recorded provenance value. If something (a human editor)
    changed it since, it is skipped and reported -- revert never clobbers an
    edit it didn't record.

    Reverted entries are re-recorded with source "unknown" (previous = the bad
    value, from = None). They are NOT marked "manual" by default: "previous"
    is usually a cluster key, and marking it manual would freeze it out of
    propagation forever, so after the root cause (the entry that first gave
    the cluster its bad name) is fixed, the next propagate() could never
    deliver the corrected name. With lock=True they are marked "manual"
    instead, which is what you want when the cluster key itself is wrong and
    should never be followed again.
    """
    matches = find_by_from(cluster_key, root=root)
    report_rows = []
    source = "manual" if lock else "unknown"

    for m in matches:
        meeting_dir = m["meeting_dir"]
        speaker_key = m["speaker_key"]
        previous = m["previous"]
        row = dict(m)

        if previous is None:
            row["status"] = "skipped: no previous value recorded"
            report_rows.append(row)
            continue

        speaker_file = speaker_ids_path(meeting_dir)
        try:
            speaker_ids = _read_json(speaker_file)
        except (OSError, ValueError):
            row["status"] = "skipped: speaker_ids.json unreadable"
            report_rows.append(row)
            continue

        on_disk = speaker_ids.get(speaker_key)
        if on_disk != m["current_value"]:
            row["status"] = "skipped: on-disk value " + repr(on_disk) + " differs from recorded"
            report_rows.append(row)
            continue

        row["status"] = "reverted" if apply else "would revert"
        report_rows.append(row)

        if apply:
            speaker_ids[speaker_key] = previous
            atomic_write_json(speaker_file, speaker_ids)

            provenance = load_provenance(meeting_dir)
            provenance[speaker_key] = make_entry(previous, source, previous=on_disk, from_=None)
            save_provenance(meeting_dir, provenance)

    return report_rows


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="speaker_ids.json provenance: seed, report, rollback")
    sub = parser.add_subparsers(dest="command")

    p_backfill = sub.add_parser("backfill", help="seed provenance ('unknown') for existing speaker_ids.json files")
    p_backfill.add_argument("--manual-from-corrections", action="store_true",
                            help="also mark plain names in manual_corrections.json videos as 'manual' (opt-in)")

    p_report = sub.add_parser("report", help="list entries derived from a cluster key, and its unnamed members")
    p_report.add_argument("cluster_key")

    p_revert = sub.add_parser("revert", help="revert entries derived from a cluster key to their previous value")
    p_revert.add_argument("cluster_key")
    p_revert.add_argument("--apply", action="store_true", help="write the revert (default: dry run, report only)")
    p_revert.add_argument("--lock", action="store_true", help="mark reverted entries 'manual' so propagate() never touches them again")

    p_drift = sub.add_parser("drift", help="entries whose speaker_ids.json value differs from its provenance record")
    p_drift.add_argument("target", help="meeting dir or yt_id")

    p_manual = sub.add_parser("mark-manual", help="record the current value of KEY(s) as hand-verified")
    p_manual.add_argument("target", help="meeting dir or yt_id")
    p_manual.add_argument("keys", nargs="+", metavar="KEY", help="e.g. SPEAKER_04")

    args = parser.parse_args()

    if args.command == "backfill":
        print(json.dumps(backfill(mark_manual_from_corrections=args.manual_from_corrections), indent=2))
    elif args.command == "report":
        print(json.dumps(report(args.cluster_key), indent=2))
    elif args.command == "revert":
        for m in revert(args.cluster_key, apply=args.apply, lock=args.lock):
            print(m)
    elif args.command in ("drift", "mark-manual"):
        meeting_dir = _resolve_dir(args.target)
        if meeting_dir is None:
            parser.exit(1, "no single meeting dir matches " + repr(args.target) + "\n")
        if args.command == "drift":
            for row in drift(meeting_dir):
                print(row)
        else:
            print(json.dumps(mark_manual(meeting_dir, args.keys), indent=2))
    else:
        parser.print_help()
