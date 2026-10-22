"""GSTIN validation, OCR repair and supplier-GSTIN lookup.

A GSTIN is 15 characters: 2-digit state code, 10-character PAN, entity number,
'Z', and a mod-36 check character. The checksum is what makes GSTINs safe to
take from noisy OCR: a misread almost never passes it.
"""
import re

from PIL import Image

from . import config
from .ocr import tess

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_ok(g):
    """True if `g` is a well-formed GSTIN with a valid state code and check character."""
    # state code: 01-38, plus 97 (other territory) and 99 (centre jurisdiction)
    if not g or not GSTIN_RE.match(g) or not (1 <= int(g[:2]) <= 38 or g[:2] in ("97", "99")):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        p = CHARS.index(ch) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return CHARS[(36 - total % 36) % 36] == g[14]


TO_DIGIT = str.maketrans("OQDIlLSZBGT", "00011152867")
TO_ALPHA = str.maketrans("0125861", "OIZSBGI")
# D = must be a digit, A = must be a letter, X = either, Z = literal 'Z'
LAYOUT = "DDAAAAADDDDAXZX"


def repair_gstin(chunk):
    """Fix OCR look-alikes (S/5, O/0, B/8...) using the character class each position must have."""
    out = []
    for ch, kind in zip(chunk, LAYOUT):
        out.append(ch.translate(TO_DIGIT) if kind == "D" else ch.translate(TO_ALPHA) if kind == "A"
                   else "Z" if kind == "Z" and ch == "2" else ch)
    return "".join(out)


def gstin_candidates(text, max_fixes=2):
    """Checksum-valid GSTINs found in OCR or model text, in order of appearance.

    A GSTIN may be split across at most two adjacent words ("32AAHCG9621 M1ZC") and
    need at most `max_fixes` look-alike repairs. Looser matching lets random OCR
    noise pass the checksum: unlimited repairs + stitching across words gave ~1
    false GSTIN per 6 pages of random text; these limits give ~1 per 230."""
    found = []
    words = [re.sub(r"[^A-Za-z0-9]", "", w).upper() for w in text.split()]
    words = [w for w in words if w]
    for i, w in enumerate(words):
        for flat in (w, w + words[i + 1]) if i + 1 < len(words) else (w,):
            for j in range(len(flat) - 14):
                if flat is not w and j + 15 <= len(w):
                    continue   # window lies inside the first word alone; already checked
                raw = flat[j:j + 15]
                fix = repair_gstin(raw)
                if sum(x != y for x, y in zip(raw, fix)) <= max_fixes and gstin_ok(fix) and fix not in found:
                    found.append(fix)
    return found


# Letterhead regions where a seller prints its GSTIN: (left, top, right, bottom, upscale).
GSTIN_CROPS = [(0, 0, 1, .45, 2), (0, 0, .5, .3, 3), (.5, 0, 1, .3, 3)]

GSTIN_LIST_PROMPT = ("List every GSTIN number printed on this page, one per line, exactly as printed "
                     "(15 characters each). Nothing else.")


def find_supplier_gstin(img, model_guess, llm):
    """Return (gstin, source) for the bill's supplier.

    The vision model reads GSTINs well but mixes up whose is whose (it often copies
    our own GSTIN into the supplier field), and the print is tiny. So:
      1. free: a checksum-valid GSTIN that isn't ours from the header pass or a
         full-page Tesseract read  -> source "header/ocr"
      2. paid: ask the model to list GSTINs on upscaled letterhead crops, keep
         checksum-valid ones that aren't ours                  -> source "crop"
      3. otherwise the model's unverified guess (or None)      -> source "unverified"
    """
    others = lambda text: [g for g in gstin_candidates(text) if g != config.COMPANY_GSTIN]
    found = others((model_guess or "") + "\n" + tess(img, "--psm", "3"))
    if found:
        return found[0], "header/ocr"
    for l, t, r, b, k in GSTIN_CROPS:
        c = img.crop((int(img.width * l), int(img.height * t), int(img.width * r), int(img.height * b)))
        c = c.resize((c.width * k, c.height * k), Image.LANCZOS)
        listed = llm.chat(GSTIN_LIST_PROMPT, c, max_tokens=120, step="gstin_crop")
        found = others(listed + "\n" + tess(c, "--psm", "3"))
        if found:
            return found[0], "crop"
    return (model_guess if model_guess != config.COMPANY_GSTIN else None), "unverified"
