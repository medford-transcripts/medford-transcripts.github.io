"""
Validate sitemap.xml against the site on disk.

Checks:
  - well-formed XML, correct namespace
  - no backslashes or other malformed URLs
  - every <loc> resolves to a file that actually exists (no 404s advertised)
  - every published English transcript page is listed (no orphans)
  - lastmod values are parseable and not in the future
  - size / URL count against Google's 50,000 URL and 50 MB limits
  - composition: how much of the crawl budget goes to translated duplicates

Usage: python check_sitemap.py
"""

import datetime
import glob
import os
import sys
from urllib.parse import unquote
from xml.etree import ElementTree

from site_url import SITE_ROOT

SITEMAP = "sitemap.xml"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

MAX_URLS = 50000
MAX_BYTES = 50 * 1024 * 1024

LANG_SUFFIXES = (".es", ".pt", ".zh-cn", ".ht", ".vi", ".km", ".ru", ".ar",
                 ".ko", ".pt-BR")


def main():
    if not os.path.exists(SITEMAP):
        print("MISSING", SITEMAP)
        return 1

    size = os.path.getsize(SITEMAP)
    print("sitemap.xml: %.2f MB" % (size / 1048576.0))

    try:
        tree = ElementTree.parse(SITEMAP)
    except ElementTree.ParseError as e:
        print("!! NOT WELL-FORMED XML:", e)
        return 1
    print("well-formed XML: yes")

    root = tree.getroot()
    if not root.tag.endswith("urlset"):
        print("!! root element is", root.tag, "- expected urlset")

    locs = []
    bad_lastmod = []
    now = datetime.datetime.now(datetime.timezone.utc)

    for url in root.findall(NS + "url"):
        loc_el = url.find(NS + "loc")
        if loc_el is None or not (loc_el.text or "").strip():
            print("!! <url> with no <loc>")
            continue
        loc = loc_el.text.strip()
        locs.append(loc)

        lm = url.find(NS + "lastmod")
        if lm is not None and lm.text:
            try:
                t = datetime.datetime.strptime(lm.text.strip(),
                                               "%Y-%m-%dT%H:%M:%SZ")
                t = t.replace(tzinfo=datetime.timezone.utc)
                if t > now + datetime.timedelta(days=1):
                    bad_lastmod.append((loc, lm.text))
            except ValueError:
                bad_lastmod.append((loc, lm.text))

    print("urls:", len(locs))

    # --- malformed ---
    backslash = [u for u in locs if "\\" in u]
    offsite = [u for u in locs if not u.startswith(SITE_ROOT)]
    dupes = len(locs) - len(set(locs))

    # --- do they exist on disk? ---
    missing = []
    for u in locs:
        rel = u[len(SITE_ROOT):] if u.startswith(SITE_ROOT) else None
        if rel is None:
            continue
        rel = rel.split("#")[0].split("?")[0]
        # <loc> is URL-escaped per the sitemap spec (site_url percent-encodes
        # spaces), so decode before testing the filesystem
        rel = unquote(rel)
        if rel == "":
            rel = "index.html"
        if not os.path.exists(rel.replace("/", os.sep)):
            missing.append(u)

    # --- published English transcripts not listed? ---
    listed = set(locs)
    orphans = []
    for d in sorted(glob.glob("20??-??-??_*")):
        if not os.path.isdir(d):
            continue
        page = os.path.join(d, d + ".html")
        if os.path.exists(page):
            want = SITE_ROOT + d + "/" + d + ".html"
            if want not in listed:
                orphans.append(want)

    # --- composition ---
    translated = sum(1 for u in locs
                     if any(u.endswith(s + ".html") for s in LANG_SUFFIXES))
    heatmaps = sum(1 for u in locs if u.endswith("/heatmap.html"))

    print()
    print("LIMITS")
    print("  under 50,000 urls :", "yes" if len(locs) <= MAX_URLS else "NO")
    print("  under 50 MB       :", "yes" if size <= MAX_BYTES else "NO")
    print()
    print("CORRECTNESS")
    print("  backslash urls    :", len(backslash), "<-- must be 0")
    print("  off-site urls     :", len(offsite))
    print("  duplicate urls    :", dupes)
    print("  listed but MISSING on disk:", len(missing), "<-- these 404")
    print("  on disk but NOT listed    :", len(orphans))
    print()
    print("COMPOSITION")
    print("  translated variants:", translated,
          "(%.0f%%)" % (100.0 * translated / len(locs)) if locs else "")
    print("  per-video heatmaps :", heatmaps)
    print("  everything else    :", len(locs) - translated - heatmaps)
    print()
    print("  bad/future lastmod :", len(bad_lastmod))

    for label, items in (("BACKSLASH", backslash), ("MISSING", missing),
                         ("NOT LISTED", orphans), ("BAD LASTMOD",
                                                   [a for a, _ in bad_lastmod])):
        if items:
            print("\n%s (first 10):" % label)
            for x in items[:10]:
                print("   ", x)

    problems = len(backslash) + len(missing) + len(offsite) + dupes
    print("\nVERDICT:", "sitemap is clean" if problems == 0 and not orphans
          else "sitemap has issues (see above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
