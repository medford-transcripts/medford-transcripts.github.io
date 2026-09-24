"""
Sync provenance artifacts into the private transcript_backup repo, and report
how far the two have drifted.

WHY THIS EXISTS. The backup holds the only copies of things that cannot be
regenerated: model.pkl and embeddings.pkl (the ASR and diarization halves of a
two-year run), and speaker_ids.json, which is pure human judgement -- nothing
rebuilds a voice-cluster-to-real-name map from anything.

It was populated by hand on 2026-09-17/18 and then nothing kept it current. By
2026-09-23 the live tree had 2,301 speaker_ids.json against 2,275 in the
backup, and 339 had changed since the last sync. The guarantee held only as
long as someone remembered, and nothing reported the gap.

THE DRIFT CHECK IS THE POINT, more than the copying. A backup nobody measures
is a belief, not a backup. `drift` answers "what would be lost right now" and
is cheap enough to run on every pipeline pass; `sync` is what you do about it.

Usage:
    python backup_sync.py                 # report drift, change nothing
    python backup_sync.py --apply         # copy changed/new files
    python backup_sync.py --apply --commit
"""

import argparse
import glob
import io
import os
import shutil
import subprocess
import sys

BACKUP = os.path.join("..", "transcript_backup")

# Per meeting. Two rules: it must be IRRECOVERABLE (regenerating it costs
# GPU-months, or it encodes a human decision), and it must not be publishable
# (voiceprints are biometric; speaker_ids maps clusters to real names).
ARTIFACTS = ("{base}.srt", "{base}.srt.orig", "{base}_aligned.srt",
             "{base}_basic.srt", "speaker_ids.json", "speaker_provenance.json",
             "model.pkl", "embeddings.pkl")


def meeting_dirs():
    return sorted(d for d in glob.glob("20??-??-??_*") if os.path.isdir(d))


def plan(backup=BACKUP):
    """[(src, dest, why)] for everything out of date, plus counts."""
    todo, same, missing_dirs = [], 0, 0
    for d in meeting_dirs():
        base = os.path.basename(d)
        dest_dir = os.path.join(backup, base)
        # count a meeting as absent only if it HAS artifacts and none are
        # backed up -- ~718 directories hold no transcript at all (download
        # started, never finished), and reporting those as missing invents a
        # problem and buries the real one.
        had_any = False
        for pattern in ARTIFACTS:
            name = pattern.format(base=base)
            src = os.path.join(d, name)
            if not os.path.exists(src):
                continue
            had_any = True
            dest = os.path.join(dest_dir, name)
            if not os.path.exists(dest):
                todo.append((src, dest, "new"))
            elif (os.path.getsize(src) != os.path.getsize(dest)
                  or os.path.getmtime(src) > os.path.getmtime(dest) + 1):
                todo.append((src, dest, "changed"))
            else:
                same += 1
        if had_any and not os.path.isdir(dest_dir):
            missing_dirs += 1
    return todo, same, missing_dirs


def drift(backup=BACKUP):
    """Print what the backup is missing. Returns the number of stale files."""
    if not os.path.isdir(backup):
        print("NO BACKUP REPO at %s -- nothing is protected" % backup)
        return -1
    todo, same, missing_dirs = plan(backup)
    new = sum(1 for _, _, w in todo if w == "new")
    chg = len(todo) - new
    print("backup: %s" % os.path.abspath(backup))
    print("  up to date : %d files" % same)
    print("  CHANGED    : %d" % chg)
    print("  NEW        : %d  (%d meetings absent entirely)" % (new, missing_dirs))
    if todo:
        by_kind = {}
        for src, _, _ in todo:
            k = os.path.basename(src)
            k = "speaker_ids.json" if k == "speaker_ids.json" else (
                "model/embeddings.pkl" if k.endswith(".pkl") else
                "speaker_provenance.json" if k.startswith("speaker_prov") else ".srt*")
            by_kind[k] = by_kind.get(k, 0) + 1
        print("  by kind    :", by_kind)
        irrecoverable = sum(v for k, v in by_kind.items()
                            if k in ("speaker_ids.json", "model/embeddings.pkl"))
        if irrecoverable:
            print("  %d of those are IRRECOVERABLE if this machine dies today"
                  % irrecoverable)
    return len(todo)


def sync(backup=BACKUP, apply=False, commit=False):
    todo, same, _ = plan(backup)
    print("%d files to copy (%d already current)" % (len(todo), same))
    if not apply:
        for src, _, why in todo[:12]:
            print("   %-8s %s" % (why, src))
        if len(todo) > 12:
            print("   ... and %d more" % (len(todo) - 12))
        print("\ndry run; pass --apply")
        return len(todo)
    n = 0
    for src, dest, _ in todo:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        n += 1
        if n % 200 == 0:
            print("   ...%d/%d" % (n, len(todo)))
            sys.stdout.flush()
    print("copied %d files" % n)
    if commit and n:
        subprocess.run(["git", "add", "-A"], cwd=backup)
        msg = "Sync %d provenance artifacts from the main repo" % n
        if subprocess.run(["git", "commit", "-m", msg], cwd=backup).returncode:
            print("COMMIT FAILED -- files are copied but only on this machine")
            return n
        # -u because a fresh clone may have no upstream set: plain `git push`
        # then fails with "no upstream branch" and the old code ignored the
        # result and printed success anyway. A backup tool that misreports a
        # push is worse than one that does not push, because it converts a
        # known gap into an assumed safety.
        if subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=backup).returncode:
            print("PUSH FAILED -- committed locally, NOT on the remote")
            return n
        # confirm against the REMOTE, not the cached origin/ ref, which is only
        # as fresh as the last fetch and reported "0 unpushed" while a commit
        # sat unpushed.
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=backup,
                              capture_output=True, text=True).stdout.strip()
        ls = subprocess.run(["git", "ls-remote", "origin", "HEAD"], cwd=backup,
                            capture_output=True, text=True).stdout.split()
        if ls and ls[0] == head:
            print("committed and pushed; remote confirmed at %s" % head[:9])
        else:
            print("PUSH REPORTED OK BUT REMOTE IS AT %s, NOT %s"
                  % ((ls[0][:9] if ls else "?"), head[:9]))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", default=BACKUP)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        drift(args.backup)
        print()
    sync(args.backup, apply=args.apply, commit=args.commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
