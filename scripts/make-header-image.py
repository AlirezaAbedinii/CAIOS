#!/usr/bin/env python3
"""Turn a supplied home page illustration into the asset the dashboard serves.

    demo/.venv/bin/python scripts/make-header-image.py <source>

Writes configs/dashboard/images/header_image.webp. Re-runnable: the artwork is
iterated on, and every version needs the same three things doing to it.

WHY THIS EXISTS RATHER THAN A ONE-OFF COMMAND

1. THE BACKGROUND HAS TO GO. The illustrations arrive on their own cream, which
   is close to the page's paper but not the same, so dropped in as supplied
   they read as a rectangle pasted onto the page. Keying the background out
   lets the page's own ground show through and the drawing sit on the page
   rather than on top of it.

   Keyed by distance from the background colour, with a soft ramp rather than a
   threshold, so antialiased edges keep partial alpha instead of turning into a
   staircase. The unfilled interiors of the drawing go transparent too, which
   is correct: they were the same cream, and occlusion is already baked into
   the raster, so what shows through is the page and nothing is revealed that
   should not be.

   Fully transparent pixels have their colour set to the page's paper. Resizing
   RGBA does not premultiply, so a little colour bleeds from transparent pixels
   into their neighbours; making that colour the page's own means the bleed is
   invisible instead of being a cream halo.

2. IT HAS TO BE THE SIZE THE PAGE GIVES IT. The slot is about 320 CSS pixels
   wide on a desktop, measured in a browser, so 640 is exactly 2x and anything
   beyond it is bytes nobody sees. That is not a small saving on artwork like
   this: the same drawing at 800 wide is 400 KB against 290, because dense
   hatching is expensive in any lossy format and there is a lot of it.

3. IT HAS TO BE WEBP. The same picture as a PNG is four times the size, on a
   page whose whole argument is that it renders immediately.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "configs/dashboard/images/header_image.webp"

# --h-paper in configs/dashboard/home/components/home/home.component.scss.
PAPER = (247, 245, 242)

# Distance from the background colour, in 0-255 per channel, between which
# alpha ramps from nothing to solid. The floor is above JPEG's noise around
# flat areas; the ceiling is below the lightest ink in these drawings.
SOFT_FLOOR = 10
SOFT_CEIL = 28


def background_colour(rgb: Image.Image) -> tuple[int, int, int]:
    """The median of a one-pixel ring around the edge.

    A ring rather than a single corner: one corner can land on a stray line,
    and these illustrations run their linework off all four edges.
    """
    a = np.asarray(rgb)
    ring = np.concatenate(
        [a[0, :, :], a[-1, :, :], a[:, 0, :], a[:, -1, :]], axis=0
    )
    return tuple(int(v) for v in np.median(ring, axis=0))


def key_out(rgb: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """RGBA, with everything the colour of `bg` made transparent.

    Distance is the largest per-channel difference rather than the Euclidean
    one: it is the measure that treats a change in a single channel, which is
    what a pale wash of one of the drawing's colours looks like, as seriously
    as a change in all three.
    """
    a = np.asarray(rgb).astype(np.int16)
    distance = np.abs(a - np.array(bg, dtype=np.int16)).max(axis=2)
    alpha = np.clip(
        (distance - SOFT_FLOOR) / (SOFT_CEIL - SOFT_FLOOR), 0.0, 1.0
    )

    rgb_out = a.astype(np.uint8).copy()
    # Transparent pixels take the page's own colour, so the little that bleeds
    # out of them when the image is resized is invisible rather than a halo.
    rgb_out[alpha == 0] = PAPER

    return Image.fromarray(
        np.dstack([rgb_out, (alpha * 255).astype(np.uint8)]), "RGBA"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="the supplied illustration")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument(
        "--keep-background",
        action="store_true",
        help="skip the keying, for artwork that is already transparent",
    )
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"no such file: {args.source}", file=sys.stderr)
        return 1

    src = Image.open(args.source)
    before = args.source.stat().st_size
    print(f"{args.source.name}: {src.size[0]}x{src.size[1]} {src.mode}")

    if args.keep_background and src.mode == "RGBA":
        img = src
    else:
        rgb = src.convert("RGB")
        bg = background_colour(rgb)
        print(f"  background read from the border ring: {bg}")
        img = key_out(rgb, bg)

    height = round(args.width * img.size[1] / img.size[0])
    img = img.resize((args.width, height), Image.LANCZOS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="WEBP", quality=88, method=6)

    after = OUT.stat().st_size
    opaque = float((np.asarray(img.getchannel("A")) > 0).mean())
    print(
        f"  -> {OUT.relative_to(ROOT)}  {args.width}x{height}  "
        f"{after / 1024:.0f} KB (from {before / 1024:.0f} KB)  "
        f"{100 * opaque:.0f}% of it draws anything"
    )
    print(
        "\nThe page sets width and height on the element, so update them in "
        "home.component.html if the aspect ratio changed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
