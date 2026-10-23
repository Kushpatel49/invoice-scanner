"""Turn a clean bill page into a WhatsApp photo of that bill as it looks at the store.

    photo, recipe = apply(page, layout, spec, rng, difficulty=None)

1. Receiver's marks, drawn at page resolution and multiplied in like ink (so the print underneath
   stays readable): the violet GOODS RECEIVED stamp with handwritten fill-ins, the invoice-number
   correction, pen notes ("Bill-641"), ticks next to rows and a signature.
2. Paper: tint (layout["paper"]), fibre texture, fold creases, slight curl.
3. Photo: background (other bills, desk, laptop keyboard), sometimes the edge of another bill
   underneath showing its GSTIN, perspective, skew and a global rotation.
4. Camera: light gradient, phone/hand shadow, glare, colour cast, low-contrast tone, blur, noise.
5. WhatsApp-like save: 960x1280 or 1280x960 and a JPEG round trip at quality 60-85.

recipe["rotate_deg"] is the CLOCKWISE rotation that makes the photo upright, the same convention as
eval/ground_truth.json (top of the text pointing left => 90, pointing right => 270).
Every choice is recorded in the recipe. numpy noise is seeded from `rng`, so the same rng state gives
the same photo. Coordinates in the recipe are page pixels unless the key says "photo".
"""
import io
import math
import random
from datetime import date, timedelta

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from bench.synth import hand
from bench.synth.spec import make_gstin

WORK = 1.6                      # the photo is rendered at 1.6x its final size, then downscaled
FINAL_LONG, FINAL_SHORT = 1280, 960

DIFFICULTY = {"easy": 30, "medium": 45, "hard": 25}
# clockwise rotation to upright -> weight (real photos: ~55% upright, 35% top-left, 10% top-right)
ROTATIONS = {0: 53, 90: 35, 270: 10, 180: 2}

KNOBS = {
    "easy": {"fill": (0.92, 1.06), "skew": 1.5, "persp": (0.0, 0.012), "curl": (0.0, 0.004), "crease": 0.15,
             "shadow": (0.0, 0.12), "gradient": (0.02, 0.10), "glare": 0.05, "glare_strength": (0.15, 0.3),
             "blur": (0.25, 0.5), "noise": (1.0, 2.5), "white": (205, 235), "black": (20, 45), "jpeg": (75, 85)},
    "medium": {"fill": (0.9, 1.08), "skew": 3.0, "persp": (0.01, 0.03), "curl": (0.003, 0.01), "crease": 0.35,
               "shadow": (0.08, 0.25), "gradient": (0.05, 0.16), "glare": 0.15, "glare_strength": (0.18, 0.35),
               "blur": (0.45, 0.8), "noise": (2.0, 4.0), "white": (188, 222), "black": (30, 58), "jpeg": (66, 82)},
    "hard": {"fill": (0.88, 1.1), "skew": 5.0, "persp": (0.025, 0.05), "curl": (0.008, 0.018), "crease": 0.6,
             "shadow": (0.18, 0.36), "gradient": (0.1, 0.22), "glare": 0.3, "glare_strength": (0.25, 0.42),
             "blur": (0.7, 1.2), "noise": (3.0, 5.5), "white": (180, 215), "black": (35, 62), "jpeg": (60, 74)},
}

# paper reflectance per layout["paper"]; pink measured from inv09
PAPER = {"white": (250, 250, 247), "cream": (250, 243, 222), "pink": (250, 160, 180), "yellow": (250, 238, 168),
         "green": (214, 240, 208)}
BLUE_PENS = [(25, 45, 150), (35, 55, 165), (20, 35, 120), (45, 70, 170), (30, 40, 135)]
BLACK_PEN = (30, 30, 40)
STAMP_INKS = [(85, 55, 150), (75, 50, 135), (95, 62, 160), (72, 58, 145), (92, 52, 145)]
# handwriting a careful reader can still read: used for anything that is ground truth
LEGIBLE_HANDS = ["Kalam-Regular.ttf", "Kalam-Bold.ttf", "PatrickHand-Regular.ttf", "Caveat.ttf"]
STAMP_BRANCHES = {"KAKKANAD": ["KKD", "K.K.D", "Kakkanad", "KKD"], "TRIPUNITHURA": ["TPRA", "Tripunithura", "TPR"]}
RECEIVERS = ["Prajesh", "Sajitha S", "Shalet", "Rahim", "Pradeesh", "Bibin", "Anu", "Jithin", "Sreeja", "Akhil",
             "Neethu", "Vishnu", "Rakhi", "Sanal", "Arun"]
PAPER_WORDS = ["Invoice", "INVOICE", "Received By", "Signature", "Particulars", "Qty", "Rate", "Amount", "Date",
               "Bill No", "M/s", "Kakkanad", "Ernakulam", "Thank you", "Customer", "Remarks", "Delivery Note",
               "Terms of Delivery", "E & O.E", "Authorised Signatory", "Fresh", "Vegetables", "Fruits", "TAX INVOICE",
               "ORIGINAL FOR RECIPIENT", "Note", "Receiver's Signature", "Buyer", "Description of Goods"]
KEY_LABELS = ["home", "end", "pg up", "pg dn", "delete", "insert", "shift", "enter", "backspace", "prt sc", "F", "G",
              "H", "J", "K", "L", "ctrl", "alt", "fn", "num lk", "esc", "tab", "caps lock", "?", "}", "|"]
DESKS = {"wood": (150, 108, 72), "dark wood": (96, 66, 44), "grey laminate": (140, 140, 136),
         "white table": (212, 210, 202), "black table": (52, 52, 56)}


def apply(page, layout, spec, rng, difficulty=None):
    """Return (photo, recipe): a WhatsApp-like photo of the bill and every parameter used."""
    if difficulty is None:
        difficulty = _pick(rng, DIFFICULTY)
    k = KNOBS[difficulty]
    nrng = np.random.default_rng(rng.getrandbits(32))
    page = page.convert("RGB")
    layout = _clean_layout(layout, page.size)
    recipe = {"difficulty": difficulty, "paper": layout["paper"]}

    # 1. receiver's marks on a white layer, multiplied in at the end
    ppm = _px_per_mm(page, layout)
    recipe["px_per_mm"] = ppm
    marks = Image.new("RGB", page.size, "white")
    pen = rng.choice(BLUE_PENS) if rng.random() < 0.82 else BLACK_PEN
    recipe["pen_ink"] = list(pen)
    recipe["invoice_correction"] = _invoice_correction(marks, page, layout, spec, rng, ppm)
    recipe["notes"] = _notes(marks, page, layout, spec, rng, ppm, pen)
    # the handwritten invoice number and notes are ground truth too: the stamp and signature keep off them
    layout["keep_clear"] = [m["box"] for m in recipe["notes"][:1]]
    if recipe["invoice_correction"]:
        layout["keep_clear"].append(recipe["invoice_correction"]["box"])
    recipe["stamp"] = _stamp(marks, page, layout, spec, rng, nrng, ppm, difficulty)
    recipe["stamp_over_table"] = bool(recipe["stamp"] and recipe["stamp"]["over_table"])
    recipe["ticks"] = _ticks(marks, page, layout, rng, ppm, pen)
    recipe["signature"] = _signature(marks, page, layout, rng, ppm, pen)
    page = ImageChops.multiply(page, marks)

    # 2-3. geometry first (it decides the scale), then paper effects on the downscaled page
    portrait = page.height >= page.width
    fw, fh = (FINAL_SHORT, FINAL_LONG) if portrait else (FINAL_LONG, FINAL_SHORT)
    fw, fh = round(fw * WORK), round(fh * WORK)
    underlay = rng.random() < 0.05
    content = _content_box(layout, recipe, page.size, ppm)
    geo = _place_page(page.size, content, fw, fh, rng, k, underlay)
    s = geo["scale"]
    small = page.resize((max(8, round(page.width * s)), max(8, round(page.height * s))), Image.LANCZOS)
    small, recipe["paper_effects"] = _paper(small, layout["paper"], rng, nrng, k, ppm * s)
    frame, recipe["background"] = _background(fw, fh, rng, nrng, ppm * s, geo["corners"])
    recipe["underlay_gstin"] = recipe["underlay"] = None
    if underlay:
        recipe["underlay"] = _underlay(frame, small.size, geo, spec, rng, ppm * s)
        recipe["underlay_gstin"] = recipe["underlay"]["gstin"]
    frame = _composite_page(frame, small, geo, recipe["paper_effects"]["curl"], rng)

    # 4. light and camera
    arr = np.asarray(frame, np.float32)
    arr, recipe["lighting"] = _lighting(arr, geo["corners"], rng, k, difficulty)
    row_px = _row_height(layout, ppm) * s / WORK          # a text row's height in the final photo, px
    text_px = _text_height(layout, ppm) * s / WORK        # the printed numbers' height in the final photo, px
    mm_px = ppm * s / WORK                                  # final photo px per mm of paper
    recipe["text_row_px"], recipe["text_px"], recipe["photo_px_per_mm"] = row_px, text_px, mm_px
    img, recipe["camera"] = _camera(arr, rng, nrng, k, row_px, text_px, mm_px, difficulty)

    # 5. rotation and the WhatsApp save
    rot = _pick(rng, ROTATIONS)
    recipe["rotate_deg"] = rot
    if rot:
        # the photo shows the page turned counter-clockwise by rot, so clockwise rot makes it upright
        img = img.transpose({90: Image.ROTATE_90, 180: Image.ROTATE_180, 270: Image.ROTATE_270}[rot])
    quality = rng.randint(*k["jpeg"])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, progressive=True)
    photo = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    recipe["jpeg_quality"] = quality
    recipe["size"] = list(photo.size)
    recipe["geometry"] = {"fill": geo["fill"], "skew_deg": geo["skew"], "perspective": geo["persp"],
                          "page_corners_photo": [_to_photo(x / WORK, y / WORK, fw / WORK, fh / WORK, rot)
                                                 for x, y in geo["corners"]]}
    if underlay:
        u = recipe["underlay"]
        u["text_box_photo"] = [_to_photo(x / WORK, y / WORK, fw / WORK, fh / WORK, rot) for x, y in u.pop("text_quad")]
    return photo, _jsonable(recipe)


