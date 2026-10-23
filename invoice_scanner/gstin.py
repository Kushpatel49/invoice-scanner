"""GSTIN validation, OCR repair and supplier-GSTIN lookup.

A GSTIN is 15 characters: 2-digit state code, 10-character PAN, entity number,
'Z', and a mod-36 check character. The checksum is what makes GSTINs safe to
take from noisy OCR: a misread almost never passes it.
"""
import re

from PIL import Image

from . import config
from .ocr import tess
from .validate import edit_distance

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
                   else "Z" if kind == "Z" and ch in "27" else ch)
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


# Letterhead corners where a seller prints its GSTIN: (left, top, right, bottom, upscale). The top 45% at 2x
# is already read by extract.verify_header, so these are only the fallbacks for tiny print.
GSTIN_CROPS = [(0, 0, .5, .3, 3), (.5, 0, 1, .3, 3)]

GSTIN_LIST_PROMPT = ("List every GSTIN number printed on this page, one per line, exactly as printed "
                     "(15 characters each). Nothing else.")


def find_supplier_gstin(img, header_guess, verify_gstins, ocr_text, llm):
    """Return (gstin, source, issue) for the bill's supplier.

    The vision model reads GSTINs well but mixes up whose is whose (it often copies our own GSTIN into
    the supplier field, or one from another bill lying underneath), and a garbled read passes the mod-36
    checksum about 1 time in 36. So a GSTIN is only trusted when two independent sources agree:
      "ocr+model"   Tesseract and a model read both contain it
      "model x2"    the full-page header read and the zoomed header read agree
      "ocr"         only Tesseract saw it, and it is the only candidate (OCR + checksum rarely invent one)
      "crop"        found on a paid 3x corner crop, confirmed by Tesseract or another model read
    Otherwise it is returned unconfirmed (issue set) or None."""
    ours = config.COMPANY_GSTIN
    ocr_c = [g for g in gstin_candidates(ocr_text) if g != ours]
    reads = [[g for g in gstin_candidates(t) if g != ours] for t in [header_guess or "", *verify_gstins]]
    model_c = [g for r in reads for g in r]
    # another bill lying under or beside this one can show its own GSTIN: if two different valid GSTINs
    # are on the photo, nothing here can tell which is the supplier's, so a person decides
    seen = list(dict.fromkeys(ocr_c + model_c))
    # a model read of the other GSTIN can carry a one-character slip and fail the checksum, yet still shows
    # that a second GSTIN is on the photo: count GSTIN-shaped strings far from every valid candidate too
    shaped = [g for t in [header_guess or "", *verify_gstins] for g in re.findall(r"\d{2}[A-Z0-9]{13}", re.sub(r"[^A-Z0-9 ]", "", t.upper()))]
    # edit distance: garbled reads of one GSTIN measured 2-6 (characters slip and shift); two different
    # GSTINs measured 7 or more (state code aside, they share nothing)
    others = [g for g in shaped if g != ours and all(edit_distance(g, v) >= 7 for v in seen + [ours])]
    many = seen + list(dict.fromkeys(others))
    ambiguous = f"several GSTINs on the photo ({', '.join(many)}) - confirm the supplier's" if len(many) > 1 else None
    both = [g for g in model_c if g in ocr_c]
    if both:
        return both[0], "ocr+model", ambiguous
    twice = [g for g in model_c if sum(g in r for r in reads) >= 2]
    if twice:
        return twice[0], "model x2", ambiguous
    if len(set(ocr_c)) == 1:
        return ocr_c[0], "ocr", None
    if len(set(ocr_c)) > 1:
        return ocr_c[0], "ocr", f"several GSTINs on the photo ({', '.join(dict.fromkeys(ocr_c))}) - confirm the supplier's"
    for l, t, r, b, k in GSTIN_CROPS:
        c = img.crop((int(img.width * l), int(img.height * t), int(img.width * r), int(img.height * b)))
        c = c.resize((c.width * k, c.height * k), Image.LANCZOS)
        listed = [g for g in gstin_candidates(llm.chat(GSTIN_LIST_PROMPT, c, max_tokens=120, step="gstin_crop"))
                  if g != ours]
        crop_ocr = [g for g in gstin_candidates(tess(c, "--psm", "3")) if g != ours]
        confirmed = [g for g in listed if g in crop_ocr or g in model_c] + [g for g in crop_ocr if g in model_c]
        if confirmed:
            return confirmed[0], "crop", None
        if crop_ocr and len(set(crop_ocr)) == 1:
            return crop_ocr[0], "crop", None
        model_c += listed
    if model_c:
        return model_c[0], "unverified", f"supplier GSTIN '{model_c[0]}' not confirmed (read once by the model only)"
    return None, "none", None
