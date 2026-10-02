"""Push the sitemap's URLs to IndexNow (Bing, Yandex, Seznam, Naver).

WHY THIS EXISTS. Google has never fetched either sitemap: both have sat
isPending with zero errors since 2026-09-18 and 2026-09-21, and the URL
Inspection API reports "URL is unknown to Google" for ordinary transcript
pages. Everything indexed today arrived through a Reddit link or a manual
submission in Search Console, so roughly 2,300 pages are invisible.

IndexNow does not depend on a sitemap being read. You POST the URLs and the
engine fetches them, which is exactly the failure mode we are working around.
It is one protocol shared by Bing, Yandex, Seznam and Naver, and needs no
account -- ownership is proven by hosting a key file on the site itself.

NOT GOOGLE. Google does not participate in IndexNow, and its own Indexing API
accepts only JobPosting and BroadcastEvent, neither of which these pages are.
Claiming otherwise to get them crawled would be misrepresenting the content.

    python submit_indexnow.py             # show what would be sent
    python submit_indexnow.py --submit    # actually send
"""

import argparse
import io
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

HOST = "medford-transcripts.github.io"
SITE = "https://%s/" % HOST
KEY_FILE = "indexnow_key.txt"          # the key, kept beside the code
ENDPOINT = "https://api.indexnow.org/indexnow"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BATCH = 10000                          # the protocol's documented maximum


def load_key(path=KEY_FILE):
    try:
        k = io.open(path, encoding="utf-8").read().strip()
    except OSError:
        raise SystemExit(
            "no key at %s. Generate one with:\n"
            "    python -c \"import secrets,io;"
            "io.open('%s','w').write(secrets.token_hex(16))\"\n"
            "then commit it AND the <key>.txt file at the site root."
            % (path, path))
    if not re.match(r"^[A-Za-z0-9-]{8,128}$", k):
        raise SystemExit("key must be 8-128 chars of [A-Za-z0-9-]; got %r" % k[:20])
    return k


def sitemap_urls(path="sitemap.xml"):
    root = ET.parse(path).getroot()
    return [u.find("s:loc", NS).text for u in root.findall("s:url", NS)
            if u.find("s:loc", NS) is not None]


def key_is_live(key):
    """IndexNow verifies ownership by fetching <host>/<key>.txt.

    Checked BEFORE submitting, because a submission made while the key file is
    missing is rejected wholesale and there is no partial credit -- and the file
    only goes live after a deploy, which is a step it is easy to forget.
    """
    url = "%s%s.txt" % (SITE, key)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "medford-transcripts"})
        body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8").strip()
    except Exception as e:
        return False, "%s (%s)" % (url, str(e)[:60])
    if body != key:
        return False, "%s served %r, expected the key" % (url, body[:40])
    return True, url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="actually POST")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    key = load_key()
    urls = sitemap_urls()
    if args.limit:
        urls = urls[:args.limit]
    print("host    : %s" % HOST)
    print("key     : %s...%s" % (key[:4], key[-4:]))
    print("urls    : %d" % len(urls))

    live, detail = key_is_live(key)
    print("key file: %s" % ("LIVE at " + detail if live else "NOT REACHABLE -- " + detail))
    if not live:
        print()
        print("Commit %s.txt to the repo root containing exactly the key," % key)
        print("push, wait for Pages to deploy, then run this again.")
        return 1

    if not args.submit:
        print()
        print("dry run. first 3:")
        for u in urls[:3]:
            print("   %s" % u)
        print("pass --submit to send")
        return 0

    sent = 0
    for i in range(0, len(urls), BATCH):
        chunk = urls[i:i + BATCH]
        body = json.dumps({"host": HOST, "key": key,
                           "keyLocation": "%s%s.txt" % (SITE, key),
                           "urlList": chunk}).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                # 200 accepted, 202 accepted pending key validation
                print("batch %d: %d urls -> HTTP %s" % (i // BATCH + 1, len(chunk), r.status))
                sent += len(chunk)
        except Exception as e:
            print("batch %d: FAILED %s" % (i // BATCH + 1, str(e)[:120]))
    print("submitted %d of %d" % (sent, len(urls)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