# ----------------------------------------------------------------------------- small helpers

def _pick(rng, weights):
    r = rng.random() * sum(weights.values())
    for key, w in weights.items():
        r -= w
        if r < 0:
            return key
    return key


def _u(rng, lo_hi):
    return rng.uniform(*lo_hi)


def _box(b):
    if not b:
        return None
    x0, y0, x1, y1 = (float(v) for v in b)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _clean_layout(layout, size):
    """Tolerate missing keys and odd types from templates."""
    layout = dict(layout or {})
    for key in ("table_bbox", "header_bbox", "invoice_number_bbox", "date_bbox", "total_bbox", "notes_area"):
        layout[key] = _box(layout.get(key))
    rows = []
    for r in layout.get("rows") or []:
        y0, y1 = float(r.get("y0", 0)), float(r.get("y1", 0))
        if y1 > y0:
            rows.append({"y0": y0, "y1": y1, "desc": _box(r.get("desc_bbox")), "qty": _box(r.get("qty_bbox")),
                         "amount": _box(r.get("amount_bbox"))})
    layout["rows"] = rows
    if layout.get("paper") not in PAPER:
        layout["paper"] = "white"
    # total_bbox is only the grand-total line; subtotal, CGST/SGST and round-off are printed in the same column
    # above it, down to the last item row. Protect that whole block (at most 12% of the page tall).
    tb, layout["totals_area"] = layout["total_bbox"], None
    if tb:
        last = max([r["y1"] for r in rows] or [tb[1]])
        layout["totals_area"] = (min(tb[0], tb[2] - 0.3 * size[0]), max(min(last, tb[1]), tb[1] - 0.12 * size[1]),
                                 tb[2], tb[3])
    return layout


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _value_boxes(layout):
    """Where ground-truth numbers are printed: each row from the end of the description to the amount (hsn, qty,
    rate, amount), the totals block, invoice no and date."""
    boxes = []
    for r in layout["rows"]:
        cells = [b for b in (r["qty"], r["amount"]) if b]
        if not cells:
            continue
        x0 = min(b[0] for b in cells)
        if r["desc"] and r["desc"][2] < x0:
            x0 = r["desc"][2]
        boxes.append((x0, r["y0"], max(b[2] for b in cells), r["y1"]))
    boxes += [layout[k] for k in ("totals_area", "invoice_number_bbox", "date_bbox") if layout.get(k)]
    return boxes


