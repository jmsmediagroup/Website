#!/usr/bin/env python3
"""Bring the site in line with the book library.

    python3 sync_library.py            copy what changed
    python3 sync_library.py --all      redo every cover and motif

The books and the site share one source of truth: library.yaml in the ADHD and
autism build folder (titles, locked subtitles, series, groups, roles, pitches,
live formats with ASINs and ISBNs, the toolkit text), with covers.yaml for the
series colours and motifs. This script reads both and writes:

  content/library.json           what build.py reads about every book (never edit by hand)
  assets/covers/<site_slug>.jpg  700 px wide master of the new Kindle front, plus -400.jpg
                                 and the AVIF/WebP sizes (make_cover_images.py)
  assets/motifs/<site_slug>.svg  the book's line-drawing motif, drawn by the same code as the cover

Run it whenever a title, format, pitch or cover changes, then run build.py. The
build refuses to run if a book page has no library entry or the other way round,
so the site and the books cannot drift apart unnoticed.
"""

import glob
import json
import os
import re
import subprocess
import sys

import yaml
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
LIBRARY = os.environ.get("JMS_LIBRARY", "/Users/johan/Projects/03_Books/01_ADHD_and_Autism")
BUILD = os.path.join(LIBRARY, "00_Build")
OUT_JSON = os.path.join(ROOT, "content", "library.json")
COVERS = os.path.join(ROOT, "assets", "covers")
MOTIFS = os.path.join(ROOT, "assets", "motifs")
MASTER_W = 700


def fail(msg):
    sys.exit("sync_library.py: " + msg)


def theme_for(book, covers):
    series = book.get("series") or ""
    theme = next((dict(t) for t in covers["series"].values() if t["match"] == series), None)
    key = next((k for k, t in covers["series"].items() if t["match"] == series), "standalone")
    if theme is None:
        theme = dict(covers["series"]["standalone"])
    cfg = covers["books"].get(book["slug"], {})
    for k in ("bg", "ink", "soft", "accent", "motif"):
        if k in cfg:
            theme[k] = cfg[k]
    theme["key"] = key
    return theme


def find_cover(book):
    title = re.sub(r"[^A-Za-z0-9]+", "_", book["title"]).strip("_").lower()
    for path in glob.glob(os.path.join(LIBRARY, "*", "*", "03_Cover", "new-2026-11", "kindle-front.jpg")):
        folder = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        if re.sub(r"^\d+_", "", folder).lower() == title:
            return path
    return None


def write_cover(src, slug, force):
    """700 px master and 400 px JPEG; the AVIF/WebP sizes come from make_cover_images.py."""
    master = os.path.join(COVERS, slug + ".jpg")
    if not force and os.path.exists(master) and os.path.getmtime(master) >= os.path.getmtime(src):
        return False
    image = Image.open(src).convert("RGB")
    for width, out in ((MASTER_W, master), (400, os.path.join(COVERS, slug + "-400.jpg"))):
        height = round(image.height * width / image.width)
        image.resize((width, height), Image.LANCZOS).save(out, "JPEG", quality=86, optimize=True, progressive=True)
    # Old variants were made from the previous cover; remove them so they are rebuilt.
    for old in glob.glob(os.path.join(COVERS, slug + "-*.avif")) + glob.glob(os.path.join(COVERS, slug + "-*.webp")):
        os.remove(old)
    return True


def write_motif(book, theme, force):
    """The cover's motif as a small SVG panel in the series colours, drawn by build_covers.py itself."""
    out = os.path.join(MOTIFS, book["site_slug"] + ".svg")
    sys.path.insert(0, os.path.join(BUILD, "tools"))
    import build_covers as BC  # noqa: E402  (the cover builder; imports figlib and library.py)

    w, h = 450.0, 300.0
    s = w / (6 * BC.PT)
    c = BC.Canvas(w, h)
    c.rect(0, 0, w, h, theme["bg"])
    c.begin_clip(0, 0, w, h)
    BC.MOTIFS[theme["motif"]](c, (0, 22, w, h - 44), 40, w - 40, theme, s)
    c.end_group()
    svg = c.svg()
    svg = re.sub(r'width="[\d.]+in" height="[\d.]+in" ', 'width="450" height="300" ', svg)
    # One decimal is plenty at web sizes and halves the file.
    svg = re.sub(r"(\d+\.\d)\d+", r"\1", svg)
    svg = svg.replace('text-rendering="geometricPrecision"', 'role="img" aria-hidden="true"')
    if not force and os.path.exists(out) and open(out, encoding="utf-8").read() == svg:
        return False
    open(out, "w", encoding="utf-8").write(svg)
    return True


def main():
    force = "--all" in sys.argv[1:]
    lib = yaml.safe_load(open(os.path.join(BUILD, "library.yaml"), encoding="utf-8"))
    covers = yaml.safe_load(open(os.path.join(BUILD, "covers.yaml"), encoding="utf-8"))
    os.makedirs(COVERS, exist_ok=True)
    os.makedirs(MOTIFS, exist_ok=True)

    books, new_covers, new_motifs = [], 0, 0
    for b in lib["books"]:
        for key in ("slug", "site_slug", "group", "role", "title", "pitch", "formats"):
            if not b.get(key):
                fail("library.yaml book %s has no %s." % (b.get("slug"), key))
        theme = theme_for(b, covers)
        src = find_cover(b)
        if not src:
            fail("no new-2026-11/kindle-front.jpg found for %s." % b["title"])
        new_covers += write_cover(src, b["site_slug"], force)
        new_motifs += write_motif(b, theme, force)
        fmt = b["formats"]
        formats = []
        for kind in ("paperback", "hardcover", "kindle", "audiobook"):
            if fmt.get(kind):
                formats.append({"kind": kind, "asin": str(fmt[kind]),
                                "isbn": str(fmt.get(kind + "_isbn") or "") or None})
        books.append({
            "id": b.get("id"), "slug": b["slug"], "site_slug": b["site_slug"],
            "group": b["group"], "role": b["role"],
            "title": b["title"], "subtitle": b.get("subtitle") or "",
            "kindle_subtitle": b.get("kindle_subtitle") or "",
            "series": b.get("series") or "", "number": b.get("number"),
            "pitch": b["pitch"].strip(), "formats": formats,
            "theme": {k: theme[k] for k in ("key", "bg", "ink", "soft", "accent", "motif")},
        })

    data = {
        "source": os.path.relpath(os.path.join(BUILD, "library.yaml"), ROOT),
        "groups": lib["groups"],
        "toolkit": {"title": lib["toolkit"]["title"], "text": lib["toolkit"]["text"].strip()},
        "books": books,
    }
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    changed = not os.path.exists(OUT_JSON) or open(OUT_JSON, encoding="utf-8").read() != text
    if changed:
        open(OUT_JSON, "w", encoding="utf-8").write(text)
    print("library: %d books%s; covers copied: %d; motifs drawn: %d"
          % (len(books), " (library.json updated)" if changed else "", new_covers, new_motifs))
    subprocess.run([sys.executable, os.path.join(ROOT, "make_cover_images.py")], check=True)


if __name__ == "__main__":
    main()
