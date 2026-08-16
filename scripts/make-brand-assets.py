#!/usr/bin/env python3
"""Generate the CAIOS dashboard artwork.

    demo/.venv/bin/python scripts/make-brand-assets.py

Writes into configs/dashboard/images/, which scripts/build-dashboard.sh copies
into the build as src/assets/images/caios/:

    dashboard-logo.png   top-left of every page
    favicon.ico          browser tab
    forbidden.png        403 page
    not-found.png        404 page

WHY THIS IS A SCRIPT AND NOT FOUR COMMITTED BLOBS

The PNGs are committed too — the build needs them and nobody should have to run
this to get a working dashboard. But a binary appearing in a repository with no
way to regenerate it is a dead end the first time someone wants the logo 20px
wider, or in a different colour, or with the palette changed. This is the
source; the PNGs are the build output of it.

THE MARK

Three nodes joined in a triangle. That is the federated learning story in one
glyph — three sites, connected, each holding its own data — and it is the thing
this platform is actually for. The upper node is filled to give the shape a
direction rather than reading as a bare triangle.

Colours come from configs/dashboard/theme/caios/variables.scss and are repeated
here rather than parsed out of the SCSS: two files, and a mismatch is visible
immediately rather than being a silent build-time failure.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs" / "dashboard" / "images"

# Matches --primary / --accent / --primary-text in the theme.
PRIMARY = (18, 181, 203, 255)  # #12b5cb
ACCENT = (14, 79, 92, 255)  # #0e4f5c
INK = (10, 42, 48, 255)  # #0a2a30
MUTED = (123, 123, 123, 255)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Everything is drawn at this multiple and downsampled, which is the cheapest
# way to get smooth circles and diagonals out of Pillow — it has no
# antialiasing of its own for shapes.
SS = 4


def font(path, size):
    return ImageFont.truetype(path, size)


def draw_mark(draw, cx, cy, radius, node_r, line_w):
    """Three nodes in a triangle, joined. The federated story as a glyph."""
    import math

    points = []
    for i in range(3):
        angle = math.radians(-90 + i * 120)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    for i in range(3):
        draw.line([points[i], points[(i + 1) % 3]], fill=ACCENT, width=line_w)

    for index, (x, y) in enumerate(points):
        box = [x - node_r, y - node_r, x + node_r, y + node_r]
        if index == 0:
            draw.ellipse(box, fill=PRIMARY)
        else:
            draw.ellipse(box, fill=(255, 255, 255, 255), outline=ACCENT, width=line_w)


def make_logo():
    """Wordmark plus mark, transparent, about 200x50 at final size."""
    w, h = 260 * SS, 56 * SS
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw_mark(draw, cx=26 * SS, cy=28 * SS, radius=17 * SS, node_r=6 * SS, line_w=2 * SS)

    draw.text((58 * SS, 9 * SS), "CAIOS", font=font(FONT_BOLD, 27 * SS), fill=INK)
    draw.text(
        (60 * SS, 37 * SS),
        "MEDICAL AI PLATFORM",
        font=font(FONT_REG, 8 * SS),
        fill=MUTED,
    )

    image.resize((w // SS, h // SS), Image.LANCZOS).save(OUT / "dashboard-logo.png")
    return "dashboard-logo.png"


def make_favicon():
    """Just the mark. Multi-size ICO so the tab is sharp at any zoom."""
    size = 64 * SS
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_mark(
        draw,
        cx=size / 2,
        cy=size / 2 + 2 * SS,
        radius=21 * SS,
        node_r=8 * SS,
        line_w=3 * SS,
    )
    small = image.resize((64, 64), Image.LANCZOS)
    small.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    return "favicon.ico"


def make_error_page(filename, code, message):
    """The 403 and 404 images. Rarely seen, but seen at the worst moments."""
    w, h = 420 * SS, 260 * SS
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw_mark(
        draw, cx=w / 2, cy=88 * SS, radius=44 * SS, node_r=15 * SS, line_w=5 * SS
    )

    code_font = font(FONT_BOLD, 54 * SS)
    msg_font = font(FONT_REG, 15 * SS)
    for text, y, fnt, fill in (
        (code, 158 * SS, code_font, ACCENT),
        (message, 218 * SS, msg_font, MUTED),
    ):
        width = draw.textlength(text, font=fnt)
        draw.text(((w - width) / 2, y), text, font=fnt, fill=fill)

    image.resize((w // SS, h // SS), Image.LANCZOS).save(OUT / filename)
    return filename


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    written = [
        make_logo(),
        make_favicon(),
        make_error_page("forbidden.png", "403", "You do not have access to this page"),
        make_error_page("not-found.png", "404", "That page does not exist"),
    ]
    for name in written:
        path = OUT / name
        with Image.open(path) as check:
            print(f"  {name:22s} {check.size[0]}x{check.size[1]}  {path.stat().st_size:>6} bytes")
    print(f"\n  wrote {len(written)} files to {OUT.relative_to(ROOT)}/")
    print("  now run: bash scripts/build-dashboard.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
