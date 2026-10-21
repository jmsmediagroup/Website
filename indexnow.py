#!/usr/bin/env python3
"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver) about new or changed pages.

    python3 indexnow.py                     submit every URL in sitemap.xml
    python3 indexnow.py /blog/some-post/    submit specific paths

Run it after a deploy has gone live, since the engines fetch the key file from
the live site to verify the submission. Bing's index also feeds ChatGPT search
and Copilot, so this is the fastest way to get new pages in front of them.
Google does not take part in IndexNow; submit the sitemap in Search Console.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
HOST = "jmstruijk.com"
SITE = "https://" + HOST
KEY = "6f136448afb448c3b01ece01bac2a530"


def sitemap_urls():
    text = open(os.path.join(ROOT, "sitemap.xml"), encoding="utf-8").read()
    return re.findall(r"<loc>([^<]+)</loc>", text)


def main():
    if not os.path.exists(os.path.join(ROOT, KEY + ".txt")):
        sys.exit("indexnow.py: key file %s.txt is missing from the repo root." % KEY)

    urls = [SITE + p if p.startswith("/") else p for p in sys.argv[1:]] or sitemap_urls()
    payload = {"host": HOST, "key": KEY, "keyLocation": "%s/%s.txt" % (SITE, KEY), "urlList": urls}
    request = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print("IndexNow accepted %d URLs (HTTP %d)" % (len(urls), response.status))
    except urllib.error.HTTPError as e:
        # 403: key not found on the live site yet; 422: URLs not on this host.
        sys.exit("IndexNow rejected the submission: HTTP %d %s" % (e.code, e.read().decode()[:300]))


if __name__ == "__main__":
    main()
