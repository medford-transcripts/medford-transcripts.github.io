#!/bin/sh
# One SHORT process per meeting, not one long one: srt2html -f redoes the
# nine-language translation per page and a single long run is what has been
# OOM-killed repeatedly (RESUME.md). A per-id process frees its memory at
# exit, and the loop is resumable -- rerun and it skips pages already current.
PY="C:/Users/jdeas/AppData/Local/Programs/Python/Python311/python.exe"
n=0
while read -r id; do
  [ -z "$id" ] && continue
  "$PY" srt2html.py -i "$id" -f >> logs/regen_stale.log 2>&1
  n=$((n+1))
  echo "$(date +%H:%M:%S) done $n $id" >> logs/regen_stale.progress
done < regen_now.txt
echo "$(date +%H:%M:%S) FINISHED $n pages" >> logs/regen_stale.progress
