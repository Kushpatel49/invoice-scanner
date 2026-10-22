"""Local Tesseract helpers: page orientation and raw text (free, no API calls)."""
import re
import subprocess
import tempfile


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
