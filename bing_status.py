"""Bing Webmaster indexing status, which IndexNow itself cannot report.

An IndexNow submission answers HTTP 200 for "accepted", never for "crawled" or
"indexed" -- it is fire and forget. Bing Webmaster Tools is the only place the
outcome shows up, so this is how we find out whether a submission did anything.

THE BASELINE, taken 2026-10-02 just after submitting 2,363 urls:

    date         2xx   blocked   InIndex
    2026-09-24  2006       192      1921
    2026-09-27  1990       192      1907
    2026-09-30  1963       193      1869

Bing had indexed most of the corpus on its own -- about 1,869 pages against the
few dozen urls Google knows -- but was LOSING roughly 8 to 10 a day. Whether that
decline flattens or reverses is the measurement the submission was for.

BlockedByRobotsTxt around 193 is ours and is correct: robots.txt disallows *.srt
and *.json, which are the raw transcript and data files behind each page.

    python bing_status.py              # trend plus a url sample
    python bing_status.py --days 30
"""

import argparse
import datetime
import io
import json
import re
import urllib.parse
import time
import urllib.request

KEY_FILE = "credentials/bing_key.txt"
SITE = "https://medford-transcripts.github.io/"
BASE = "https://ssl.bing.com/webmaster/api.svc/json/"
EPOCH_MIN = -62135596800000          # .NET DateTime.MinValue: "we have nothing"


def load_key(path=KEY_FILE):
    try:
        return io.open(path, encoding="utf-8").read().strip()
    except OSError:
        raise SystemExit(
            "no Bing key at %s. Bing Webmaster Tools -> Settings -> API access."
            % path)


def call(method, key, **params):
    params["apikey"] = key
    url = BASE + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "medford-transcripts/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")).get("d")


def when(value):
    """.NET /Date(ms)/ to a date string, or None when it is MinValue."""
    m = re.search(r"/Date\((-?\d+)\)/", str(value) or "")
    if not m:
        return None
    ms = int(m.group(1))
    if ms <= EPOCH_MIN:
        return None                  # Bing holds no record for this url
    return datetime.datetime.utcfromtimestamp(ms / 1000.0).strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--sample", type=int, default=6)
    args = ap.parse_args()
    key = load_key()

    q = call("GetUrlSubmissionQuota", key, siteUrl=SITE) or {}
    print("submission quota: %s/day, %s/month"
          % (q.get("DailyQuota"), q.get("MonthlyQuota")))
    print()

    stats = call("GetCrawlStats", key, siteUrl=SITE) or []
    rows = stats[-args.days:]
    print("%-12s %7s %7s %8s %9s %9s" % ("date", "2xx", "4xx", "blocked",
                                         "crawled", "InIndex"))
    prev = None
    for r in rows:
        idx = r.get("InIndex")
        delta = "" if prev is None or idx is None else " %+d" % (idx - prev)
        print("%-12s %7s %7s %8s %9s %9s%s"
              % (when(r.get("Date")) or "?", r.get("Code2xx"), r.get("Code4xx"),
                 r.get("BlockedByRobotsTxt"), r.get("CrawledPages"), idx, delta))
        prev = idx if idx is not None else prev

    traffic = call("GetRankAndTrafficStats", key, siteUrl=SITE) or []
    recent = [t for t in traffic[-args.days:] if t.get("Impressions")]
    tot_i = sum(t.get("Impressions") or 0 for t in traffic[-args.days:])
    tot_c = sum(t.get("Clicks") or 0 for t in traffic[-args.days:])
    print()
    print("last %d days: %d impressions, %d clicks (%d days with any impression)"
          % (args.days, tot_i, tot_c, len(recent)))

    # Per-url: did a specific page make it in? A url Bing has never seen comes
    # back with DateTime.MinValue rather than an error, which reads as a date
    # in year 1 if you do not check for it.
    try:
        import xml.etree.ElementTree as ET
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [u.find("s:loc", ns).text
                for u in ET.parse("sitemap.xml").getroot().findall("s:url", ns)]
    except Exception:
        locs = []
    if locs:
        step = max(1, len(locs) // args.sample)
        print()
        print("%-54s %-12s %s" % ("url", "discovered", "last crawled"))
        for u in locs[::step][:args.sample]:
            # Bing answers 503 to rapid GetUrlInfo calls; one a second is fine.
            time.sleep(1.0)
            try:
                d = call("GetUrlInfo", key, siteUrl=SITE, url=u) or {}
            except Exception as e:
                print("%-54s ERROR %s" % (u[-54:], str(e)[:40]))
                continue
            disc, crawl = when(d.get("DiscoveryDate")), when(d.get("LastCrawledDate"))
            print("%-54s %-12s %s" % (u.replace(SITE, "/")[-54:],
                                      disc or "never", crawl or "never"))


if __name__ == "__main__":
    main()