def _row_height(layout, ppm):
    hs = sorted(r["y1"] - r["y0"] for r in layout["rows"])
    return hs[len(hs) // 4] if hs else 6.5 * ppm


def _text_height(layout, ppm):
    """Height of the printed numbers (median qty / amount box, never taller than the row). Some formats print
    small text in tall rows (carbon: 17 px digits in 68 px rows), so the row height alone overstates it."""
    hs = sorted(min(b[3] - b[1], r["y1"] - r["y0"]) for r in layout["rows"] for b in (r["qty"], r["amount"]) if b)
    return hs[len(hs) // 2] if hs else 0.55 * _row_height(layout, ppm)


def _px_per_mm(page, layout):
    """Page pixels per millimetre. Assumes an A4 long side, corrected by the row height (a printed row is
    about 6.5 mm), because bill books are smaller than A4 but rendered at a similar pixel size."""
    long_side = max(page.size)
    a4 = long_side / 297
    if not layout["rows"]:
        return a4
    rows = _row_height(layout, a4) / 6.5
    return min(max(math.sqrt(a4 * rows), long_side / 300), long_side / 190)


def _busy(img, box, marks=None):
    """Fraction of dark pixels inside box (page coords) - how much is already written there."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 1.0
    region = img.crop((x0, y0, x1, y1))
    if marks is not None:
        region = ImageChops.multiply(region, marks.crop((x0, y0, x1, y1)))
    a = np.asarray(region.convert("L").reduce(2) if min(region.size) > 4 else region.convert("L"))
    return float((a < 160).mean())


def _inside(box, size, margin=0):
    return box[0] >= margin and box[1] >= margin and box[2] <= size[0] - margin and box[3] <= size[1] - margin


def _multiply_at(base, layer, xy):
    """Multiply `layer` (white = no change) into `base` with its top-left corner at xy, clipped to base."""
    x, y = int(round(xy[0])), int(round(xy[1]))
    bx0, by0 = max(0, x), max(0, y)
    bx1, by1 = min(base.width, x + layer.width), min(base.height, y + layer.height)
    if bx1 <= bx0 or by1 <= by0:
        return
    region = base.crop((bx0, by0, bx1, by1))
    part = layer.crop((bx0 - x, by0 - y, bx1 - x, by1 - y))
    base.paste(ImageChops.multiply(region, part), (bx0, by0))


def _noise(nrng, w, h, cells):
    """Smooth random field in [0, 1] with about `cells` blobs across the long side."""
    gw = max(2, int(cells * w / max(w, h)) + 2)
    gh = max(2, int(cells * h / max(w, h)) + 2)
    small = Image.fromarray(nrng.random((gh, gw)).astype(np.float32), "F")
    return np.asarray(small.resize((w, h), Image.BICUBIC), np.float32).clip(0, 1)


def _rot(dx, dy, angle):
    """Rotate an offset like PIL's Image.rotate(angle) does (counter-clockwise on screen, y down)."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return dx * c + dy * s, -dx * s + dy * c


def _ink_layer(alpha, ink):
    """Coverage (L image) -> RGB layer of that ink on white, for multiply blending."""
    a = np.asarray(alpha, np.float32)[..., None] / 255
    return Image.fromarray((255 - a * (255 - np.array(ink, np.float32))).astype(np.uint8), "RGB")


def _to_photo(x, y, w, h, rot):
    """Point in the upright frame (w x h) -> point in the photo after turning it counter-clockwise by rot."""
    if rot == 90:
        return [y, w - x]
    if rot == 180:
        return [w - x, h - y]
    if rot == 270:
        return [h - y, x]
    return [x, y]


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return round(float(v), 3)
    return v


# ----------------------------------------------------------------------------- pen marks

def _invoice_correction(marks, page, layout, spec, rng, ppm):
    """Strike the printed invoice number and write the new one next to, below or above it (like inv05).
    The new number goes where its pen strokes cross no print: never over a label, the date or another number,
    which would make both unreadable. Only when every nearby spot has print under it is it written smaller."""
    corr = (spec.get("corrections") or {}).get("invoice_number")
    box = layout["invoice_number_bbox"]
    if not corr or not box:
        return None
    ink = rng.choice(BLUE_PENS) if rng.random() < 0.8 else BLACK_PEN
    double = rng.random() < 0.35
    hand.strike_through(marks, box, rng, ink=ink, double=double)
    x0, y0, x1, y1 = box
    h = y1 - y0
    size = min(max(h * rng.uniform(1.3, 1.7), 4.5 * ppm), 9 * ppm)
    font_name = rng.choice(LEGIBLE_HANDS)
    text = corr["new"]
    protect = [b for b in _value_boxes(layout) if b != box]
    shift = rng.uniform(-0.3, 0.3)
    # what is on the paper already (print, and print with the strike-through) and the rng state the number is
    # drawn with, so every spot is scored with the exact pen strokes that will land there
    printed = np.asarray(page.convert("L")) < 160
    on_paper = printed | (np.asarray(marks.convert("L")) < 160)
    state = rng.getstate()
    # nearby spots: the same line to the right, lines further and further above / below sliding along (far
    # enough left to reach the blank paper beside a right-aligned label column), and the same line left of the
    # label. Pen on or crowding print costs far more than distance; smaller writing only when every spot has print
    # under it.
    best, best_score = None, None
    for scale, scale_cost in ((1.0, 0.0), (0.85, 0.3), (0.72, 0.6)):
        s = size * scale
        if scale < 1 and s < 3.6 * ppm:       # smaller than this the new number itself becomes hard to read
            break
        probe = random.Random()
        probe.setstate(state)
        pen, near, (ox, oy), (bx0, by0, bx1, by1) = _pen_probe(text, s, probe, font_name, ink)
        tw = bx1 - bx0
        spots = [("right", 0.0, x1 + (0.85 + shift) * h, y1 - 0.05 * h),     # clear of the strike's end
                 ("right", 0.03, x1 + (0.3 + shift) * h, y1 + 0.55 * s)]
        for j in range(6):
            spots.append(("left", 0.2 + 0.03 * j, x0 - tw - (0.6 + shift) * h - j * 0.4 * tw, y1 - 0.05 * h))
        for ring, k in enumerate((1.05, 1.7, 2.4)):
            for f in (-2.0, -1.5, -1.0, -0.5, 0.0, 0.25, 0.5, 0.75, 1.0):
                x = x0 - 0.4 * tw + f * (x1 - x0 + 0.4 * tw) + shift * h
                cost = 0.02 + 0.06 * ring + (0.04 - 0.06 * f if f < 0 else 0.0)
                spots.append(("below", cost, x, y1 + s * k))
                spots.append(("above", cost + 0.01, x, y0 - 0.3 * h - s * (k - 1.05)))
        for where, cost, x, base in spots:
            xi, yi = int(round(x)), int(round(base))
            b = (xi + bx0 - 1, yi + by0 - 1, xi + bx1 + 1, yi + by1 + 1)     # the strokes themselves
            pad = 0.12 * s
            # share of the strokes on print or the strike, and of the strokes grown by a gap on print (crowding it)
            on = _pen_on(on_paper, pen, xi + ox, yi + oy)
            touch = _pen_on(printed, near, xi + ox, yi + oy)
            # another value inside the box, or running straight on from it ("31/08/26B1/FS/2737"), confuses both
            bm = (b[0] - 0.4 * s, b[1] - 0.1 * s, b[2] + 0.4 * s, b[3] + 0.1 * s)
            covered = sum(_overlap(bm, p) for p in protect) / ((bm[2] - bm[0]) * (bm[3] - bm[1]))
            # far from the struck number (more than a letter's height away) it may read as some other field's value
            far = max(0.0, math.hypot(max(0.0, b[0] - x1, x0 - b[2]), max(0.0, b[1] - y1, y0 - b[3])) / s - 1)
            score = 100 * on + 200 * touch + _busy(page, (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad), marks) + \
                40 * covered + 5 * (not _inside(b, page.size, 2)) + 0.1 * far + cost + scale_cost
            if best_score is None or score < best_score:
                best, best_score = (where, x, base, s, on, b), score
    where, x, base, size, on, drawn = best
    # "box" is where the strokes are (hand_text's own box reaches 0.3 * size below the baseline, where digits
    # never go, and would seem to overlap the line below)
    hand.hand_text(marks, (x, base), text, size, rng, font_name=font_name, ink=ink, jitter=0.7)
    return {"printed": corr["printed"], "new": text, "where": where, "box": list(drawn), "ink": list(ink),
            "double_strike": double, "font": font_name, "size": size, "pen_on_print": on}


def _pen_probe(text, size, rng, font_name, ink):
    """Draw `text` with hand.hand_text as the correction will (same rng state, same size) on a scratch canvas.
    Returns the stroke mask, the mask grown by a gap, the mask's top-left corner relative to the start
    point (left, baseline) and the strokes' box relative to it."""
    left, base = int(size), int(2 * size)       # the canvas leaves a margin of at least `size` around the text
    canvas = Image.new("RGB", (int(hand.text_width(text, size, font_name) * 1.3 + 2 * size), int(3.6 * size)), "white")
    hand.hand_text(canvas, (left, base), text, size, rng, font_name=font_name, ink=ink, jitter=0.7)
    pen = np.asarray(canvas.convert("L")) < 200
    if not pen.any():
        pen[base - 1, left] = True
    # grow the strokes by a gap: a word space along the line (closer, print reads as part of the number), less
    # across it (lines of print sit closer than that)
    wide = pen.copy()
    for d in range(1, max(1, round(0.3 * size)) + 1):
        wide[:, d:] |= pen[:, :-d]
        wide[:, :-d] |= pen[:, d:]
    near = wide.copy()
    for d in range(1, max(1, round(0.12 * size)) + 1):
        near[d:] |= wide[:-d]
        near[:-d] |= wide[d:]
    ys, xs = np.nonzero(near)
    cx0, cy0 = int(xs.min()), int(ys.min())
    near_crop = near[cy0:ys.max() + 1, cx0:xs.max() + 1]
    pen_crop = pen[cy0:ys.max() + 1, cx0:xs.max() + 1]
    ys, xs = np.nonzero(pen)
    return pen_crop, near_crop, (cx0 - left, cy0 - base), (int(xs.min()) - left, int(ys.min()) - base,
                                                           int(xs.max()) + 1 - left, int(ys.max()) + 1 - base)


def _pen_on(dark, mask, x, y):
    """Share of `mask` (bool, top-left corner at page pixel x, y) lying on True pixels of `dark` (page-sized).
    Parts off the page count as blank (the caller penalises leaving the page)."""
    ph, pw = dark.shape
    h, w = mask.shape
    px0, py0, px1, py1 = max(0, x), max(0, y), min(pw, x + w), min(ph, y + h)
    if px1 <= px0 or py1 <= py0:
        return 0.0
    hit = mask[py0 - y:py1 - y, px0 - x:px1 - x] & dark[py0:py1, px0:px1]
    return float(hit.sum() / max(1, mask.sum()))


def _notes(marks, page, layout, spec, rng, ppm, ink):
    """Write the receiver's notes ("Bill-641", "short 2 kg") big and sloppy in the notes area."""
    notes = spec.get("notes") or []
    if not notes:
        return []
    area = layout["notes_area"]
    if not area:   # no area given: the top margin above the letterhead, right half
        top = (layout["header_bbox"] or (0, page.height * 0.12, 0, 0))[1]
        area = (page.width * 0.45, page.height * 0.01, page.width * 0.97, max(top - 2, page.height * 0.06))
    ax0, ay0, ax1, ay1 = area
    aw, ah = ax1 - ax0, ay1 - ay0
    font_name = rng.choice(LEGIBLE_HANDS)
    jitter = rng.uniform(1.2, 1.7)
    angle = rng.uniform(-9, 7) if rng.random() < 0.8 else rng.uniform(-30, -12)
    size = rng.uniform(7.5, 10.5) * ppm
    widest = max(hand.text_width(t, size, font_name) for t in notes) * 1.1
    size *= min(1.0, aw * 0.95 / widest, ah / (1.25 * size * len(notes) + 1e-6) if ah > 4 * ppm else 1.0)
    size = max(size, 4.5 * ppm)
    pad = int(size)
    widths = [hand.text_width(t, size, font_name) * 1.1 for t in notes]
    block = Image.new("RGB", (int(max(widths)) + 2 * pad, int(size * 1.3 * len(notes)) + 2 * pad), "white")
    for i, text in enumerate(notes):
        hand.hand_text(block, (pad + rng.uniform(0, 0.4) * size * (i > 0), pad + size * (1.0 + 1.3 * i)), text, size,
                       rng, font_name=font_name, ink=ink, jitter=jitter)
    block = block.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
    bw, bh = block.size
    # a few spots in the area; keep the one whose writing covers the least print (the block can be bigger
    # than a cramped notes area and then spills over its edges)
    protect = _value_boxes(layout) + [b for b in (layout["header_bbox"],) if b]
    best, best_score = None, None
    for _ in range(8):
        cx = rng.uniform(ax0 + bw / 2 - pad, ax1 - bw / 2 + pad) if aw > bw - 2 * pad else (ax0 + ax1) / 2
        cy = rng.uniform(ay0 + bh / 2 - pad, ay1 - bh / 2 + pad) if ah > bh - 2 * pad else (ay0 + ay1) / 2
        cx = min(max(cx, bw / 2 - pad), page.width - bw / 2 + pad)
        cy = min(max(cy, bh / 2 - pad), page.height - bh / 2 + pad)
        b = (cx - bw / 2 + pad, cy - bh / 2 + pad, cx + bw / 2 - pad, cy + bh / 2 - pad)
        area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
        score = _busy(page, b, marks) + 2 * sum(_overlap(b, p) for p in protect) / area
        if best_score is None or score < best_score:
            best, best_score = (cx, cy), score
    cx, cy = best
    _multiply_at(marks, block, (cx - bw / 2, cy - bh / 2))
    box = [cx - bw / 2 + pad, cy - bh / 2 + pad, cx + bw / 2 - pad, cy + bh / 2 - pad]
    # one block holds all the lines; "box" is that block
    return [{"text": t, "box": box, "angle": angle, "size": size, "font": font_name, "ink": list(ink)} for t in notes]


def _ticks(marks, page, layout, rng, ppm, ink):
    """Receiver's ticks in front of some rows (before the description or before the quantity)."""
    rows = layout["rows"]
    if not rows or rng.random() > 0.45:
        return None
    style = "before_desc" if rng.random() < 0.7 else "before_qty"
    share = rng.uniform(0.5, 1.0)
    ticked = []
    for i, r in enumerate(rows):
        if rng.random() > share:
            continue
        size = int(min(max((r["y1"] - r["y0"]) * rng.uniform(0.55, 0.85), 2.5 * ppm), 6 * ppm))
        cy = (r["y0"] + r["y1"]) / 2 + rng.uniform(-0.15, 0.15) * size
        ref = r["qty"] if style == "before_qty" and r["qty"] else r["desc"]
        if not ref:
            continue
        x = ref[0] - size * rng.uniform(1.05, 1.4)
        if x < 2 or (style == "before_qty" and _busy(page, (x, cy - 0.6 * size, x + size, cy + 0.4 * size)) > 0.06):
            continue
        hand.tick(marks, (x, cy + 0.1 * size), size, rng, ink)
        ticked.append(i)
    return {"style": style, "rows": ticked} if ticked else None


def _signature(marks, page, layout, rng, ppm, ink):
    """A scribbled signature in a blank spot: by the letterhead, under the total or near the bottom."""
    if rng.random() > 0.75:
        return None
    pw, ph = page.size
    sw = rng.uniform(18, 30) * ppm
    sh = sw * 0.4
    cands = []
    hb, tb = layout["header_bbox"], layout["total_bbox"]
    if hb:
        hw, hh = hb[2] - hb[0], hb[3] - hb[1]
        cands.append((hb[2] - sw - rng.uniform(0, 0.2) * hw, hb[1] + rng.uniform(0, 0.5) * hh))
        cands.append((rng.uniform(0.35, 0.75) * pw, hb[1] - sh * rng.uniform(1.1, 1.6)))
    if tb:
        cands.append((tb[0] - rng.uniform(0, 0.5) * sw, tb[3] + sh * rng.uniform(0.6, 2.0)))
    cands.append((rng.uniform(0.5, 0.95) * pw - sw, ph - sh * rng.uniform(2.0, 5.0)))
    cands.append((rng.uniform(0.05, 0.4) * pw, ph - sh * rng.uniform(2.0, 5.0)))
    values = _value_boxes(layout) + layout.get("keep_clear", [])
    best, best_score = None, None
    for x, y in cands:
        b = (x, y, x + sw, y + sh)
        score = _busy(page, b, marks) + 5 * (not _inside(b, page.size, 4)) + \
            sum(_overlap(b, v) for v in values) / (sw * sh)
        if best_score is None or score < best_score:
            best, best_score = b, score
    x, y = best[0], best[1]
    style = _sign(marks, (x, y + sh / 2), sw, rng, ink)
    return {"box": list(best), "width": sw, "style": style}


def _sign(img, xy, width, rng, ink):
    """A signature with its middle line starting at xy: usually a big initial followed by joined-up loops and an
    underline flourish, sometimes hand.signature's zigzag scribble. Returns the style used."""
    x, y = xy
    if rng.random() < 0.3:
        hand.signature(img, (x, y), width, rng, ink)
        hand.pen_line(ImageDraw.Draw(img), [(x, y + width * 0.12), (x + width, y + width * 0.08)], rng, ink, width=2)
        return "scribble"
    h = width * rng.uniform(0.2, 0.32)
    font_name = rng.choice(["Kalam-Regular.ttf", "GochiHand-Regular.ttf", "Caveat.ttf", "ReenieBeanie.ttf"])
    box = hand.hand_text(img, (x, y + h * 0.45), rng.choice("ABDJKMPRSV"), h * 1.9, rng, font_name=font_name,
                         ink=ink, jitter=1.5)
    # a prolate trochoid makes loops like joined-up handwriting
    r, amp, slant = h * rng.uniform(0.1, 0.18), h * 0.55, rng.uniform(0.1, 0.4)
    phase = rng.uniform(0, 6)
    pts, t = [], 0.0
    while t < 300:
        a = amp * (0.65 + 0.35 * math.sin(0.4 * t + phase))
        dy = -a * math.cos(t)
        px = box[2] + r * t - a * math.sin(t) - slant * dy
        if px > x + width:
            break
        pts.append((px, y + dy))
        t += 0.3
    width_px = max(2, int(width / 70))
    d = ImageDraw.Draw(img)
    if len(pts) > 2:
        hand.pen_line(d, pts, rng, ink, width=width_px)
    if rng.random() < 0.7:
        y1 = y + h * rng.uniform(0.6, 1.0)
        hand.pen_line(d, [(x + width * 0.05, y1), (x + width * 0.6, y1 + h * 0.15), (x + width * 1.05, y1 - h * 0.3)],
                      rng, ink, width=width_px)
    return "loops"


# ----------------------------------------------------------------------------- the GOODS RECEIVED stamp

_heavy_cache = {}


def _heavy(size, weight=850, width=88):
    """Noto Sans at rubber-stamp weight (hand.font stops at 700) and slightly condensed."""
    key = (size, weight, width)
    if key not in _heavy_cache:
        f = ImageFont.truetype(str(hand.FONT_DIR / "NotoSans.ttf"), size)
        f.set_variation_by_axes([weight, width])
        _heavy_cache[key] = f
    return _heavy_cache[key]


def _fit_font(text, max_w, max_cap, weight=850, width=88):
    """Largest stamp font whose text fits max_w wide with capitals at most max_cap tall."""
    ref = _heavy(100, weight, width)
    cap = ref.getbbox("H")[3] - ref.getbbox("H")[1]
    size = min(100 * max_w / ref.getlength(text), 100 * max_cap / cap)
    return _heavy(max(6, int(size)), weight, width)


def _leaf_mark(d, x, y, size, mirror):
    """The little two-leaf sprout printed beside AEDEN FRESH."""
    for ang, length in ((-125 if mirror else -55, 1.0), (-35 if mirror else -145, 0.75)):
        a = math.radians(ang)
        ax, ay = math.cos(a), math.sin(a)
        nx, ny = -ay, ax
        pts = []
        for i in range(13):
            t = i / 12
            half = 0.28 * size * length * math.sin(math.pi * t) ** 0.8
            pts.append((x + ax * t * size * length + nx * half, y + ay * t * size * length + ny * half))
        for i in range(12, -1, -1):
            t = i / 12
            half = 0.28 * size * length * math.sin(math.pi * t) ** 0.8
            pts.append((x + ax * t * size * length - nx * half, y + ay * t * size * length - ny * half))
        d.polygon(pts, fill=255)
    d.line((x, y, x, y + 0.35 * size), fill=255, width=max(1, int(size * 0.1)))


def _draw_stamp(ppm, rng, nrng, branch, spec):
    """Draw the stamp unrotated: ink coverage (L), pen fill-ins (RGB on white), body and fill-in zone boxes."""
    u = ppm * rng.uniform(0.92, 1.06)          # stamp millimetres -> page pixels
    W, H = 74 * u, 110 * u
    pad = 4 * u
    cw, ch = int(W + 2 * pad), int(H + 2 * pad)
    alpha = Image.new("L", (cw, ch), 0)
    d = ImageDraw.Draw(alpha)
    x0, y0 = pad, pad
    cx = x0 + W / 2
    d.rounded_rectangle((x0, y0, x0 + W, y0 + H), radius=2.5 * u, outline=255, width=max(2, round(1.4 * u)))
    f = _fit_font("AEDEN FRESH", 0.72 * W, 7.5 * u, weight=900, width=85)
    d.text((cx, y0 + 10 * u), "AEDEN FRESH", font=f, fill=255, anchor="mm")
    tw = f.getlength("AEDEN FRESH")
    _leaf_mark(d, cx - tw / 2 - 3.8 * u, y0 + 11.5 * u, 5 * u, False)
    _leaf_mark(d, cx + tw / 2 + 3.8 * u, y0 + 11.5 * u, 5 * u, True)
    f = _fit_font("GREENS ANGAADI AGRO PVT LTD", 0.93 * W, 3.5 * u, weight=800, width=80)
    d.text((cx, y0 + 18.5 * u), "GREENS ANGAADI AGRO PVT LTD", font=f, fill=255, anchor="mm")
    d.line((x0 + 0.04 * W, y0 + 21.6 * u, x0 + 0.96 * W, y0 + 21.6 * u), fill=255, width=max(1, round(0.6 * u)))
    f = _fit_font(branch, 0.6 * W, 4.4 * u)
    gap = 1.0 * u
    bw = sum(f.getlength(c) for c in branch) + gap * (len(branch) - 1)
    x = cx - bw / 2
    for c in branch:
        d.text((x, y0 + 27 * u), c, font=f, fill=255, anchor="lm")
        x += f.getlength(c) + gap
    f = _fit_font("GOODS RECEIVED", 0.84 * W, 6.0 * u, weight=900, width=82)
    gw = f.getlength("GOODS RECEIVED")
    d.rectangle((cx - gw / 2 - 1.8 * u, y0 + 31.5 * u, cx + gw / 2 + 1.8 * u, y0 + 42.5 * u), outline=255,
                width=max(2, round(0.9 * u)))
    d.text((cx, y0 + 37.2 * u), "GOODS RECEIVED", font=f, fill=255, anchor="mm")
    labels = ["Store Name", "Received", "Name", "Date", "Checked by", "Signature"]
    ys = [52, 62, 72, 82, 92, 105]
    lf = _fit_font("Checked by", 23 * u, 3.8 * u, weight=800, width=75)
    colon_x = x0 + 30 * u
    for lab, yy in zip(labels, ys):
        base = y0 + yy * u
        d.text((x0 + 4 * u, base), lab, font=lf, fill=255, anchor="ls")
        d.text((colon_x, base), ":", font=lf, fill=255, anchor="ls")
        r = max(0.8, 0.3 * u)
        xx = colon_x + 2.5 * u
        while xx < x0 + W - 4 * u:
            d.ellipse((xx - r, base - r, xx + r, base + r), fill=255)
            xx += 1.1 * u

    alpha = _patchy(alpha, rng, nrng, u)

    # handwritten fill-ins, one writer for the whole stamp
    pen = Image.new("RGB", (cw, ch), "white")
    ink = rng.choice(BLUE_PENS)
    font_name = hand.hand_font(rng)
    size = rng.uniform(7, 9.5) * u
    slant = rng.uniform(-6, 6)
    fills = {}

    def write(row, text):
        base = y0 + ys[row] * u - rng.uniform(0.3, 2.2) * u + (-6 * u if rng.random() < 0.15 else 0)
        hand.hand_text(pen, (colon_x + rng.uniform(3, 12) * u, base), text, size, rng, font_name=font_name, ink=ink,
                       slant=slant, jitter=1.1)

    if rng.random() < 0.9:
        fills["store_name"] = rng.choice(STAMP_BRANCHES[branch])
        write(0, fills["store_name"])
    receiver = rng.choice(RECEIVERS)
    if rng.random() < 0.85:
        fills["received"] = receiver
        write(1, receiver)
    if rng.random() < 0.3:
        fills["name"] = receiver.split()[0]
        write(2, fills["name"])
    if rng.random() < 0.85:
        dt = date.fromisoformat(spec.get("invoice_date") or "2026-08-29") + timedelta(days=rng.choice([0, 0, 0, 1]))
        yy = dt.year % 100
        fills["date"] = rng.choice([f"{dt.day}/{dt.month:02d}/{yy}", f"{dt.day:02d}/{dt.month:02d}/{yy}",
                                    f"{dt.day}/{dt.month}/{yy}", f"{dt.day}.{dt.month:02d}.{dt.year}"])
        write(3, fills["date"])
    for row, key, p in ((4, "checked_by", 0.6), (5, "signature", 0.45)):
        if rng.random() < p:
            fills[key] = "(signature)"
            _sign(pen, (colon_x + rng.uniform(3, 12) * u, y0 + (ys[row] - 2.5) * u), rng.uniform(16, 28) * u, rng, ink)
    body = (x0, y0, x0 + W, y0 + H)
    meta = {"size_mm": [74 * u / ppm, 110 * u / ppm], "fills": fills, "fill_ink": list(ink), "fill_font": font_name}
    return alpha, pen, body, meta


def _patchy(alpha, rng, nrng, u):
    """Uneven rubber-stamp ink: blotchy pressure, a weaker side, specks the rubber missed, soft edges."""
    a = np.asarray(alpha, np.float32) / 255
    h, w = a.shape
    dens = 0.7 + 0.3 * _noise(nrng, w, h, 4)
    dens *= 0.82 + 0.18 * _noise(nrng, w, h, 28)
    ang = rng.uniform(0, 2 * math.pi)
    xx = (np.arange(w, dtype=np.float32)[None, :] - w / 2) * math.cos(ang)
    yy = (np.arange(h, dtype=np.float32)[:, None] - h / 2) * math.sin(ang)
    ramp = (xx + yy) / (0.5 * math.hypot(w, h)) * 0.5 + 0.5
    dens *= 1 - rng.uniform(0, 0.4) * ramp
    hs, ws = max(2, int(h / max(1.5, u * 0.5))), max(2, int(w / max(1.5, u * 0.5)))
    holes = (nrng.random((hs, ws)) < rng.uniform(0.03, 0.15)).astype(np.float32)
    holes = np.asarray(Image.fromarray(holes, "F").resize((w, h), Image.BILINEAR), np.float32)
    dens *= 1 - 0.8 * holes.clip(0, 1)
    a = a * dens.clip(0, 1)
    img = Image.fromarray((a * 255).astype(np.uint8), "L")
    return img.filter(ImageFilter.GaussianBlur(max(0.4, 0.22 * u)))


def _stamp(marks, page, layout, spec, rng, nrng, ppm, difficulty):
    if rng.random() > 0.85:
        return None
    branch = "KAKKANAD" if rng.random() < 0.85 else "TRIPUNITHURA"
    alpha, pen, body, meta = _draw_stamp(ppm, rng, nrng, branch, spec)
    ink = rng.choice(STAMP_INKS)
    faint = rng.random() < 0.08
    opacity = rng.uniform(0.3, 0.5) if faint else rng.uniform(0.82, 0.98)
    # fairness: the stamp must stay clearly lighter than the print it covers, or the digits under it get lost
    # (matters for faint dot-matrix / carbon print; black toner allows a full-strength stamp)
    print_lum = _print_darkness(page, layout)
    ink_lum = 0.299 * ink[0] + 0.587 * ink[1] + 0.114 * ink[2]
    max_opacity = min(1.0, max(0.45, (255 - print_lum - 70) / (255 - ink_lum)))
    opacity = min(opacity, max_opacity)
    # fairness again: a full-strength impression over small print hides digits under its bold letters (seen on
    # gst_modern / software rows at ~23 px a row: "20.94" under the H of FRESH became unreadable). So where the
    # stamp covers numbers or the letterhead it is pressed lighter, lightest when its bold title block lies on
    # small print; big handwriting and large print take a darker stamp. row_px is a rough row height in the photo,
    # from the digit height when that is smaller (carbon prints 9 px digits in 36 px rows).
    row_px = min(_row_height(layout, ppm), 2.6 * _text_height(layout, ppm)) * FINAL_LONG / max(page.size)
    small_print = row_px < 32
    place = _place_stamp(alpha.size, body, pen, layout, page, rng, difficulty, small_print)
    if max(place["on_numbers"], place["on_header"], place["on_key"]) > 0.02:
        if small_print and place["title_on_print"] > 0.02:
            opacity = min(opacity, 0.48)
        else:
            opacity = min(opacity, 0.6 + 0.3 * min(max((row_px - 24) / 16, 0.0), 1.0))
        if small_print:      # faint small dot-matrix / carbon print: keep the stamp a good deal lighter than it
            opacity = min(opacity, max(0.3, (255 - print_lum - 100) / (255 - ink_lum)))
    alpha = alpha.point(lambda v: int(v * opacity))
    angle, (cx, cy) = place["angle"], place["center"]
    a = alpha.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=0)
    p = pen.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
    xy = (cx - a.width / 2, cy - a.height / 2)
    _multiply_at(marks, _ink_layer(a, ink), xy)
    _multiply_at(marks, p, xy)
    return {"branch": branch, "angle_deg": angle, "center": [cx, cy], "ink": list(ink), "opacity": opacity,
            "print_lum": print_lum, "row_px_estimate": row_px, "faint": faint, **meta,
            **{k: v for k, v in place.items() if k not in ("angle", "center")}}


def _print_darkness(page, layout):
    """Luminance of the printed digits (1st percentile inside the value boxes; the table if there are none)."""
    boxes = _value_boxes(layout) or [b for b in (layout["table_bbox"],) if b]
    if not boxes:
        return 30.0
    lum = []
    for x0, y0, x1, y1 in boxes[:60]:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(page.width, int(x1)), min(page.height, int(y1))
        if x1 > x0 and y1 > y0:
            lum.append(np.asarray(page.crop((x0, y0, x1, y1)).convert("L"), np.float32).ravel())
    lum = np.concatenate(lum) if lum else np.zeros(0)
    return float(np.percentile(lum, 1)) if lum.size else 30.0


def _place_stamp(canvas, body, pen, layout, page, rng, difficulty, small_print=False):
    """Try many centres/angles; keep the one that best fits the difficulty.
    The handwritten fill-ins (pen, RGB on white, canvas-sized) never go over the numbers; easy keeps the whole
    stamp off them too, hard puts the stamp body right over them. With small print the bold title block
    (AEDEN FRESH ... GOODS RECEIVED, the top 40% of the body) prefers to keep off the numbers."""
    pw, ph = page.size
    cw, ch = canvas
    table, header, total = layout["table_bbox"], layout["header_bbox"], layout["total_bbox"]
    bw, bh = body[2] - body[0], body[3] - body[1]
    title = (body[0], body[1], body[2], body[1] + bh * 43.5 / 110)
    r = rng.random()
    mode = "table" if table and r < 0.8 else "below" if r < 0.93 else "top"
    g = max(4.0, max(pw, ph) / 220)          # scoring raster: one cell = g page px
    m = int(max(cw, ch) / g)
    gw, gh = int(pw / g) + 2 * m, int(ph / g) + 2 * m

    def raster(boxes):
        im = Image.new("L", (gw, gh), 0)
        dr = ImageDraw.Draw(im)
        for b in boxes:
            dr.rectangle(((b[0]) / g + m, b[1] / g + m, b[2] / g + m, b[3] / g + m), fill=1)
        return np.asarray(im, bool)

    values = raster(_value_boxes(layout))
    key = raster([layout[k] for k in ("total_bbox", "invoice_number_bbox", "date_bbox") if layout[k]] +
                 layout.get("keep_clear", []))
    header_m = raster([header] if header else [])
    guarded = values | key | header_m          # numbers, invoice no / date / totals and the letterhead (GSTIN)
    table_m = raster([table] if table else [])
    page_m = np.zeros((gh, gw), bool)
    page_m[m:m + int(ph / g), m:m + int(pw / g)] = True
    # cells with printed text (not just a ruled line): the fill-ins rather go on blank paper
    print_m = np.zeros((gh, gw), bool)
    small = page.convert("L").resize((max(1, int(pw / g)), max(1, int(ph / g))), Image.BOX)
    print_m[m:m + small.height, m:m + small.width] = np.asarray(small) < 215

    def poly(rect, angle, cx, cy):
        pts = []
        for px, py in ((rect[0], rect[1]), (rect[2], rect[1]), (rect[2], rect[3]), (rect[0], rect[3])):
            dx, dy = _rot(px - cw / 2, py - ch / 2, angle)
            pts.append(((cx + dx) / g + m, (cy + dy) / g + m))
        im = Image.new("L", (gw, gh), 0)
        ImageDraw.Draw(im).polygon(pts, fill=1)
        return np.asarray(im, bool)

    # the fill-in handwriting itself (not a box around it) at raster resolution, so the score sees exactly
    # where the pen ink lands
    pen_small = pen.convert("L").point(lambda v: 255 - v).resize((max(1, round(cw / g)), max(1, round(ch / g))),
                                                                   Image.BOX)

    def pen_cells(angle, cx, cy):
        r = np.asarray(pen_small.rotate(angle, resample=Image.BILINEAR, expand=True)) > 8
        out = np.zeros((gh, gw), bool)
        x, y = int(round(cx / g + m - r.shape[1] / 2)), int(round(cy / g + m - r.shape[0] / 2))
        x0, y0, x1, y1 = max(0, x), max(0, y), min(gw, x + r.shape[1]), min(gh, y + r.shape[0])
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = r[y0 - y:y1 - y, x0 - x:x1 - x]
        return out

    bottom = max(table[3] if table else ph * 0.5, total[3] if total else 0)

    def region(where, ew, eh):
        if where == "table":
            return (table[0] + 0.25 * ew, table[2] - 0.25 * ew,
                    table[1] + 0.2 * eh, max(table[1] + 0.2 * eh, table[3] + 0.1 * eh))
        if where == "below":
            return 0.08 * pw + ew / 2, 0.92 * pw - ew / 2, bottom + 0.4 * eh, ph - 0.45 * eh
        if where == "top":     # beside or just under the letterhead
            hb = header or (0, 0, pw, ph * 0.25)
            return pw * 0.4, pw - 0.45 * ew, hb[1] + 0.3 * eh, hb[3] + 0.5 * eh
        return ew * 0.45, pw - ew * 0.45, eh * 0.45, ph - eh * 0.45      # anywhere on the page

    def candidate(where):
        angle = rng.uniform(-45, 45)
        c, s = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
        ew, eh = bw * c + bh * s, bw * s + bh * c
        x_lo, x_hi, y_lo, y_hi = region(where, ew, eh)
        if x_hi < x_lo:
            x_lo = x_hi = (x_lo + x_hi) / 2
        if y_hi < y_lo:
            y_lo = y_hi = min(max((y_lo + y_hi) / 2, eh * 0.45), ph - eh * 0.45)
        cx, cy = rng.uniform(x_lo, x_hi), rng.uniform(y_lo, y_hi)
        bm, fm = poly(body, angle, cx, cy), pen_cells(angle, cx, cy)
        area, farea = max(1, bm.sum()), max(1, fm.sum())
        inside = (bm & page_m).sum() / area
        on_values = (bm & values).sum() / area
        # pen over a printed number makes it unreadable whatever the difficulty
        fill_values = (fm & values).sum() / farea
        fill_key = (fm & key).sum() / farea
        fill_header = (fm & header_m).sum() / farea
        fill_print = (fm & print_m).sum() / farea
        over_table = (bm & table_m).sum() / area
        on_header = (bm & header_m).sum() / area       # the supplier name and GSTIN live here
        on_key = (bm & key).sum() / area
        if difficulty == "easy":
            score = -2 * on_values - 3 * on_header - 3 * on_key
        elif difficulty == "medium":
            score = 0.3 * on_values - 3 * on_header - 2 * on_key
        else:
            score = 0.8 * min(on_values, 0.3) - 2 * on_header - 0.5 * on_key
        tm = poly(title, angle, cx, cy)
        title_values = (tm & guarded).sum() / max(1, tm.sum())
        score += -10 * fill_values - 6 * fill_key - 3 * fill_header - 1.5 * fill_print - \
            6 * max(0.0, 0.88 - inside) - (1.5 * title_values if small_print else 0) + rng.uniform(0, 0.15)
        return score, {"angle": angle, "center": [cx, cy], "placement": where, "over_table": over_table >= 0.25,
                       "on_numbers": on_values, "title_on_print": title_values, "fill_on_numbers": fill_values,
                       "on_header": on_header, "on_key": on_key, "inside_page": inside}

    best = max((candidate(mode) for _ in range(40)), key=lambda c: c[0])
    # the preferred spot is too cramped to keep the handwriting off the numbers: look over the whole page
    if best[1]["fill_on_numbers"] > 0.005 or best[1]["inside_page"] < 0.85 or \
            (difficulty == "easy" and best[1]["on_numbers"] > 0.12):
        best = max([best] + [candidate("free") for _ in range(60)], key=lambda c: c[0])
    return best[1]


# ----------------------------------------------------------------------------- paper

def _paper(img, paper, rng, nrng, k, mm):
    """Tint, fibre texture, fold creases and the shading of a curled edge. mm = px per mm at this scale."""
    arr = np.asarray(img, np.float32)
    h, w = arr.shape[:2]
    target = np.array(PAPER[paper], np.float32) + np.array([rng.uniform(-3, 3) for _ in range(3)], np.float32)
    bg = np.percentile(arr.reshape(-1, 3)[::7], 90, axis=0)
    gain = (target / np.maximum(bg, 1)).clip(0.4, 1.3)
    arr *= gain
    grain = rng.uniform(0.008, 0.018)
    shade = 1 + nrng.normal(0, grain, (h, w)).astype(np.float32)
    shade += 0.03 * (_noise(nrng, w, h, 10) - 0.5) + 0.02 * (_noise(nrng, w, h, 60) - 0.5)
    xx = np.arange(w, dtype=np.float32)[None, :]
    yy = np.arange(h, dtype=np.float32)[:, None]
    creases = []
    if rng.random() < k["crease"]:
        for i in range(1 if rng.random() < 0.7 else 2):
            horizontal = (i == 0 and rng.random() < 0.75) or (i == 1 and not creases[0]["horizontal"])
            pos = rng.choice([0.5, 1 / 3, 2 / 3]) + rng.uniform(-0.04, 0.04)
            tilt = math.tan(math.radians(rng.uniform(-2.5, 2.5)))
            depth = rng.uniform(0.04, 0.14)
            width = rng.uniform(0.5, 1.5) * mm
            step = rng.uniform(0, 0.06)
            side = rng.choice([-1, 1])
            if horizontal:
                d = yy - (pos * h + tilt * (xx - w / 2))
            else:
                d = xx - (pos * w + tilt * (yy - h / 2))
            shade *= 1 - depth * np.exp(-(d / width) ** 2)
            shade *= 1 + 0.5 * depth * np.exp(-((d - side * 2 * width) / (1.5 * width)) ** 2)
            shade *= np.where(d * side > 0, 1 - step, 1).astype(np.float32)
            creases.append({"horizontal": horizontal, "pos": pos, "tilt": tilt, "depth": depth, "width_mm": width / mm,
                            "panel_step": step})
    curl = None
    amount = _u(rng, k["curl"])
    if amount > 0.002:
        edge = rng.choice(["bottom", "bottom", "top", "left", "right"])
        t = {"bottom": yy / h, "top": 1 - yy / h, "right": xx / w, "left": 1 - xx / w}[edge]
        shade *= 1 - amount * rng.uniform(3, 8) * t ** 3
        curl = {"edge": edge, "amount": amount, "bow": rng.uniform(-1, 1), "lift": rng.uniform(-0.3, 1.0)}
    arr *= shade[..., None]
    out = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")
    return out, {"tint": target.tolist(), "grain": grain, "creases": creases, "curl": curl}


def _curl_mesh(img, curl, pad):
    """Bend the page near one edge (Image.MESH). img is the page padded by `pad` transparent pixels."""
    W, H = img.size
    w, h = W - 2 * pad, H - 2 * pad
    edge, amount, bow, lift = curl["edge"], curl["amount"], curl["bow"], curl["lift"]

    def disp(x, y):
        px, py = (x - pad) / w, (y - pad) / h
        along = py if edge in ("left", "right") else px
        t = {"bottom": py, "top": 1 - py, "right": px, "left": 1 - px}[edge]
        t = min(max(t, 0.0), 1.0)
        mag = amount * (h if edge in ("top", "bottom") else w) * t ** 3 * (lift + bow * (2 * along - 1) ** 2)
        sign = 1 if edge in ("bottom", "right") else -1
        return (0, sign * mag) if edge in ("top", "bottom") else (sign * mag, 0)

    n = 16
    mesh = []
    for i in range(n):
        for j in range(n):
            x0, x1 = W * j / n, W * (j + 1) / n
            y0, y1 = H * i / n, H * (i + 1) / n
            quad = []
            for qx, qy in ((x0, y0), (x0, y1), (x1, y1), (x1, y0)):
                dx, dy = disp(qx, qy)
                quad += [qx - dx, qy - dy]
            mesh.append(((int(x0), int(y0), int(x1), int(y1)), quad))
    return img.transform(img.size, Image.MESH, mesh, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))


