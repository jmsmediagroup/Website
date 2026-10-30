#!/usr/bin/env python3
"""Write AVIF and WebP versions of every book cover, at 160, 260, 320, 400 and 700px wide.

    python3 make_cover_images.py           only covers whose variants are missing
    python3 make_cover_images.py --all     rewrite every variant

Run it after adding or replacing a cover in assets/covers/{slug}.jpg. The build
refuses to run while any cover lacks its variants, because cover_frame() points
<picture> sources at them.

Needs Pillow with AVIF support (11.2 or later). AVIF at quality 55 roughly halves
the JPEG and keeps the small type on the covers legible; WebP is the fallback for
browsers without AVIF, and the original JPEG stays the last resort and the image
used in structured data and share cards.
"""

import glob
import os
import sys

from PIL import Image

COVERS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "covers")
WIDTHS = (160, 260, 320, 400, 700)
FORMATS = (("avif", "AVIF", {"quality": 55}), ("webp", "WEBP", {"quality": 80, "method": 6}))


def main():
    force = "--all" in sys.argv[1:]
    written = 0
    for src in sorted(glob.glob(os.path.join(COVERS, "*.jpg"))):
        if src.endswith("-400.jpg"):
            continue
        slug = os.path.basename(src)[:-4]
        image = None
        for width in WIDTHS:
            for ext, fmt, opts in FORMATS:
                out = os.path.join(COVERS, "%s-%d.%s" % (slug, width, ext))
                if os.path.exists(out) and not force:
                    continue
                if image is None:
                    image = Image.open(src).convert("RGB")
                height = round(image.height * width / image.width)
                image.resize((width, height), Image.LANCZOS).save(out, fmt, **opts)
                written += 1
    print("cover variants written: %d" % written)


if __name__ == "__main__":
    main()
