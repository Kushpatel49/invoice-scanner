"""Billing-app "Tax Invoice" printed on A4, like R K Mercantile (inv06).

Small traders print these from phone/PC billing apps: a plain letterhead with a drawn
logo, a centred "Tax Invoice" title, Bill To / Ship To / Transportation Details /
Invoice Details blocks, a coloured table header bar, a right-hand summary with the
highlighted Total, Balance / Payment mode / Previous Balance / Current Balance (the
last two are larger trap numbers), "Invoice Amount In Words", bank details, and a
tear-off Acknowledgement that repeats the invoice number, date and amount.
"""
import math
import random
import re
from datetime import date, timedelta

from PIL import Image, ImageDraw

from bench.synth import hand

A4 = 1.4142
RUPEE = "₹"
# Only these bundled fonts draw U+20B9 as a rupee sign (PT Serif draws a ruble, the
# others have no glyph), so the sign falls back to NotoSans in any other font.
RUPEE_FONTS = {"sans", "narrow", "condensed"}
BODY_FONTS = ["sans", "sans", "sans", "sans2", "sans2", "narrow"]

ACCENTS = {"gray": (122, 122, 122), "graphite": (84, 86, 92), "navy": (36, 64, 124), "teal": (0, 110, 118),
           "maroon": (126, 34, 46), "purple": (92, 56, 138), "green": (36, 110, 74), "orange": (196, 104, 34)}
PAPERS = {"white": (255, 255, 255), "cream": (251, 248, 238)}
INKS = [(26, 26, 30), (20, 20, 22), (40, 40, 46)]
BANKS = [("ICICI BANK LIMITED", "ICIC"), ("FEDERAL BANK", "FDRL"), ("SOUTH INDIAN BANK", "SIBL"),
         ("STATE BANK OF INDIA", "SBIN"), ("HDFC BANK", "HDFC"), ("CANARA BANK", "CNRB"),
         ("KOTAK MAHINDRA BANK", "KKBK"), ("UNION BANK OF INDIA", "UBIN"), ("ESAF SMALL FINANCE BANK", "ESMF")]
STATE_ABBR = {"Kerala": "KL", "Tamil Nadu": "TN", "Karnataka": "KR"}
DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d-%b-%y", "%d.%m.%Y", "%d/%m/%y", "%d-%b-%Y"]
TERMS = [["Thanks for doing business with us!"],
         ["Goods once sold will not be taken back.", "Subject to Ernakulam jurisdiction."],
         ["1. Goods once sold will not be taken back or exchanged.",
          "2. Interest @18% p.a. will be charged if not paid within 15 days.",
          "3. Subject to Ernakulam jurisdiction only."],
         ["Keep frozen at -18°C or below.", "Thanks for doing business with us!"]]


# ---------------------------------------------------------------- number formatting

def _group(n, style):
    s = str(n)
    if style == "none" or len(s) <= 3:
        return s
    if style == "western":
        return f"{n:,}"
    head, parts = s[:-3], [s[-3:]]
    while len(head) > 2:          # Indian grouping: 1,35,000
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + parts)


def _money(v, st):
    paise = round(abs(v) * 100)
    rupees, p = divmod(paise, 100)
    s = _group(rupees, st["grouping"])
    if p or not st["auto_decimals"]:
        s += f".{p:02d}"
    return ("-" if v < 0 and paise else "") + s


def _rs(s, on, st):
    return (RUPEE + st["rupee_gap"] + s) if on else s


def _qty(q, three_dp):
    if isinstance(q, int):
        return str(q)
    s = f"{q:.3f}"
    return s if three_dp else s.rstrip("0").rstrip(".")


def _pct(p):
    return f"{p:g}%"


# ---------------------------------------------------------------- drawing helper

class Canvas:
    """ImageDraw wrapper: text by cap-top position, rupee-sign font fallback, ink bboxes."""

    def __init__(self, img, family, ink):
        self.img, self.d, self.family, self.ink = img, ImageDraw.Draw(img), family, ink

    def font(self, size, bold=False, family=None):
        return hand.font(family or self.family, size, bold)

    def _runs(self, s, size, bold, family):
        fam = family or self.family
        if fam in RUPEE_FONTS or RUPEE not in s:
            return [(s, self.font(size, bold, fam))]
        return [(part, hand.font("sans", size, bold) if part == RUPEE else self.font(size, bold, fam))
                for part in re.split(f"({RUPEE})", s) if part]

    def width(self, s, size, bold=False, family=None):
        return sum(f.getlength(t) for t, f in self._runs(s, size, bold, family))

    def cap(self, size, bold=False, family=None):
        return -self.font(size, bold, family).getbbox("H", anchor="ls")[1]

    def text(self, x, top, s, size, bold=False, fill=None, align="l", family=None):
        """One line with its capital letters starting at `top`; x is the left, right or
        middle edge per align. Returns the tight ink bbox."""
        runs = self._runs(s, size, bold, family)
        w = sum(f.getlength(t) for t, f in runs)
        x = x - w if align == "r" else x - w / 2 if align == "m" else x
        base = top + self.cap(size, bold, family)
        box = None
        for t, f in runs:
            self.d.text((x, base), t, font=f, fill=fill or self.ink, anchor="ls")
            if t.strip():
                b = self.d.textbbox((x, base), t, font=f, anchor="ls")
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
            x += f.getlength(t)
        if box is None:
            return (int(x), int(top), int(x) + 1, int(top) + 1)
        return (int(box[0]), int(box[1]), math.ceil(box[2]), math.ceil(box[3]))

    def wrap(self, s, size, maxw, bold=False):
        """Split s into lines no wider than maxw (words longer than a line are cut by character)."""
        lines, cur = [], ""
        for word in s.split():
            while self.width(word, size, bold) > maxw and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and self.width(word[:cut], size, bold) > maxw:
                    cut -= 1
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:cut])
                word = word[cut:]
            trial = f"{cur} {word}" if cur else word
            if cur and self.width(trial, size, bold) > maxw:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines or [""]

    def dashed(self, x0, x1, y, fill, dash=10, gap=7, width=2):
        x = x0
        while x < x1:
            self.d.line([(x, y), (min(x + dash, x1), y)], fill=fill, width=width)
            x += dash + gap