# ----------------------------------------------------------------------------- photo geometry

def _content_box(layout, recipe, size, ppm):
    """Everything a reader needs (letterhead, table, totals, marks) - this must stay inside the photo."""
    boxes = [layout[k] for k in ("header_bbox", "table_bbox", "total_bbox", "invoice_number_bbox", "date_bbox")]
    boxes += [n["box"] for n in recipe["notes"]]
    if recipe["invoice_correction"]:
        boxes.append(recipe["invoice_correction"]["box"])
    box = _union(boxes)
    if not box:
        return (0, 0, size[0], size[1])
    pad = 3 * ppm
    return (max(0, box[0] - pad), max(0, box[1] - pad), min(size[0], box[2] + pad), min(size[1], box[3] + pad))


def _homography(src, dst):
    """3x3 matrix H with dst ~ H @ src for four point pairs."""
    a, b = [], []
    for (x, y), (X, Y) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        b.append(X)
        a.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
        b.append(Y)
    h = np.linalg.solve(np.array(a, float), np.array(b, float))
    return np.append(h, 1).reshape(3, 3)


def _map(H, x, y):
    v = H @ np.array([x, y, 1.0])
    return v[0] / v[2], v[1] / v[2]


def _place_page(size, content, fw, fh, rng, k, underlay):
    """Where the page lands in the (upright) frame: scale, skew, perspective. The content box must stay inside;
    the page's own blank margins may be cut off by the frame like in real photos."""
    pw, ph = size
    fill = _u(rng, k["fill"])
    skew = rng.uniform(-k["skew"], k["skew"])
    persp = _u(rng, k["persp"])
    jit = [(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(4)]
    keystone = (rng.choice(["top", "bottom", "left", "right"]), rng.uniform(0.3, 1.0))
    off = (rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6))    # photographers roughly centre the bill
    top_gap = rng.uniform(0.07, 0.11) if underlay else 0.0
    margin = 0.012 * max(fw, fh)
    for _ in range(60):
        s = fill * min(fw / pw, fh * (1 - top_gap) / ph)
        w, h = pw * s, ph * s
        cx = fw / 2 + off[0] * max(0.0, fw - w) / 2 * 0.9
        cy = fh / 2 + off[1] * max(0.0, fh - h) / 2 * 0.9 + top_gap * fh / 2
        corners = []
        for i, (x, y) in enumerate(((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))):
            side, amt = keystone   # one edge a little shorter: the phone was tilted towards it
            if side == "top" and i < 2 or side == "bottom" and i >= 2:
                x *= 1 - persp * amt
            if side == "left" and i in (0, 3) or side == "right" and i in (1, 2):
                y *= 1 - persp * amt
            x += jit[i][0] * persp * 0.5 * w
            y += jit[i][1] * persp * 0.5 * h
            dx, dy = _rot(x, y, skew)
            corners.append((cx + dx, cy + dy))
        H = _homography([(0, 0), (pw, 0), (pw, ph), (0, ph)], corners)
        cpts = [_map(H, x, y) for x, y in ((content[0], content[1]), (content[2], content[1]),
                                           (content[2], content[3]), (content[0], content[3]))]
        ok = all(margin <= x <= fw - margin and margin <= y <= fh - margin for x, y in cpts)
        if underlay:
            ok = ok and min(corners[0][1], corners[1][1]) >= top_gap * fh * 0.9
        if ok:
            break
        fill *= 0.98
        off = (off[0] * 0.85, off[1] * 0.85)
    return {"scale": s, "corners": corners, "fill": fill, "skew": skew,
            "persp": {"amount": persp, "keystone": keystone[0]}}


