"""
Add a proper <head> with noindex to the already-generated electeds/ pages.

WHY NOINDEX: every excerpt on these pages is DUPLICATE text -- it already
appears on the transcript page it links to. Their purpose is to be fed to an
LLM to synthesise a candidate profile, not to be read by people or ranked.
Asking Google to index 125 pages of duplicated transcript (one of them 13 MB)
dilutes the domain exactly the way the machine-translated copies did.

"follow" is kept, so the links out to the real transcript pages still pass
value. The pages stay published and linked -- they are simply not advertised
for indexing, and make_sitemap now excludes them.

WHY PATCH RATHER THAN REGENERATE: supercut.py now emits this head, but
regenerating the pages means re-running supercut for every official, which
scans all 2,272 transcripts per person -- about three hours. The head is a
pure prepend, so patching is seconds and byte-identical in the body.

These files had NO head at all: they began mid-document with the wordcloud
image, which is malformed HTML and left nowhere to put a directive.

Usage:
    python add_electeds_noindex.py            # dry run
    python add_electeds_noindex.py --apply
"""

import argparse
import glob
import io
import os
import sys
from html import escape


def head_for(speaker):
    return (
        '<!DOCTYPE html>\n<html lang="en">\n  <head>\n'
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '    <meta name="robots" content="noindex,follow">\n'
        '    <title>' + escape(speaker) + ' - transcript excerpts</title>\n'
        '  </head>\n  <body>\n'
        '    <h1>' + escape(speaker) + '</h1>\n'
        '    <p>Every excerpt below also appears on the linked transcript page. '
        'This page collects one speaker\'s words for analysis; it is not indexed.</p>\n'
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    patched = already = 0
    for path in sorted(glob.glob("electeds/*.html")):
        with io.open(path, encoding="utf-8", errors="replace") as fp:
            body = fp.read()

        if "noindex" in body[:800]:
            already += 1
            continue

        speaker = os.path.splitext(os.path.basename(path))[0]
        new = head_for(speaker) + body
        if not body.rstrip().endswith("</html>"):
            new = new + "\n  </body>\n</html>\n"

        patched += 1
        if patched <= 3:
            print("  %s  (%.0f KB)" % (path, len(body) / 1024))

        if args.apply:
            tmp = path + ".noindex.tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="") as fp:
                fp.write(new)
            os.replace(tmp, path)

    print("\npages patched        :", patched)
    print("already had noindex  :", already)
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
