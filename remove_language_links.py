"""
Remove the language-switcher nav from already-generated English pages.

The per-language transcript copies are retired (srt2html.TRANSLATIONS_DISABLED)
and no longer tracked by git, so they are not published. The English pages
still carry a nav bar linking to all ten of them:

    <a href="X.html">English</a> | <a href="X.es.html">espanol</a> | ... <br><br>

Left in place those become ten 404s on every transcript page. The generator no
longer emits the bar; this strips it from pages already written, in place, on
bytes, without regenerating (which would be pointless anyway now that there is
nothing to translate).

Usage:
    python remove_language_links.py            # dry run
    python remove_language_links.py --apply
"""

import argparse
import os
import re
import sys

from srt2html import is_translated_page

LANGS = "es|pt|pt-BR|zh-cn|ht|vi|km|ru|ar|ko"

# the whole run: the English self-link followed by one or more " | <a ...>"
# entries pointing at a retired language page, then the trailing <br><br>
NAV_RE = re.compile(
    rb'<a href="[^"]*\.html">English</a>'
    rb'(?:\s*\|\s*<a href="[^"]*\.(?:' + LANGS.encode() + rb')\.html">[^<]*</a>)+'
    rb'<br><br>\r?\n?'
)

SKIP_DIRS = {
    ".git", "__pycache__", "archive", "voices_folder", "clips", "headshots",
    "medford_tmp", "scratch", "node_modules", "jotaemei_videos",
    "models--Systran--faster-whisper-large-v2",
    "models--Systran--faster-whisper-large-v3",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    if not args.apply:
        print("=== DRY RUN -- nothing will be written (use --apply) ===\n")

    examined = changed = 0
    samples = []

    for dirpath, dirnames, filenames in os.walk(args.root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".html"):
                continue
            # the retired pages are untracked and unpublished; don't waste
            # time rewriting them, and leave them intact for recovery
            if is_translated_page(name):
                continue

            full = os.path.join(dirpath, name)
            examined += 1

            with open(full, "rb") as fp:
                data = fp.read()

            if b">English</a>" not in data:
                continue

            patched, n = NAV_RE.subn(b"", data)
            if not n:
                continue

            changed += 1
            if len(samples) < 3:
                m = NAV_RE.search(data)
                snippet = m.group(0)[:150].decode("utf-8", "replace")
                samples.append((os.path.relpath(full, args.root), snippet))

            if args.apply:
                tmp = full + ".navfix.tmp"
                with open(tmp, "wb") as fp:
                    fp.write(patched)
                os.replace(tmp, full)

    print("english pages examined :", examined)
    print("nav bars removed       :", changed)
    if samples:
        print("\nremoved (truncated):")
        for rel, snip in samples:
            print("  ", rel)
            print("     ", snip, "...")
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