def _composite_page(frame, small, geo, curl, rng):
    """Warp the (downscaled) page into the frame with its curl and a soft drop shadow."""
    fw, fh = frame.size
    w, h = small.size
    pad = int(0.04 * max(w, h)) if curl else 0
    rgba = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    rgba.paste(small.convert("RGBA"), (pad, pad))
    if curl:
        rgba = _curl_mesh(rgba, curl, pad)
    H = _homography([(pad, pad), (pad + w, pad), (pad + w, pad + h), (pad, pad + h)], geo["corners"])
    inv = np.linalg.inv(H)
    inv = inv / inv[2, 2]
    warped = rgba.transform((fw, fh), Image.PERSPECTIVE, tuple(inv.flatten()[:8]), resample=Image.BICUBIC,
                            fillcolor=(0, 0, 0, 0))
    # drop shadow: the page edge lifts a little off whatever is under it
    shadow = warped.getchannel("A").filter(ImageFilter.GaussianBlur(0.006 * max(fw, fh)))
    off = (rng.randint(-3, 6), rng.randint(-2, 8))
    strength = rng.uniform(0.25, 0.5)
    moved = Image.new("L", shadow.size, 0)
    moved.paste(shadow, off)          # shift without wrapping round the frame edges
    shadow = moved.point(lambda v: 255 - int(v * strength))
    base = ImageChops.multiply(frame, Image.merge("RGB", (shadow, shadow, shadow)))
    out = Image.alpha_composite(base.convert("RGBA"), warped)
    return out.convert("RGB")


