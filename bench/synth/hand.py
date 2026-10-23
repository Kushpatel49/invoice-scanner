"""Shared drawing helpers for synthetic bills: fonts, handwriting, pen marks.

Handwriting is drawn character by character with small random rotation,
baseline wobble, size and ink variation so it reads like pen, not a font.
All functions take a `random.Random` so output is reproducible.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"

HAND_FONTS = ["Kalam-Regular.ttf", "Kalam-Light.ttf", "Caveat.ttf", "PatrickHand-Regular.ttf",
              "GochiHand-Regular.ttf", "ReenieBeanie.ttf"]
# Rupee sign (U+20B9): only "sans", "narrow" and "condensed" draw it correctly. PT Serif draws a
# ruble-like glyph and OpenSans / RobotoMono / Courier Prime have none - print "Rs." with those.
PRINT_FONTS = {
    "sans": "NotoSans.ttf", "sans2": "OpenSans.ttf", "narrow": "ArchivoNarrow.ttf", "condensed": "Oswald.ttf",
    "serif": "PT_Serif-Web-Regular.ttf", "serif_bold": "PT_Serif-Web-Bold.ttf",
    "mono": "RobotoMono.ttf", "typewriter": "CourierPrime-Regular.ttf", "typewriter_bold": "CourierPrime-Bold.ttf",
}
VARIABLE = {"NotoSans.ttf", "OpenSans.ttf", "ArchivoNarrow.ttf", "Oswald.ttf", "RobotoMono.ttf", "Caveat.ttf"}

INKS = {"blue": (25, 45, 150), "blue_light": (45, 70, 170), "black": (25, 25, 35), "red": (190, 30, 35),
        "violet": (95, 50, 150), "green": (20, 110, 60)}

_cache = {}


def font(name, size, bold=False):
    """Load a bundled font by file name or PRINT_FONTS key. `bold` sets the weight axis of variable fonts."""
    fname = PRINT_FONTS.get(name, name)
    key = (fname, size, bold)
    if key not in _cache:
        f = ImageFont.truetype(str(FONT_DIR / fname), size)
        if fname in VARIABLE:
            try:
                f.set_variation_by_axes([700 if bold else 400] + ([100] if fname in ("NotoSans.ttf", "OpenSans.ttf") else []))
            except (OSError, ValueError):
                pass
        _cache[key] = f
    return _cache[key]


def hand_font(rng):
    return rng.choice(HAND_FONTS)


def hand_text(img, xy, text, size, rng, font_name=None, ink="blue", slant=None, jitter=1.0, anchor="ls"):
    """Draw `text` as handwriting starting at xy (left, baseline). Returns the bounding box.

    font_name: a HAND_FONTS file (random if None)
    jitter:    0 = plain font, 1 = normal hand, 2 = sloppy
    """
    font_name = font_name or hand_font(rng)
    color = INKS.get(ink, ink) if isinstance(ink, str) else ink
    slant = rng.uniform(-4, 4) if slant is None else slant
    x, y = xy
    bbox = [x, y, x, y]
    for ch in text:
        s = max(8, int(size * (1 + rng.uniform(-0.06, 0.06) * jitter)))
        f = font(font_name, s)
        if ch == " ":
            x += s * rng.uniform(0.28, 0.42)
            continue
        w = f.getlength(ch)
        pad = int(s * 0.6)
        layer = Image.new("L", (int(w) + 2 * pad, int(s * 1.6) + 2 * pad), 0)
        ImageDraw.Draw(layer).text((pad, pad + s), ch, font=f, fill=int(255 * rng.uniform(0.82, 1.0)), anchor="ls")
        angle = slant + rng.uniform(-5, 5) * jitter
        layer = layer.rotate(angle, resample=Image.BICUBIC, center=(pad, pad + s))
        dy = rng.uniform(-1.5, 1.5) * jitter * s / 30
        ox, oy = int(x - pad), int(y - pad - s + dy)
        _ink(img, layer, (ox, oy), color)
        bbox = [min(bbox[0], x), min(bbox[1], y - s * 0.8), max(bbox[2], x + w), max(bbox[3], y + s * 0.3)]
        x += w * rng.uniform(0.92, 1.06)
    return tuple(int(v) for v in bbox)


def _ink(img, mask, offset, color):
    """Composite a coverage mask onto img in `color` (works on RGB images)."""
    solid = Image.new("RGB", mask.size, color)
    img.paste(solid, offset, mask)


def text_width(text, size, font_name):
    return font(font_name, size).getlength(text)


def pen_line(draw, points, rng, ink="blue", width=3):
    """A slightly wobbly pen stroke through `points`."""
    color = INKS.get(ink, ink) if isinstance(ink, str) else ink
    pts = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 12))
        for i in range(n):
            t = i / n
            pts.append((x0 + (x1 - x0) * t + rng.uniform(-1, 1), y0 + (y1 - y0) * t + rng.uniform(-1.2, 1.2)))
    pts.append(points[-1])
    draw.line(pts, fill=color, width=width, joint="curve")


def strike_through(img, bbox, rng, ink="blue", double=False):
    """Cross out the text inside bbox with one or two pen strokes."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = bbox
    ym = (y0 + y1) / 2
    for k in range(2 if double else 1):
        off = (k - 0.5) * (y1 - y0) * 0.25 if double else 0
        pen_line(d, [(x0 - 4, ym + off + rng.uniform(-3, 3)), (x1 + 4, ym + off + rng.uniform(-3, 3))], rng, ink,
                 width=rng.randint(2, 4))


def tick(img, xy, size, rng, ink="blue"):
    x, y = xy
    pen_line(ImageDraw.Draw(img), [(x, y), (x + size * 0.35, y + size * 0.4), (x + size, y - size * 0.6)], rng, ink,
             width=max(2, size // 8))


def signature(img, xy, width, rng, ink="blue"):
    """A scribbled signature: a few loops and a flourish."""
    x, y = xy
    pts = []
    for i in range(rng.randint(14, 26)):
        t = i / 20
        pts.append((x + t * width, y + math.sin(t * rng.uniform(8, 14)) * width * rng.uniform(0.06, 0.14)))
    pen_line(ImageDraw.Draw(img), pts, rng, ink, width=rng.randint(2, 3))
