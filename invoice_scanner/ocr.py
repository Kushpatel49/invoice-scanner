"""Local Tesseract helpers: page orientation and raw text (free, no API calls)."""
import re
import subprocess
import tempfile

from PIL import Image


def tess(img, *args):
    """Run the tesseract CLI on a PIL image and return stdout."""
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.convert("L").save(f.name)
        return subprocess.run(["tesseract", f.name, "-", *args], capture_output=True, text=True).stdout


def text_score(img):
    """Summed confidence of plausible words - high only when the text is upright."""
    score = 0
    for row in tess(img, "--psm", "6", "tsv").splitlines()[1:]:
        c = row.split("\t")
        if len(c) == 12 and float(c[10]) > 60 and len(re.sub(r"[^A-Za-z0-9]", "", c[11])) >= 3:
            score += float(c[10])
    return score


def orientation(img):
    """Clockwise degrees (0/90/180/270) needed to make the text upright.

    Tesseract OSD is used when it is confident (>= 2). Otherwise each candidate
    rotation is OCR'd and the one yielding the most confident words wins - OSD
    alone gets about a third of phone photos wrong. Asking the vision model
    instead was unreliable (it answered "up" for everything)."""
    out = tess(img, "--psm", "0")
    m, c = re.search(r"Rotate: (\d+)", out), re.search(r"Orientation confidence: ([\d.]+)", out)
    if m and c and float(c.group(1)) >= 2:
        return int(m.group(1))
    small = img.copy()
    small.thumbnail((1000, 1000))
    # A landscape photo of a portrait bill can only be a quarter turn.
    cands = (90, 270) if img.width > img.height else (0, 180, 90, 270)
    scores = {r: text_score(small.rotate(-r, expand=True)) for r in cands}
    return max(scores, key=scores.get)


def page_text(img):
    """Tesseract text of the whole page plus the top 45% at 2x (where invoice numbers, dates and GSTINs
    are printed small). Used to confirm or contradict what the model read; computed once per bill."""
    top = img.crop((0, 0, img.width, int(img.height * 0.45)))
    top = top.resize((top.width * 2, top.height * 2), Image.LANCZOS)
    return tess(img, "--psm", "3") + "\n" + tess(top, "--psm", "11")


def skew_angle(img, max_deg=6.0):
    """Small rotation (degrees, counter-clockwise positive like PIL) that makes printed text lines level.

    Projection-profile method: on a binarised copy of the central part of the page, the row sums are
    most uneven (highest variance) when text lines are horizontal. Returns 0.0 when no angle is clearly
    better than none (handwriting, unruled pages)."""
    import numpy as np
    g = img.convert("L")
    g.thumbnail((900, 900))
    w, h = g.size
    g = g.crop((int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)))   # stay off the background
    a = np.asarray(g, dtype=np.float32)
    ink = Image.fromarray(((a < a.mean() - 1.0 * a.std()) * 255).astype("uint8"))

    def score(deg):
        rows = np.asarray(ink.rotate(deg, resample=Image.NEAREST), dtype=np.float32).sum(axis=1)
        return float(np.var(rows))

    coarse = {d / 2: score(d / 2) for d in range(int(-max_deg * 2), int(max_deg * 2) + 1)}
    best = max(coarse, key=coarse.get)
    fine = {best + d / 10: score(best + d / 10) for d in range(-5, 6)}
    best = max(fine, key=fine.get)
    if abs(best) < 0.3 or fine[best] < coarse[0.0] * 1.05:
        return 0.0
    return round(best, 2)


def deskew(img):
    """Rotate away a small skew (see skew_angle). Returns (image, angle)."""
    angle = skew_angle(img)
    if not angle:
        return img, 0.0
    fill = tuple(int(v) for v in img.convert("RGB").resize((1, 1)).getpixel((0, 0)))
    return img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill), angle
