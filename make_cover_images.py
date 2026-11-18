#!/usr/bin/env python3
"""Write AVIF and WebP versions of every book cover, at 160, 260, 320, 400 and 700px wide.

    python3 make_cover_images.py           only covers whose variants are missing
    python3 make_cover_images.py --all     rewrite every variant

Run it after adding or replacing a cover in assets/covers/{slug}.jpg. The build
refuses to run while any cover lacks its variants, because cover_frame() points
<picture> sources at them.

Uses Pillow's AVIF encoder when it has one, otherwise avifenc (Homebrew: libavif). AVIF at quality 55 roughly halves
the JPEG and keeps the small type on the covers legible; WebP is the fallback for
browsers without AVIF, and the original JPEG stays the last resort and the image
used in structured data and share cards.
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, features

COVERS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "covers")
WIDTHS = (160, 260, 320, 400, 700)
FORMATS = (("avif", "AVIF", {"quality": 55}), ("webp", "WEBP", {"quality": 80, "method": 6}))


def avif_cli(image, out):
    """AVIF through avifenc, for a Pillow built without AVIF; quality 55 as above."""
    tool = shutil.which("avifenc") or "/opt/homebrew/bin/avifenc"
    if not os.path.exists(tool):
        sys.exit("make_cover_images.py: no AVIF encoder (install libavif, or Pillow 11.2+ with AVIF)")
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "in.png")
        image.save(png)
        subprocess.run([tool, "-q", "55", "-s", "4", "-y", "420", png, out], check=True, capture_output=True)


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
                small = image.resize((width, height), Image.LANCZOS)
                if fmt == "AVIF" and not features.check("avif"):
                    avif_cli(small, out)
                else:
                    small.save(out, fmt, **opts)
                written += 1
    print("cover variants written: %d" % written)


if __name__ == "__main__":
    main()