# ----------------------------------------------------------------------------- background

def _background(fw, fh, rng, nrng, mm, page_corners):
    """What shows around the bill: other bills on a desk, the desk itself or a laptop keyboard.
    mm = frame px per millimetre (for text and key sizes)."""
    kind = _pick(rng, {"papers": 62, "desk": 20, "laptop": 18})
    info = {"kind": kind}
    if kind == "laptop":
        deck = rng.choice([(176, 178, 182), (60, 62, 66), (140, 142, 148)])
        img = Image.new("RGB", (fw, fh), deck)
        _keyboard(img, rng, mm, full=True)
        info["deck"] = list(deck)
    else:
        name = rng.choice(list(DESKS)) if kind == "desk" else rng.choice(["grey laminate", "white table", "wood"])
        img = _desk(fw, fh, DESKS[name], name, rng, nrng)
        info["desk"] = name
        if kind == "papers":
            info["sheets"] = rng.randint(1, 3)
            for _ in range(info["sheets"]):
                _other_sheet(img, rng, mm)
        if rng.random() < 0.3:
            info["keyboard"] = _keyboard(img, rng, mm, full=False)
    info["stack"] = 0
    if rng.random() < 0.4:      # the rest of the day's bills under this one, edges peeking out
        info["stack"] = rng.randint(1, 3)
        d = ImageDraw.Draw(img)
        cx = sum(x for x, _ in page_corners) / 4
        cy = sum(y for _, y in page_corners) / 4
        for _ in range(info["stack"]):
            ang = rng.uniform(-2.5, 2.5)
            sx, sy = rng.uniform(-1, 1) * 0.015 * fw, rng.uniform(-1, 1) * 0.015 * fh
            pts = []
            for x, y in page_corners:
                dx, dy = _rot(x - cx, y - cy, ang)
                pts.append((cx + dx * 1.01 + sx, cy + dy * 1.01 + sy))
            col = rng.choice([(238, 238, 234), (244, 243, 238), (232, 233, 230)]) if rng.random() < 0.8 else \
                rng.choice([(240, 170, 190), (240, 232, 170)])
            shadow = [(x + 3, y + 4) for x, y in pts]
            d.polygon(shadow, fill=tuple(int(c * 0.75) for c in col))
            d.polygon(pts, fill=col, outline=tuple(int(c * 0.85) for c in col))
    return img, info