def _union(boxes):
    boxes = [b for b in boxes if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _tint(color, k, paper=(255, 255, 255)):
    """Mix k of `color` into the paper colour (light fills)."""
    return tuple(round(p + (c - p) * k) for c, p in zip(color, paper))


# ---------------------------------------------------------------- random appearance

def _style(spec, rng):
    W = rng.randrange(1560, 1680, 2)
    family = rng.choice(BODY_FONTS)
    # Archivo Narrow looks smaller than the others at the same pixel size
    s = round(W * rng.uniform(0.0146, 0.0162) * (1.1 if family == "narrow" else 1.0))
    accent = rng.choice(["gray", "gray", "gray", "graphite", "navy", "teal", "maroon", "purple", "green", "orange"])
    has_mrp = any(it.get("mrp") is not None for it in spec["items"])
    items_tax = spec["tax_mode"] != "none"
    d = date.fromisoformat(spec["invoice_date"])
    fmt = next((f for f in DATE_FORMATS if d.strftime(f) == spec["date_printed"]), None)
    bank, code = rng.choice(BANKS)
    supplier = spec["supplier"]
    if not supplier["gstin"]:
        title = rng.choice(["Invoice", "Invoice", "Bill of Supply", "Estimate"])
    elif not items_tax:
        title = rng.choice(["Bill of Supply", "Tax Invoice", "Invoice"])
    else:
        title = "Tax Invoice"
    grand = (spec["totals"] or {}).get("grand_total") or 0
    # mostly credit sales (nothing received); sometimes part or fully paid in cash / UPI
    pay = rng.random()
    if pay < 0.12 and grand > 600:
        received, mode = float(rng.randrange(100, int(grand * 0.8), 100)), rng.choice(["Cash", "UPI"])
    elif pay < 0.22:
        received, mode = grand, rng.choice(["Cash", "UPI", "Cheque"])
    else:
        received, mode = 0.0, "Credit"
    prev = 0.0 if rng.random() < 0.08 else round(grand * rng.uniform(0.6, 5.0) + rng.uniform(200, 9000),
                                                 rng.choice([0, 2, 2]))
    # Some apps print whole-rupee bills without ".00" - only when every money value is whole
    money = [v for it in spec["items"] for v in (it["rate"], it["amount"], it["cgst"] + it["sgst"], it.get("mrp") or 0)]
    money += [v for v in (spec["totals"] or {}).values() if v is not None] + [prev, received]
    no_decimals = all(abs(v - round(v)) < 0.001 for v in money) and rng.random() < 0.5
    return {
        "seed": rng.random(), "width": W, "size": s, "table_size": s - rng.choice([0, 0, 1, 2]),
        "name_share": rng.uniform(0.34, 0.46),
        "margin": round(W * rng.uniform(0.042, 0.062)),
        "family": family,
        "name_family": rng.choice([None, None, None, "serif_bold", "condensed"]),
        "name_scale": rng.uniform(1.4, 1.85),
        "accent": ACCENTS[accent], "title_gray": rng.random() < 0.5,
        "ink": rng.choice(INKS), "paper": "cream" if rng.random() < 0.15 else "white",
        "bar": rng.choice(["dark", "dark", "dark", "light"]),
        "zebra": rng.random() < 0.2, "row_lines": rng.random() < 0.75, "boxed": rng.random() < 0.25,
        "name_bold": rng.random() < 0.65, "valign_mid": rng.random() < 0.7,
        "logo": rng.choice(["none", "initials", "initials", "circle", "square", "leaf"]),
        "logo_left": rng.random() < 0.3, "header_center": rng.random() < 0.25,
        "header_rule": rng.random() < 0.8, "address_joined": rng.random() < 0.5,
        "udyam": f"UDYAM-{STATE_ABBR.get(supplier['state'], 'KL')}-{rng.randint(1, 14):02d}-{rng.randint(1000, 99999):07d}"
        if rng.random() < 0.4 else None,
        "fssai_valid": _valid_after(date(rng.randint(2026, 2030), rng.randint(1, 12), rng.randint(1, 28)), d),
        "phone_label": rng.choice(["Phone no. : ", "Phone: ", "Ph: ", "Mobile : "]),
        "gstin_label": rng.choice(["GSTIN : ", "GSTIN: ", "GSTIN No. : "]),
        "title": title.upper() if rng.random() < 0.2 else title, "original_tag": rng.random() < 0.3,
        "ship_to": rng.random() < 0.6, "transport": rng.random() < 0.5,
        "vehicle": f"KL-{rng.randint(1, 65):02d}-{rng.choice('ABCDEFGHJK')}{rng.choice('ABCDEFGHJK')}-{rng.randint(1000, 9999)}"
        if rng.random() < 0.4 else "",
        "buyer_contact": "9" + "".join(rng.choice("0123456789") for _ in range(9)) if rng.random() < 0.3 else None,
        "buyer_gstin": rng.random() < 0.85, "buyer_state": rng.random() < 0.8,
        "inv_label": rng.choice(["Invoice No. : ", "Invoice No.: ", "Invoice No : ", "Bill No. : "]),
        "date_label": rng.choice(["Date : ", "Date: ", "Invoice Date : "]),
        "details_right": rng.random() < 0.6,
        "time": f"{rng.randint(1, 12):02d}:{rng.randint(0, 59):02d} {rng.choice(['AM', 'PM'])}" if rng.random() < 0.3 else None,
        "due": (d + timedelta(days=rng.choice([7, 10, 15, 30]))).strftime(fmt) if fmt and rng.random() < 0.15 else None,
        "grouping": rng.choice(["indian", "indian", "indian", "indian", "none", "western"]),
        "auto_decimals": no_decimals, "rupee_gap": rng.choice([" ", " ", ""]),
        "rupee_table": rng.random() < 0.7, "rupee_totals": rng.random() < 0.85,
        "qty3": rng.random() < 0.25, "unit_col": rng.random() < 0.75, "hsn_col": rng.random() < 0.9,
        "mrp_col": has_mrp and rng.random() < 0.6,
        "gst_col": "amount" if spec["tax_mode"] == "inclusive" else ("pct" if items_tax and rng.random() < 0.45 else None),
        "headers": {"no": rng.choice(["#", "#", "Sl.", "S.No"]),
                    "name": rng.choice(["Item name", "Item name", "Item Name", "Particulars", "Description"]),
                    "hsn": rng.choice(["HSN/ SAC", "HSN/SAC", "HSN"]), "mrp": "MRP",
                    "qty": rng.choice(["Quantity", "Quantity", "Qty"]), "unit": rng.choice(["Unit", "Unit", "UOM"]),
                    "rate": rng.choice(["Price/ unit", "Price/ unit", "Price/Unit", "Rate"]),
                    "gst": rng.choice(["GST", "GST", "Tax"]), "gstp": rng.choice(["GST %", "Tax %", "GST"]),
                    "amount": "Amount"},
        "total_row": rng.random() < 0.85, "per_rate": rng.random() < 0.75, "sgst_first": rng.random() < 0.6,
        "round_sign": rng.random() < 0.5,
        "received": received, "show_received": received > 0 or rng.random() < 0.4, "prev": prev,
        "payment_mode": mode,
        "words_label": rng.choice(["Invoice Amount In Words", "Invoice Amount In Words", "Amount In Words"]),
        # the cold-chain line only on frozen-food bills
        "terms": rng.choice(TERMS if spec.get("supplier_kind") == "frozen" else TERMS[:-1])
        if rng.random() < 0.65 else None,
        "bank": (bank, "".join(rng.choice("0123456789") for _ in range(rng.choice([12, 14, 15]))),
                 code + "0" + "".join(rng.choice("0123456789") for _ in range(6))) if rng.random() < 0.8 else None,
        "bank_beside": rng.random() < 0.5, "qr": rng.random() < 0.25,
        "for_label": rng.choice(["For, ", "For : ", "For "]), "sign_scribble": rng.random() < 0.2,
        "eoe": rng.random() < 0.3, "computer_note": rng.random() < 0.35,
        "ack_bottom": rng.random() < 0.65, "notes_header": rng.random() < 0.75,
        # inv06's Invoice Details column is the narrowest, so its number and place of supply wrap
        "inv_weight": rng.choice([1.15, 1.15, 0.78]), "inv_wrap": rng.random() < 0.6,
    }


def _valid_after(valid, d):
    """An FSSAI licence printed on a bill is still valid on the bill date."""
    if valid <= d:
        valid = valid.replace(year=d.year + 1)
    return valid.strftime("%d-%m-%Y")


# ---------------------------------------------------------------- page sections

def _initials(name):
    words = [w for w in re.split(r"[\s.&,'-]+", name) if w[:1].isalpha()]
    return "".join(w[0] for w in words[:2]).upper() or "M"


def _logo(c, st, name, box):
    x0, y0, x1, y1 = box
    color = st["accent"] if st["accent"] != ACCENTS["gray"] else (110, 110, 110)
    ini = _initials(name)
    w, h = x1 - x0, y1 - y0
    kind = st["logo"]
    if kind == "circle":
        c.d.ellipse(box, outline=color, width=max(3, w // 30))
        size = int(h * 0.42)
        c.text((x0 + x1) / 2, (y0 + y1) / 2 - c.cap(size, True, "condensed") / 2, ini, size, True, color, "m", "condensed")
    elif kind == "square":
        c.d.rounded_rectangle(box, radius=w // 6, fill=color)
        size = int(h * 0.45)
        c.text((x0 + x1) / 2, (y0 + y1) / 2 - c.cap(size, True, "condensed") / 2, ini, size, True, (255, 255, 255), "m",
               "condensed")
    elif kind == "leaf":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        pts = []
        for i in range(41):     # a pointed leaf: two arcs meeting at the tips
            t = math.pi * i / 40
            pts.append((cx + math.cos(t) * w * 0.45, cy - math.sin(t) * h * 0.22))
        for i in range(41):
            t = math.pi * i / 40
            pts.append((cx - math.cos(t) * w * 0.45, cy + math.sin(t) * h * 0.22))
        rot = math.radians(-30)
        pts = [(cx + (px - cx) * math.cos(rot) - (py - cy) * math.sin(rot),
                cy + (px - cx) * math.sin(rot) + (py - cy) * math.cos(rot)) for px, py in pts]
        c.d.polygon(pts, fill=_tint(color, 0.85))
        c.d.line([pts[0], pts[40]], fill=(255, 255, 255), width=3)
    else:   # stylised initials, like the "RK" mark on R K Mercantile
        size = int(h * 0.62)
        c.text((x0 + x1) / 2, (y0 + y1) / 2 - c.cap(size, True, "condensed") / 2, ini, size, True,
               _tint(color, 0.7), "m", "condensed")
        c.d.line([(x0 + w * 0.12, y1 - h * 0.12), (x0 + w * 0.38, y0 + h * 0.62)], fill=_tint(color, 0.7), width=4)


def _letterhead(c, spec, st, x0, x1, y):
    """Supplier block. Returns (header_bbox, right edge of its text, logo box or None, bottom y)."""
    sup = spec["supplier"]
    s = st["size"]
    lh = round(s * 1.42)
    ns = round(s * st["name_scale"])
    logo_size = round(s * _logo_scale(st))
    logo = None
    if st["logo"] != "none":
        lx = x0 if st["logo_left"] else x1 - logo_size
        logo = (lx, y, lx + logo_size, y + logo_size)
        _logo(c, st, sup["name"], logo)
    tx0 = x0 + logo_size + round(s * 1.2) if logo and st["logo_left"] else x0
    tx1 = x1 - logo_size - round(s * 1.2) if logo and not st["logo_left"] else x1
    center = st["header_center"]
    tx = (tx0 + tx1) / 2 if center else tx0
    align = "m" if center else "l"
    maxw = (tx1 - tx0) if center else (tx1 - tx0) * 0.72

    lines = []
    if st["address_joined"]:
        lines += c.wrap(", ".join(sup["address_lines"]), s - 1, maxw)
    else:
        lines += sup["address_lines"]
    if st["udyam"]:
        lines.append(f"MSME/UDYAM Reg No.{st['udyam']}")
    contact = st["phone_label"] + sup["phone"]
    if center and sup["email"]:
        lines.append(f"{contact}   Email : {sup['email']}")
    else:
        lines.append(contact)
        if sup["email"]:
            lines.append(f"Email : {sup['email']}")
    state = f"State: {sup['state_code']}-{sup['state']}"
    if sup["gstin"]:
        lines.append(f"{st['gstin_label']}{sup['gstin']}" + (f"   {state}" if center else ""))
    if not center or not sup["gstin"]:
        lines.append(state)
    if sup["fssai"]:
        lines.append(f"fssai license number: {sup['fssai']}")
        lines.append(f"Valid up to: {st['fssai_valid']}")

    boxes = [c.text(tx, y + round(s * 0.2), sup["name"], ns, True, None, align, st["name_family"])]
    yy = boxes[0][3] + round(s * 0.6)
    for ln in lines:
        boxes.append(c.text(tx, yy, ln, s - 1, False, None, align))
        yy += lh - 2
    text_box = _union(boxes)
    bottom = max(text_box[3], logo[3] if logo else 0)
    return _union([text_box, logo]), text_box[2], logo, bottom


def _logo_scale(st):
    """Logo height in body-text sizes."""
    return 5.2 if st["logo"] in ("circle", "square") else 4.6


def _party_blocks(c, spec, st, x0, x1, y, layout):
    """Bill To / Ship To / Transportation Details / Invoice Details. Returns bottom y."""
    s = st["size"]
    lh = round(s * 1.42)
    buyer = spec["buyer"]
    cols = ["bill"] + (["ship"] if st["ship_to"] else []) + (["transport"] if st["transport"] else []) + ["inv"]
    weights = {"bill": 1.15, "ship": 1.0, "transport": 1.05, "inv": st["inv_weight"]}
    total_w = sum(weights[k] for k in cols)
    gap = round(s * 1.2)
    avail = (x1 - x0) - gap * (len(cols) - 1)
    bottoms = []
    cx = x0
    for k in cols:
        w = avail * weights[k] / total_w
        right_al = k == "inv" and st["details_right"]
        ax = cx + w if right_al else cx
        al = "r" if right_al else "l"
        yy = y

        def put(t, bold=False, size=s, dy=lh, _ax=ax, _al=al):
            nonlocal yy
            b = c.text(_ax, yy, t, size, bold, None, _al)
            yy += dy
            return b

        if k == "bill":
            put("Bill To", True, dy=round(lh * 1.3))
            for ln in c.wrap(buyer["display"], s, w, True):
                put(ln, True)
            for ln in buyer["address_lines"]:
                for part in c.wrap(ln, s - 1, w):
                    put(part, size=s - 1)
            if st["buyer_contact"]:
                put(f"Contact No. : {st['buyer_contact']}", size=s - 1)
            if st["buyer_gstin"]:
                put(f"GSTIN : {buyer['gstin']}", size=s - 1)
            if st["buyer_state"]:
                put("State: 32-Kerala", size=s - 1)
        elif k == "ship":
            put("Ship To", True, dy=round(lh * 1.3))
            for ln in c.wrap(buyer["name"], s - 1, w):
                put(ln, size=s - 1)
            for ln in c.wrap(buyer["address_lines"][0], s - 1, w) + ["KAKKANAD"]:
                put(ln, size=s - 1)
        elif k == "transport":
            for ln in c.wrap("Transportation Details", s, w, True):
                put(ln, True)
            yy += round(lh * 0.3)
            # wrapped to the column so a long vehicle number never runs into Invoice Details
            for t in (f"Vehicle Number: {st['vehicle']}", "Delivery location: " + ("KAKKANAD" if st["vehicle"] else ""),
                      "Field 5:", "Field 6:"):
                for part in c.wrap(t, s - 1, w):
                    put(part, size=s - 1)
        else:
            put("Invoice Details", True, dy=round(lh * 1.3))
            for label, value, key in ((st["inv_label"], spec["invoice_number_printed"], "invoice_number_bbox"),
                                      (st["date_label"], spec["date_printed"], "date_bbox")):
                lw, vw = c.width(label, s - 1), c.width(value, s - 1)
                split = None
                if lw + vw > w and key == "invoice_number_bbox" and st["inv_wrap"] \
                        and not spec["corrections"]["invoice_number"]:
                    split = _split_number(c, label, value, s - 1, w)
                if lw + vw <= w:
                    if right_al:
                        vb = c.text(ax, yy, value, s - 1, False, None, "r")
                        c.text(vb[0] - 1, yy, label, s - 1, False, None, "r")
                    else:
                        c.text(ax, yy, label, s - 1)
                        vb = c.text(ax + c.width(label, s - 1), yy, value, s - 1)
                    yy += lh
                elif split:   # the app breaks the number itself, like inv06: "Invoice No. : 26-" / "27/1064"
                    head, tail = split
                    if right_al:
                        hb = c.text(ax, yy, head, s - 1, False, None, "r")
                        c.text(hb[0] - 1, yy, label, s - 1, False, None, "r")
                    else:
                        c.text(ax, yy, label, s - 1)
                        hb = c.text(ax + lw, yy, head, s - 1)
                    yy += lh
                    vb = _union([hb, put(tail, size=s - 1)])
                else:   # narrow column: label on one line, the value whole on the next
                    put(label.rstrip(), size=s - 1)
                    vb = put(value, size=s - 1)
                layout[key] = vb
            extra = ([f"Time : {st['time']}"] if st["time"] else []) + \
                ([f"Due Date : {st['due']}"] if st["due"] else []) + ["Place of supply: 32-Kerala"]
            for t in extra:
                for part in c.wrap(t, s - 1, w):
                    put(part, size=s - 1)
        bottoms.append(yy)
        cx += w + gap
    return max(bottoms)


def _split_number(c, label, value, size, w):
    """Break an invoice number after a '-' or '/' so the head fits beside the label and
    the tail on the next line. Returns (head, tail) or None."""
    best = None
    for i in range(1, len(value)):
        if value[i - 1] in "-/" and c.width(label + value[:i], size) <= w and c.width(value[i:], size) <= w:
            best = (value[:i], value[i:])
    return best


def _columns(spec, st):
    cols = [("no", "l"), ("name", "l")]
    if st["hsn_col"]:
        cols.append(("hsn", "l"))
    if st["mrp_col"]:
        cols.append(("mrp", "r"))
    cols.append(("qty", "r"))
    if st["unit_col"]:
        cols.append(("unit", "l"))
    cols.append(("rate", "r"))
    if st["gst_col"] == "amount":
        cols.append(("gst", "r"))
    elif st["gst_col"] == "pct":
        cols.append(("gstp", "r"))
    cols.append(("amount", "r"))
    return cols


def _cells(spec, st):
    rows = []
    for i, it in enumerate(spec["items"]):
        tax = it["cgst"] + it["sgst"]
        rows.append({
            "no": str(i + 1), "name": it["description"], "hsn": it["hsn"],
            "mrp": _money(it["mrp"], st) if it.get("mrp") is not None else "",
            "qty": _qty(it["quantity"], st["qty3"]), "unit": it["unit"],
            "rate": _rs(_money(it["rate"], st), st["rupee_table"], st),
            "gst": f"{_rs(_money(tax, st), st['rupee_table'], st)} ({_pct(it['tax_percent'])})",
            "gstp": _pct(it["tax_percent"]),
            "amount": _rs(_money(it["amount"], st), st["rupee_table"], st),
        })
    return rows


def _total_cells(spec, st):
    items = spec["items"]
    if all(isinstance(it["quantity"], int) for it in items):
        q = str(sum(it["quantity"] for it in items))
    else:
        q = _qty(round(sum(it["quantity"] for it in items), 3), st["qty3"])
    tax = sum(round(it["cgst"] * 100) + round(it["sgst"] * 100) for it in items) / 100
    amt = sum(round(it["amount"] * 100) for it in items) / 100
    return {"no": "", "name": "Total", "hsn": "", "mrp": "", "unit": "", "gstp": "", "rate": "",
            "qty": q,
            "gst": _rs(_money(tax, st), st["rupee_table"], st), "amount": _rs(_money(amt, st), st["rupee_table"], st)}


def _table(c, spec, st, x0, x1, y, layout):
    """The item table with its header bar and optional Total row. Returns bottom y."""
    cols = _columns(spec, st)
    cells = _cells(spec, st)
    tot = _total_cells(spec, st) if st["total_row"] and not spec["continued"] else None
    n = len(cells)
    for s in range(st["table_size"], 12, -1):
        pad = round(s * 0.5)
        widths = {}
        for key, _ in cols:
            if key == "name":
                continue
            texts = [r[key] + ("" if st["unit_col"] or key != "qty" else " " + r["unit"]) for r in cells]
            w = max([c.width(st["headers"][key], s, True)] + [c.width(t, s) for t in texts] +
                    ([c.width(tot[key], s, True)] if tot else []))
            widths[key] = w + 2 * pad
        widths["name"] = (x1 - x0) - sum(widths.values())
        if widths["name"] >= (x1 - x0) * 0.27:
            break
    # few columns: the app spreads the spare width over the other columns
    spare = widths["name"] - (x1 - x0) * st["name_share"]
    if spare > 0:
        others = [k for k, _ in cols if k not in ("no", "name")]
        for k in others:
            widths[k] += spare / len(others)
        widths["name"] -= spare
    lh = round(s * 1.36)
    vpad = round(s * (0.6 if n <= 10 else 0.32 if n <= 20 else 0.22))
    min_h = round(s * (1.9 if n <= 10 else 1.6 if n <= 20 else 1.4))
    xs, cx = {}, x0
    for key, _ in cols:
        xs[key] = (cx, cx + widths[key])
        cx += widths[key]

    accent = st["accent"]
    paper = PAPERS[st["paper"]]
    top = y
    hb = round(s * 1.95)
    if st["bar"] == "dark":
        c.d.rectangle((x0, y, x1, y + hb), fill=accent)
        head_fill = (255, 255, 255)
    else:
        c.d.rectangle((x0, y, x1, y + hb), fill=_tint(accent, 0.22, paper))
        head_fill = c.ink
    cap = c.cap(s, True)
    for key, al in cols:
        a, b = xs[key]
        c.text(a + pad if al == "l" else b - pad, y + (hb - cap) / 2, st["headers"][key], s, True, head_fill, al)
    y += hb

    rows = []
    name_w = widths["name"] - 2 * pad
    for i, r in enumerate(cells):
        name_lines = c.wrap(r["name"], s, name_w, st["name_bold"])
        th = len(name_lines) * lh - (lh - cap)
        h = max(th + 2 * vpad, min_h)
        if st["zebra"] and i % 2 == 1:
            c.d.rectangle((x0, y, x1, y + h), fill=_tint(accent, 0.08, paper))
        # the name block sits in the middle of the row, so a one-line name shares the
        # numbers' baseline; with a wrapped name the numbers go mid-row or on the first line
        ty = y + (h - th) / 2
        desc = [c.text(xs["name"][0] + pad, ty + k * lh, ln, s, st["name_bold"]) for k, ln in enumerate(name_lines)]
        cy = y + (h - cap) / 2 if st["valign_mid"] else ty
        boxes = {}
        for key, al in cols:
            if key == "name":
                continue
            a, b = xs[key]
            if key == "qty" and not st["unit_col"]:
                ub = c.text(b - pad, cy, r["unit"], s, False, None, "r")
                boxes["qty"] = c.text(ub[0] - c.width(" ", s), cy, r["qty"], s, False, None, "r")
                continue
            if r[key]:
                boxes[key] = c.text(a + pad if al == "l" else b - pad, cy, r[key], s, False, None, al)
        if st["row_lines"] and (i < n - 1 or not st["boxed"]):
            c.d.line([(x0, y + h), (x1, y + h)], fill=_tint(c.ink, 0.25, paper), width=1)
        rows.append({"y0": int(y), "y1": int(y + h), "desc_bbox": _union(desc),
                     "qty_bbox": boxes["qty"], "amount_bbox": boxes["amount"]})
        y += h
    layout["rows"] = rows

    if spec["continued"]:
        y += round(s * 0.4)
        c.text(x1 - pad, y, "continued...", s, False, None, "r")
        y += round(s * 1.6)
    elif tot:
        h = round(s * 2.0)
        c.d.line([(x0, y), (x1, y)], fill=c.ink, width=2)
        for key, al in cols:
            a, b = xs[key]
            if key == "name":
                c.text(a + pad, y + (h - cap) / 2, "Total", s, True)
            elif tot[key]:
                c.text(b - pad, y + (h - cap) / 2, tot[key], s, True, None, "r")
        y += h
        c.d.line([(x0, y), (x1, y)], fill=c.ink, width=2)
    else:
        c.d.line([(x0, y), (x1, y)], fill=c.ink, width=2)
    if st["boxed"]:
        c.d.rectangle((x0, top, x1, y), outline=c.ink, width=2)
        for key, _ in cols[1:]:
            c.d.line([(xs[key][0], top + hb), (xs[key][0], y)], fill=_tint(c.ink, 0.5, paper), width=1)
    layout["table_bbox"] = (int(x0), int(top), int(x1), int(y))
    return y


def _summary_lines(spec, st):
    """(label, value, kind) rows of the right-hand summary block."""
    t = spec["totals"]
    rt = st["rupee_totals"]
    m = lambda v: _rs(_money(v, st), rt, st)   # noqa: E731
    out = [("Sub Total", m(t["subtotal"]), "")]
    if spec["tax_mode"] != "none":
        taxed = [it for it in spec["items"] if it["tax_percent"]]
        rates = sorted({it["tax_percent"] for it in taxed})
        names = ["SGST", "CGST"] if st["sgst_first"] else ["CGST", "SGST"]
        if st["per_rate"] and rates:
            for p in rates:
                for nm in names:
                    key = nm.lower()
                    v = sum(round(it[key] * 100) for it in taxed if it["tax_percent"] == p) / 100
                    out.append((f"{nm}@{_pct(p / 2)}", m(v), ""))
        else:
            for nm in names:
                out.append((nm, m(t[nm.lower()]), ""))
        if t.get("igst"):
            out.append(("IGST", m(t["igst"]), ""))
    if t["round_off"]:
        ro = _money(t["round_off"], st)
        out.append(("Round off", ro if t["round_off"] < 0 or not st["round_sign"] else "+" + ro, ""))
    grand = t["grand_total"]
    out.append(("Total", m(grand), "total"))
    balance = round(grand - st["received"], 2)
    if st["show_received"]:
        out.append(("Received", m(st["received"]), ""))
    out.append(("Balance", m(balance), ""))
    out.append(("Payment mode", st["payment_mode"], ""))
    out.append(("Previous Balance", m(st["prev"]), ""))
    out.append(("Current Balance", m(round(st["prev"] + balance, 2)), ""))
    return out


def _summary(c, spec, st, x0, x1, y, layout, rng):
    """Words + terms (+ bank) on the left, totals on the right, then bank / signature.
    Returns bottom y."""
    s = st["size"]
    lh = round(s * 1.42)
    cw = x1 - x0
    xl1 = x0 + cw * 0.48
    xr0 = x0 + cw * 0.55
    pad = round(s * 0.5)
    sup = spec["supplier"]

    # right: totals
    yr = y
    th = round(s * 1.62)
    cap = c.cap(s)
    for label, value, kind in _summary_lines(spec, st):
        if kind == "total":
            c.d.rectangle((xr0, yr, x1, yr + th), fill=st["accent"] if st["bar"] == "dark"
                          else _tint(st["accent"], 0.22, PAPERS[st["paper"]]))
            fill = (255, 255, 255) if st["bar"] == "dark" else c.ink
            c.text(xr0 + pad, yr + (th - cap) / 2, label, s, True, fill)
            c.text(x1 - pad, yr + (th - cap) / 2, value, s, True, fill, "r")
            layout["total_bbox"] = (int(xr0), int(yr), int(x1), int(yr + th))
        else:
            c.text(xr0 + pad, yr + (th - cap) / 2, label, s)
            c.text(x1 - pad, yr + (th - cap) / 2, value, s, False, None, "r")
        yr += th

    # left: amount in words, terms, maybe bank
    yl = y + round(s * 0.3)
    c.text(x0, yl, st["words_label"], s, True)
    yl += round(lh * 1.25)
    for ln in c.wrap(spec["amount_in_words"], s, xl1 - x0):
        c.text(x0, yl, ln, s)
        yl += lh
    if st["terms"]:
        yl += round(lh * 0.5)
        c.text(x0, yl, "Terms And Conditions", s, True)
        yl += round(lh * 1.2)
        for t in st["terms"]:
            for ln in c.wrap(t, s - 2, xl1 - x0):
                c.text(x0, yl, ln, s - 2)
                yl += lh - 3
    if st["bank"] and st["bank_beside"]:
        yl = _bank(c, spec, st, x0, xl1, yl + round(lh * 0.6), rng)

    y = max(yl, yr) + round(lh * 0.8)
    yb = y
    if st["bank"] and not st["bank_beside"]:
        yb = _bank(c, spec, st, x0, xl1, y, rng)
    # signature
    sx = (xr0 + x1) / 2
    c.text(sx, y, f"{st['for_label']}{sup['name']}", s, False, None, "m")
    gap = round(s * 3.6)
    if st["sign_scribble"]:
        hand.signature(c.img, (int(sx - s * 3), int(y + gap * 0.62)), int(s * 6), rng, ink=c.ink)
    c.text(sx, y + gap + lh, "Authorized Signatory", s, True, None, "m")
    y = max(yb, y + gap + 2 * lh)
    if st["eoe"] or st["computer_note"]:
        if st["eoe"]:
            c.text(x0, y, "E.&O.E", s - 3)
        if st["computer_note"]:
            c.text((x0 + x1) / 2, y, "This is a computer generated invoice", s - 4, False, _tint(c.ink, 0.65), "m")
        y += lh
    return y


def _bank(c, spec, st, x0, x1, y, rng):
    s = st["size"]
    lh = round(s * 1.42)
    bank, acno, ifsc = st["bank"]
    tx = x0
    if st["qr"]:
        q = round(s * 5.2)
        _qr(c, (x0, y + round(lh * 1.2), x0 + q, y + round(lh * 1.2) + q), rng, PAPERS[st["paper"]])
        c.text(x0 + q / 2, y + round(lh * 1.2) + q + round(s * 0.4), "Scan to pay", s - 4, False, None, "m")
        tx = x0 + q + round(s * 1.2)
    c.text(x0, y, "Pay To:", s, True)
    yy = y + round(lh * 1.25)
    for ln in (f"Bank Name : {bank}", f"Bank Account No. : {acno}", f"Bank IFSC code : {ifsc}",
               f"Account holder's name : {spec['supplier']['name']}"):
        for part in c.wrap(ln, s - 1, x1 - tx):
            c.text(tx, yy, part, s - 1)
            yy += lh
    if st["qr"]:
        yy = max(yy, y + round(lh * 1.2) + round(s * 5.2) + round(s * 1.6))
    return yy


def _qr(c, box, rng, paper):
    """A QR-looking block: three finder squares and random modules."""
    x0, y0, x1, _ = box
    n = 25
    m = (x1 - x0) / n
    for r in range(n):
        for k in range(n):
            if rng.random() < 0.5:
                c.d.rectangle((x0 + k * m, y0 + r * m, x0 + (k + 1) * m - 1, y0 + (r + 1) * m - 1), fill=c.ink)
    for fx, fy in ((0, 0), (n - 7, 0), (0, n - 7)):
        ax, ay = x0 + fx * m, y0 + fy * m
        c.d.rectangle((ax - m, ay - m, ax + 8 * m, ay + 8 * m), fill=paper)
        c.d.rectangle((ax, ay, ax + 7 * m - 1, ay + 7 * m - 1), fill=c.ink)
        c.d.rectangle((ax + m, ay + m, ax + 6 * m - 1, ay + 6 * m - 1), fill=paper)
        c.d.rectangle((ax + 2 * m, ay + 2 * m, ax + 5 * m - 1, ay + 5 * m - 1), fill=c.ink)


def _ack(c, spec, st, x0, x1, y):
    """Tear-off Acknowledgement repeating invoice no., date and amount. Returns bottom y."""
    s = st["size"]
    lh = round(s * 1.42)
    cw = x1 - x0
    gray = _tint(c.ink, 0.62, PAPERS[st["paper"]])
    c.dashed(x0 - round(s * 0.6), x1 + round(s * 0.6), y, _tint(c.ink, 0.7, PAPERS[st["paper"]]))
    y += round(lh * 0.9)
    c.text((x0 + x1) / 2, y, "Acknowledgement", s, True, None, "m")
    y += round(lh * 1.3)
    c.text((x0 + x1) / 2, y, spec["supplier"]["name"], round(s * 1.2), True, gray, "m")
    y += round(lh * 2.0)
    buyer = spec["buyer"]
    ya = y
    c.text(x0, ya, "Invoice To:", s, False, gray)
    ya += round(lh * 1.3)
    for ln in c.wrap(buyer["display"], s, cw * 0.36, True):
        c.text(x0, ya, ln, s, True)
        ya += lh
    for ln in buyer["address_lines"]:
        for part in c.wrap(ln, s - 1, cw * 0.36):
            c.text(x0, ya, part, s - 1)
            ya += lh
    xm = x0 + cw * 0.4
    yb = y
    c.text(xm, yb, "Invoice Details:", s, False, gray)
    yb += round(lh * 1.3)
    rows = [f"Invoice No. : {spec['invoice_number_printed']}", f"Invoice date : {spec['date_printed']}"]
    if spec["totals"]["grand_total"] is not None:
        rows.append("Invoice Amount : " + _rs(_money(spec["totals"]["grand_total"], st), True, st))
    for ln in rows:
        c.text(xm, yb, ln, s)
        yb += lh
    xs0 = x0 + cw * 0.71
    c.dashed(xs0, x1, y + round(lh * 2.4), gray, dash=6, gap=5, width=1)
    c.text((xs0 + x1) / 2, y + round(lh * 3.0), "Receiver's Seal & Sign", s, False, None, "m")
    return max(ya, yb, y + round(lh * 4))


# ---------------------------------------------------------------- page

def _draw(spec, st, W):
    """Lay the page out at width W. Returns (page, layout, height the content needs)."""
    rng = random.Random(st["seed"])
    s = st["size"]
    m = st["margin"]
    H = round(W * A4)
    paper = PAPERS[st["paper"]]
    img = Image.new("RGB", (W, H + 160 * len(spec["items"]) + 3000), paper)
    c = Canvas(img, st["family"], st["ink"])
    layout = {"paper": st["paper"], "total_bbox": None}
    x0, x1 = m, W - m
    lh = round(s * 1.42)

    y = round(m * 0.85)
    head_box, text_right, logo, y = _letterhead(c, spec, st, x0, x1, y)
    layout["header_bbox"] = head_box
    y += round(s * 0.7)
    if st["header_rule"]:
        c.d.line([(x0, y), (x1, y)], fill=_tint(c.ink, 0.6, paper), width=2)
    y += round(s * 1.1)

    tsize = round(s * 1.35)
    title_fill = (120, 120, 120) if st["title_gray"] else st["accent"]
    c.text(W / 2, y, st["title"], tsize, True, title_fill, "m")
    if st["original_tag"]:
        c.text(x1, y + round(tsize * 0.3), "ORIGINAL FOR RECIPIENT", s - 6, False, _tint(c.ink, 0.6, paper), "r")
    y += round(tsize * 2.0)

    y = _party_blocks(c, spec, st, x0, x1, y, layout)
    y += round(s * 0.4)
    y = _table(c, spec, st, x0, x1, y, layout)
    y += round(lh * 1.1)

    ack_top = None
    if not spec["continued"]:
        y = _summary(c, spec, st, x0, x1, y, layout, rng)
        y += round(lh * 0.8)
        # measure the acknowledgement on scratch paper, then place it
        scratch = Canvas(Image.new("RGB", (W, 40 * s), paper), st["family"], st["ink"])
        ack_h = _ack(scratch, spec, st, x0, x1, 0)
        ack_top = max(y, H - m - ack_h) if st["ack_bottom"] else y
        flow_end = y
        y = _ack(c, spec, st, x0, x1, ack_top)
    else:
        flow_end = y
    needed = y + m

    # blank space for the receiver's scribbles ("Bill-641"): beside the letterhead like on
    # inv06, the gap above or below the acknowledgement, else the top margin
    candidates = []
    gx0 = text_right + round(s * 1.5)
    gx1 = (logo[0] - round(s * 1.2)) if logo and not st["logo_left"] else x1
    if gx1 - gx0 >= 260 and head_box[3] - head_box[1] >= 110:
        candidates.append((gx0, head_box[1], gx1, head_box[3]))
    if ack_top is not None and ack_top - flow_end >= 160:
        candidates.append((x0, flow_end, x1, ack_top - round(s * 0.8)))
    if H - m - (y + round(s * 0.8)) >= 140:
        candidates.append((x0, y + round(s * 0.8), x1, H - m))
    if not candidates:
        layout["notes_area"] = (x0, 8, x1, max(20, round(m * 0.85) - 8))
    elif st["notes_header"] or len(candidates) == 1:
        layout["notes_area"] = tuple(int(v) for v in candidates[0])
    else:
        layout["notes_area"] = tuple(int(v) for v in candidates[-1])
    return img, layout, needed


def _scale_layout(layout, k):
    def sc(v):
        if isinstance(v, (tuple, list)):
            return tuple(int(round(t * k)) for t in v)
        return v
    out = {}
    for key, v in layout.items():
        if key == "rows":
            out[key] = [{rk: (int(round(rv * k)) if isinstance(rv, (int, float)) else sc(rv)) for rk, rv in r.items()}
                        for r in v]
        else:
            out[key] = sc(v)
    return out


def render(spec, rng):
    st = _style(spec, rng)
    W = st["width"]
    H = round(W * A4)
    img, layout, needed = _draw(spec, st, W)
    if needed <= H:
        return img.crop((0, 0, W, H)), layout
    # Too much for one sheet at this text size (long bills): lay out on a wider sheet with
    # the same text size so it reads as a denser print, then scale back to the page size.
    W2 = math.ceil(needed / A4)
    img, layout, needed2 = _draw(spec, st, W2)
    H2 = max(round(W2 * A4), needed2)
    img = img.crop((0, 0, W2, H2)).resize((W, round(H2 * W / W2)), Image.LANCZOS)
    return img, _scale_layout(layout, W / W2)