def _desk(fw, fh, color, name, rng, nrng):
    arr = np.ones((fh, fw, 3), np.float32) * np.array(color, np.float32)
    shade = 1 + 0.12 * (_noise(nrng, fw, fh, 4) - 0.5) + 0.05 * (_noise(nrng, fw, fh, 40) - 0.5)
    shade += nrng.normal(0, rng.uniform(0.01, 0.03), (fh, fw)).astype(np.float32)   # laminate speckle
    if "wood" in name:
        ang = rng.uniform(0, math.pi)
        xx = np.arange(fw, dtype=np.float32)[None, :] * math.cos(ang)
        yy = np.arange(fh, dtype=np.float32)[:, None] * math.sin(ang)
        period = rng.uniform(0.01, 0.03) * fw
        shade *= 1 + 0.07 * np.sin(2 * math.pi * (xx + yy) / period + 6 * _noise(nrng, fw, fh, 5))
    arr *= shade[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def _other_sheet(img, rng, mm):
    """Another bill lying on the desk: white sheet with a few printed words and lines, slightly rotated."""
    fw, fh = img.size
    layer = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    side = rng.choice(["left", "right", "top", "bottom"])
    x0, y0, x1, y1 = -0.1 * fw, -0.1 * fh, 1.1 * fw, 1.1 * fh
    cut = rng.uniform(0.25, 0.75)
    if side == "left":
        x1 = cut * fw
    elif side == "right":
        x0 = cut * fw
    elif side == "top":
        y1 = cut * fh
    else:
        y0 = cut * fh
    col = rng.choice([(240, 240, 236), (246, 245, 240), (236, 237, 234)])
    d.rectangle((x0 + 4, y0 + 5, x1 + 4, y1 + 5), fill=(0, 0, 0, 60))
    d.rectangle((x0, y0, x1, y1), fill=col + (255,))
    ink = (40, 40, 45, 255)
    y = y0 + rng.uniform(6, 20) * mm
    while y < y1 - 4 * mm:
        size = rng.choice([3.2, 3.6, 4.2, 4.2, 5, 7, 10]) * mm
        f = hand.font(rng.choice(["sans", "narrow", "serif"]), max(8, int(size)), bold=rng.random() < 0.4)
        x = x0 + rng.uniform(8, 30) * mm
        for _ in range(rng.randint(1, 3)):
            word = rng.choice(PAPER_WORDS)
            d.text((x, y), word, font=f, fill=ink)
            x += f.getlength(word) + rng.uniform(10, 60) * mm
        if rng.random() < 0.3:
            d.line((x0 + 8 * mm, y + size * 1.5, x1 - 8 * mm, y + size * 1.5), fill=ink, width=max(1, int(0.3 * mm)))
        y += size * rng.uniform(1.8, 3.0)
    layer = layer.rotate(rng.uniform(-6, 6), resample=Image.BICUBIC)
    img.paste(layer, (0, 0), layer)


def _keyboard(img, rng, mm, full):
    """A laptop keyboard: full frame (the bill lies on the laptop) or a band along one edge."""
    fw, fh = img.size
    layer = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    deck = rng.choice([(176, 178, 182), (60, 62, 66), (150, 152, 158)])
    key = (40, 40, 44) if rng.random() < 0.7 else (225, 225, 228)
    label = (225, 225, 230) if key[0] < 100 else (50, 50, 55)
    side = rng.choice(["top", "right", "left", "bottom"])
    depth = 1.0 if full else rng.uniform(0.15, 0.32)
    x0, y0, x1, y1 = 0, 0, fw, fh
    if not full:
        if side == "top":
            y1 = depth * fh
        elif side == "bottom":
            y0 = (1 - depth) * fh
        elif side == "left":
            x1 = depth * fw
        else:
            x0 = (1 - depth) * fw
    d.rectangle((x0, y0, x1, y1), fill=deck + (255,))
    pitch, ks = 19 * mm, 15.5 * mm
    f = hand.font("sans", max(8, int(2.8 * mm)))
    y = y0 + rng.uniform(0, pitch)
    while y < y1:
        x = x0 + rng.uniform(-pitch, 0)
        while x < x1:
            d.rounded_rectangle((x, y, x + ks, y + ks), radius=1.5 * mm, fill=key + (255,))
            d.text((x + 2 * mm, y + 2 * mm), rng.choice(KEY_LABELS), font=f, fill=label + (255,))
            x += pitch
        y += pitch
    layer = layer.rotate(rng.uniform(-12, 12), resample=Image.BICUBIC)
    img.paste(layer, (0, 0), layer)
    return {"side": "all" if full else side, "depth": depth}


def _underlay(frame, page_size, geo, spec, rng, mm):
    """Another supplier's bill under this one, its top edge (with its GSTIN line) visible above our page."""
    sup = (spec.get("supplier") or {}).get("gstin")
    gstin = sup
    while gstin == sup:
        gstin = make_gstin(rng, rng.choice(["32", "32", "32", "33"]), rng.choice(["prop", "pvt", "firm"]))
    w, h = page_size
    sheet = Image.new("RGBA", (w, h), rng.choice([(244, 244, 240), (240, 241, 238), (246, 240, 225)]) + (255,))
    d = ImageDraw.Draw(sheet)
    f = hand.font(rng.choice(["sans", "narrow", "mono"]), max(10, int(4.4 * mm)), bold=True)
    text = rng.choice(["GSTIN : ", "GSTIN: ", "GSTIN No : ", "GST No. "]) + gstin
    tx, ty = rng.uniform(8, 25) * mm, rng.uniform(8, 14) * mm
    d.text((tx, ty), text, font=f, fill=(30, 30, 35, 255), anchor="ls")
    tb = d.textbbox((tx, ty), text, font=f, anchor="ls")
    if rng.random() < 0.5:
        f2 = hand.font("sans", max(10, int(4.4 * mm)), bold=True)
        d.text((w * 0.55, ty), "TAX INVOICE", font=f2, fill=(30, 30, 35, 255), anchor="ls")
    d.line((tx, ty + 4 * mm, w - tx, ty + 4 * mm), fill=(40, 40, 45, 255), width=max(1, int(0.3 * mm)))
    # same pose as our page, nudged sideways, slightly turned, shifted up so the GSTIN line sits in the gap
    c = geo["corners"]
    cx, cy = sum(x for x, _ in c) / 4, sum(y for _, y in c) / 4
    ang = rng.uniform(-1.5, 1.5)
    dx = rng.uniform(-0.04, 0.04) * frame.width
    quad = []
    for x, y in c:
        rx, ry = _rot(x - cx, y - cy, ang)
        quad.append((cx + rx + dx, cy + ry))
    H = _homography([(0, 0), (w, 0), (w, h), (0, h)], quad)
    _, text_y = _map(H, (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2)
    page_top = min(c[0][1], c[1][1])
    shift = page_top * rng.uniform(0.35, 0.55) - text_y
    quad = [(x, y + shift) for x, y in quad]
    H = _homography([(0, 0), (w, 0), (w, h), (0, h)], quad)
    inv = np.linalg.inv(H)
    inv = inv / inv[2, 2]
    warped = sheet.transform(frame.size, Image.PERSPECTIVE, tuple(inv.flatten()[:8]), resample=Image.BICUBIC,
                             fillcolor=(0, 0, 0, 0))
    frame.paste(warped, (0, 0), warped)
    text_quad = [_map(H, x, y) for x, y in ((tb[0], tb[1]), (tb[2], tb[1]), (tb[2], tb[3]), (tb[0], tb[3]))]
    return {"gstin": gstin, "text": text, "edge": "top", "text_quad": text_quad}


# ----------------------------------------------------------------------------- light and camera

def _soft_shape(fw, fh, rng, draw_fn, blur):
    """Draw a shape at 1/8 scale, blur it and scale up: a cheap soft mask in [0, 1]."""
    sw, sh = max(8, fw // 8), max(8, fh // 8)
    m = Image.new("L", (sw, sh), 0)
    draw_fn(ImageDraw.Draw(m), sw, sh)
    m = m.filter(ImageFilter.GaussianBlur(blur * max(sw, sh)))
    return np.asarray(m.resize((fw, fh), Image.BICUBIC), np.float32) / 255


def _lighting(arr, corners, rng, k, difficulty):
    """Uneven light (gradient, vignette, a phone/hand shadow), white balance, the phone's low-contrast tone curve
    (paper ~180-230, print ~20-65 like the real photos) and occasional glare."""
    fh, fw = arr.shape[:2]
    info = {}
    light = np.ones((fh, fw), np.float32)
    # gradient across the frame
    g = _u(rng, k["gradient"])
    ang = rng.uniform(0, 2 * math.pi)
    xx = (np.arange(fw, dtype=np.float32)[None, :] / fw - 0.5) * math.cos(ang)
    yy = (np.arange(fh, dtype=np.float32)[:, None] / fh - 0.5) * math.sin(ang)
    light *= 1 + g * 2 * (xx + yy)
    vig = rng.uniform(0.03, 0.15)
    rx = (np.arange(fw, dtype=np.float32)[None, :] / fw - 0.5) * 2
    ry = (np.arange(fh, dtype=np.float32)[:, None] / fh - 0.5) * 2
    light *= 1 - vig * (rx ** 2 + ry ** 2) / 2
    info.update(gradient=g, gradient_angle=math.degrees(ang), vignette=vig)
    # shadow of the phone / hand / person holding it
    strength = _u(rng, k["shadow"])
    info["shadow"] = None
    if strength > 0.03:
        kind = rng.choice(["phone", "hand", "edge"])
        side = rng.choice(["top", "bottom", "left", "right"])
        depth = rng.uniform(0.2, 0.5)

        def draw(d, w, h):
            if kind == "edge":
                a, b = rng.uniform(0.1, 0.5) * depth, rng.uniform(0.6, 1.4) * depth
                pts = {"top": [(0, 0), (w, 0), (w, b * h), (0, a * h)],
                       "bottom": [(0, h), (w, h), (w, h - b * h), (0, h - a * h)],
                       "left": [(0, 0), (0, h), (b * w, h), (a * w, 0)],
                       "right": [(w, 0), (w, h), (w - b * w, h), (w - a * w, 0)]}[side]
                d.polygon(pts, fill=255)
                return
            pos = rng.uniform(0.2, 0.8)
            bw, bh = (rng.uniform(0.3, 0.5) * w, rng.uniform(0.5, 0.8) * h) if kind == "phone" else \
                (rng.uniform(0.35, 0.55) * w, rng.uniform(0.35, 0.55) * h)
            if side in ("top", "bottom"):
                x0 = pos * w - bw / 2
                y0 = -bh + depth * h if side == "top" else h - depth * h
            else:
                y0 = pos * h - bh / 2
                x0 = -bw + depth * w if side == "left" else w - depth * w
            if kind == "phone":
                d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=0.12 * bw, fill=255)
            else:
                d.ellipse((x0, y0, x0 + bw, y0 + bh), fill=255)
                for i in range(4):     # fingers
                    fx = x0 + bw * (0.1 + 0.22 * i)
                    d.ellipse((fx, y0 - 0.3 * bh, fx + 0.16 * bw, y0 + 0.5 * bh), fill=255)

        mask = _soft_shape(fw, fh, rng, draw, rng.uniform(0.04, 0.09))
        light *= 1 - strength * mask
        info["shadow"] = {"kind": kind, "side": side, "depth": depth, "strength": strength}
    # gradient, vignette and shadow together may not darken the paper below `floor` (soft limit)
    floor = {"easy": 0.8, "medium": 0.68, "hard": 0.58}[difficulty]
    dark = (1 - light).clip(0, None)
    light = np.where(light < 1, 1 - (1 - floor) * np.tanh(dark / (1 - floor)), light).astype(np.float32)
    info["light_floor"] = floor
    # tube-light / daylight white balance: mostly a little warm (real paper reads ~ 202,201,193)
    if rng.random() < 0.75:
        info["colour_cast"] = [1 + rng.uniform(0, 0.025), 1.0, 1 - rng.uniform(0.02, 0.07)]
    else:
        info["colour_cast"] = [1 - rng.uniform(0, 0.02), 1.0, 1 + rng.uniform(0, 0.03)]
    cast = np.array(info["colour_cast"], np.float32)
    white, black, gamma = _u(rng, k["white"]), _u(rng, k["black"]), rng.uniform(0.9, 1.15)
    info.update(white=white, black=black, gamma=gamma)
    x = (arr / 255) * light[..., None] * cast
    out = black + (white - black) * np.clip(x, 0, 1.15) ** gamma
    # glare: a washed-out patch where the tube light reflects
    info["glare"] = None
    if rng.random() < k["glare"]:
        gs = _u(rng, k["glare_strength"])
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        gx, gy = rng.uniform(min(xs), max(xs)) / fw, rng.uniform(min(ys), max(ys)) / fh
        gr = (rng.uniform(0.08, 0.25), rng.uniform(0.06, 0.2))
        mask = _soft_shape(fw, fh, rng, lambda d, w, h: d.ellipse(((gx - gr[0]) * w, (gy - gr[1]) * h,
                                                                   (gx + gr[0]) * w, (gy + gr[1]) * h), fill=255), 0.06)
        out += (255 - out) * gs * mask[..., None]
        info["glare"] = {"center": [gx, gy], "radius": list(gr), "strength": gs}
    return out, info


def _camera(arr, rng, nrng, k, row_px, text_px, mm_px, difficulty):
    """Defocus, a little hand shake, sensor noise, the downscale to 1280 and the phone's sharpening.
    Blur is capped by the text size so small print (a GSTIN line ~2.2 mm tall, the digits in the rows) stays
    readable."""
    fh, fw = arr.shape[:2]
    cap = max(0.35, min(row_px / 28, text_px / 11, mm_px * 2.2 / 9))
    sigma = min(_u(rng, k["blur"]), cap)
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")
    blurred = img.filter(ImageFilter.GaussianBlur(sigma * WORK))
    info = {"blur_sigma": sigma, "blur_cap": cap, "defocus": None, "motion": None}
    if rng.random() < {"easy": 0.1, "medium": 0.3, "hard": 0.5}[difficulty]:
        sigma2 = min(sigma * rng.uniform(1.4, 2.0), cap)
        far = img.filter(ImageFilter.GaussianBlur(sigma2 * WORK))
        ang = rng.uniform(0, 2 * math.pi)
        xx = (np.arange(fw, dtype=np.float32)[None, :] / fw - 0.5) * math.cos(ang)
        yy = (np.arange(fh, dtype=np.float32)[:, None] / fh - 0.5) * math.sin(ang)
        ramp = ((xx + yy) * 1.4 + 0.5).clip(0, 1)[..., None]
        out = np.asarray(blurred, np.float32) * (1 - ramp) + np.asarray(far, np.float32) * ramp
        info["defocus"] = {"sigma_far": sigma2, "angle": math.degrees(ang)}
    else:
        out = np.asarray(blurred, np.float32)
    if rng.random() < {"easy": 0.0, "medium": 0.08, "hard": 0.25}[difficulty]:
        length = min(rng.uniform(1.0, 2.0), max(0.5, cap * 1.6)) * WORK
        ang = rng.uniform(0, math.pi)
        n = max(2, int(round(length)))
        acc = np.zeros_like(out)
        for i in range(n):
            t = i / (n - 1) - 0.5
            shift = (int(round(t * length * math.sin(ang))), int(round(t * length * math.cos(ang))))
            acc += np.roll(out, shift, (0, 1))
        out = acc / n
        info["motion"] = {"length_px": length / WORK, "angle": math.degrees(ang)}
    sd = _u(rng, k["noise"])
    lum = nrng.normal(0, sd * WORK, (fh, fw, 1)).astype(np.float32)
    chroma = nrng.normal(0, sd * WORK * 0.35, (fh, fw, 3)).astype(np.float32)
    out += (lum + chroma) * np.sqrt(out.clip(1, 255) / 140)
    img = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB")
    img = img.resize((round(fw / WORK), round(fh / WORK)), Image.LANCZOS)
    sharpen = (rng.uniform(0.8, 1.6), rng.randint(30, 90))
    img = img.filter(ImageFilter.UnsharpMask(radius=sharpen[0], percent=sharpen[1], threshold=2))
    info.update(noise_sd=sd, sharpen_radius=sharpen[0], sharpen_percent=sharpen[1])
    return img, info
