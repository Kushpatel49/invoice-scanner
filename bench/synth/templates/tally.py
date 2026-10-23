"""Tally-style A4 invoice, as printed from TallyPrime / Tally.ERP 9 on a laser printer by the
wholesale fruit and vegetable suppliers (eval/samples inv04 NKA Fruits, inv12 Aeden Fruits).

Everything sits in one outer box:
  - left: seller letterhead (sometimes a drawn logo), then "Consignee (Ship to)" / "Buyer (Bill to)"
  - right: the Invoice No. / Dated / Delivery Note / Mode/Terms of Payment ... grid and a tall
    "Terms of Delivery" cell
  - the item table (Sl | Description of Goods | HSN/SAC | Quantity | Rate | per | Disc. % | Amount)
    stretched down to fill the page, tax / round-off ledgers under the items, Total row at the bottom
  - amount in words, HSN tax summary, outstanding and bank details, declaration and
    "for <seller> ... Authorised Signatory"; below the box "This is a Computer Generated Invoice".
Page 1 of a continued bill prints no totals: the table ends and "continued ..." follows it.

All random choices are made up front in _style(), so the drawing code can run twice (a dry run
to measure, then the real one) and still be deterministic.
"""
import math
from datetime import date, timedelta

from PIL import Image, ImageDraw

from bench.synth import hand
from bench.synth.spec import number_to_words

PAPERS = {"white": (253, 253, 251), "cream": (250, 246, 233)}
INKS = [(20, 20, 24), (30, 30, 34), (48, 48, 52), (26, 30, 54)]
ACCENTS = [(22, 45, 125), (130, 24, 34), (25, 95, 50), (90, 40, 120)]
# Only these bundled fonts draw U+20B9 as a rupee sign (PT Serif draws a ruble sign)
RUPEE_FACES = {"sans", "narrow", "condensed"}
KG_UNITS = {"KG", "KGS", "Kilogram"}
DATE_FORMATS = ["%d-%b-%y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%b-%Y"]
STATE_ABBR = {"Kerala": "KL", "Tamil Nadu": "TN", "Karnataka": "KA"}
BANKS = [("FEDERAL BANK", "FDRL"), ("SOUTH INDIAN BANK", "SIBL"), ("STATE BANK OF INDIA", "SBIN"),
         ("HDFC BANK", "HDFC"), ("CANARA BANK", "CNRB"), ("ICICI BANK", "ICIC"), ("DHANLAXMI BANK", "DLXB"),
         ("KOTAK MAHINDRA BANK", "KKBK")]
DECLARATIONS = [
    "We declare that this invoice shows the actual price of the goods described and that all "
    "particulars are true and correct.",
    "We declare that this invoice shows the actual price of the goods described and that all "
    "particulars are true and correct.",
    "1. Goods once sold will not be taken back. 2. Interest @ 18% p.a. will be charged if the bill "
    "is not paid within 15 days. 3. Our responsibility ceases once the goods leave our premises.",
    "Certified that the particulars given above are true and correct. Fruits are perishable, "
    "complaints if any to be reported at the time of delivery.",
]
# Optional columns (Tally invoice print options), in table order
COL_FRAC = {"sl": 0.032, "hsn": 0.075, "gst": 0.055, "mrp": 0.08, "qty": 0.105, "rate": 0.095,
            "per": 0.05, "disc": 0.052, "amount": 0.14}


# ---------------------------------------------------------------- number formatting

def _group(digits, style):
    if style == "plain" or len(digits) <= 3:
        return digits
    if style == "western":
        return f"{int(digits):,}"
    head, parts = digits[:-3], [digits[-3:]]
    while len(head) > 2:          # Indian grouping: 11,44,212.95
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + parts)


def _money(v, st):
    rupees, paise = f"{abs(v):.2f}".split(".")
    s = _group(rupees, st["num"]) + "." + paise
    return "-" + s if v < 0 else s


def _rate(v, st):
    if st["rate_int"] and float(v).is_integer():
        return _group(str(int(v)), st["num"])
    return _money(v, st)


def _qty(q, dp):
    if dp:
        return f"{q:.{dp}f}"
    return f"{q:.3f}".rstrip("0").rstrip(".")


def _decimals(q):
    s = _qty(q, 0)
    return len(s.split(".")[1]) if "." in s else 0


def _words(v):
    """Tally's tax-amount-in-words: INR Six Hundred Seventeen and Twenty Six paise Only."""
    rupees, paise = divmod(round(v * 100), 100)
    s = "INR " + number_to_words(rupees)
    if paise:
        s += f" and {number_to_words(paise)} paise"
    return s + " Only"


def _date_format(spec):
    d = date.fromisoformat(spec["invoice_date"])
    for fmt in DATE_FORMATS:
        if d.strftime(fmt) == spec["date_printed"]:
            return fmt
    return "%d-%b-%y"


def _wrap(text, f, maxw):
    """Greedy word wrap; words longer than a line are broken, so nothing is ever clipped."""
    lines, cur = [], ""
    for word in text.split(" "):
        cand = f"{cur} {word}" if cur else word
        if f.getlength(cand) <= maxw:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        while f.getlength(word) > maxw and len(word) > 1:
            k = len(word) - 1
            while k > 1 and f.getlength(word[:k]) > maxw:
                k -= 1
            lines.append(word[:k])
            word = word[k:]
        cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


# ---------------------------------------------------------------- random appearance

def _style(spec, rng):
    sup, buyer, items = spec["supplier"], spec["buyer"], spec["items"]
    # a spices bill can hold only 0% veg lines: Tally then posts no CGST/SGST ledgers at all
    taxed = spec["tax_mode"] != "none" and any(it["cgst"] or it["sgst"] for it in items)
    d = date.fromisoformat(spec["invoice_date"])
    dfmt = _date_format(spec)
    st = {"W": rng.randint(1600, 1700), "taxed": taxed}
    st["H"] = int(st["W"] * rng.uniform(1.405, 1.42))
    st["paper"] = "white" if rng.random() < 0.85 else "cream"
    st["ink"] = rng.choice(INKS)
    st["line_ink"] = st["ink"] if rng.random() < 0.7 else tuple(c + 50 for c in st["ink"])
    st["accent"] = rng.choice(ACCENTS) if rng.random() < 0.2 else st["ink"]
    st["body"] = rng.choice(["sans", "sans", "sans2", "narrow"])
    st["name_face"] = rng.choice([st["body"], st["body"], "narrow", "serif_bold", "condensed"])
    st["s"] = rng.randint(21, 25)
    # item rows print bigger than the header small print (about 10-11 pt on inv04 / inv12)
    st["ts"] = round(st["s"] * rng.uniform(1.08, 1.3))
    st["lw"] = rng.choice([1, 2, 2, 2, 3])
    st["ml"], st["mr"] = rng.randint(70, 125), rng.randint(60, 110)
    st["top"], st["bottom"] = rng.randint(150, 210), rng.randint(70, 130)
    st["left_frac"] = rng.uniform(0.44, 0.53)
    st["num"] = rng.choices(["indian", "plain", "western"], [0.7, 0.18, 0.12])[0]
    st["rate_int"] = rng.random() < 0.12

    # title line above the box
    if sup["gstin"] and taxed:
        st["title"] = rng.choice(["Tax Invoice", "TAX INVOICE", "Tax Invoice"])
    elif sup["gstin"]:
        st["title"] = rng.choice(["Tax Invoice", "INVOICE", "Bill of Supply", "BILL OF SUPPLY", "Invoice"])
    else:
        st["title"] = rng.choice(["INVOICE", "Invoice", "INVOICE"])
    st["copy"] = rng.choices(["(ORIGINAL FOR RECIPIENT)", "(DUPLICATE FOR TRANSPORTER)",
                              "(TRIPLICATE FOR SUPPLIER)", "ORIGINAL", ""], [0.45, 0.07, 0.06, 0.1, 0.32])[0]

    # e-invoice block (IRN / Ack No. / QR) for bigger GST-registered suppliers; a Bill of Supply
    # (exempt goods) is never e-invoiced
    st["einv"] = None
    if sup["gstin"] and st["title"].lower() == "tax invoice" and rng.random() < 0.18:
        n = 29
        st["einv"] = {"irn": "".join(rng.choice("0123456789abcdef") for _ in range(64)),
                      "ack": "1126" + "".join(rng.choice("0123456789") for _ in range(11)),
                      "ack_date": d.strftime(dfmt),
                      "qr": [[rng.random() < 0.5 for _ in range(n)] for _ in range(n)]}

    # logo: simple drawn shapes, sometimes in colour
    st["logo"] = None
    if rng.random() < 0.35:
        words = [w for w in sup["name"].replace(".", " ").split() if w[0].isalpha()]
        st["logo"] = {"shape": rng.choice(["circle", "block", "leaf", "fruit"]),
                      "color": rng.choice(ACCENTS + [st["ink"]]),
                      "initials": "".join(w[0] for w in words[:2]).upper() or "T",
                      "scale": rng.uniform(2.8, 3.6)}

    # seller letterhead lines
    lines = list(sup["address_lines"])
    if sup["fssai"] and rng.random() < 0.7:
        lines.append(rng.choice(["FSSAI No. : ", "FSSAI No: ", "FSSAI Lic. No. "]) + sup["fssai"])
    if sup["gstin"]:
        lines.append(rng.choice(["GSTIN/UIN: ", "GSTIN/UIN : ", "GSTIN : ", "GST No. "]) + sup["gstin"])
    lines.append(f"State Name : {sup['state']}, Code : {sup['state_code']}")
    if sup["gstin"] and sup["gstin"][5] == "C" and rng.random() < 0.6:
        lines.append(f"CIN: U{rng.randint(10000, 99999)}{STATE_ABBR[sup['state']]}{rng.randint(2005, 2022)}"
                     f"PTC{rng.randint(10000, 99999):06d}")
    phone = sup["phone"]
    lines.append(rng.choice([f"Contact : {phone}", f"Contact : 0091 {phone}", f"Ph : {phone}",
                             f"Mob : +91 {phone}", f"Contact : 0484-{rng.randint(2000000, 2999999)}, {phone}"]))
    if sup["email"] and rng.random() < 0.85:
        lines.append(f"E-Mail : {sup['email']}")
    st["seller_lines"] = lines
    st["name_scale"] = rng.uniform(1.15, 1.4)
    st["detail_scale"] = rng.uniform(0.8, 1.0)

    # buyer / consignee blocks
    pairs = []
    if rng.random() < 0.6:
        pairs += [(None, ln) for ln in buyer["address_lines"]]
    if rng.random() < 0.8:
        pairs.append(("GSTIN/UIN", buyer["gstin"]))
    pairs.append(("State Name", "Kerala, Code : 32"))
    if rng.random() < (0.7 if sup["state"] != "Kerala" else 0.3):
        pairs.append(("Place of Supply", "Kerala"))
    st["buyer_pairs"] = pairs
    st["consignee"] = rng.random() < 0.3
    st["buyer_head"] = rng.choice(["Buyer (Bill to)", "Buyer (Bill to)", "Buyer"])

    # right-hand grid; most cells stay empty, as on real bills
    po_date = (d - timedelta(days=rng.randint(0, 3))).strftime(dfmt)
    po = rng.choice([f"PO/{rng.randint(1000, 9999)}", f"AF/PO/{rng.randint(100, 999)}", "Phone", "Verbal"]) \
        if rng.random() < 0.25 else ""
    city = sup["address_lines"][1].split(",")[0].strip()
    st["grid"] = [
        [("Delivery Note", ""), ("Mode/Terms of Payment",
                                 rng.choice(["", "", "", "Credit", "CREDIT", "15 Days", "Cash", "30 Days Credit"]))],
        [("Reference No. & Date.", f"{po} dt. {po_date}" if po and rng.random() < 0.3 else ""),
         ("Other References", rng.choice(["", "", "", "", "Direct", "As per PO"]))],
        [("Buyer's Order No.", po), ("Dated", po_date if po else "")],
        [("Dispatch Doc No.", ""), ("Delivery Note Date", "")],
        [("Dispatched through", rng.choice(["", "", "", "Own Vehicle", "BY ROAD", "Pick Up", "Goods Auto"])),
         ("Destination", rng.choice(["", "", "Kakkanad", "KAKKANAD", "Kakkanad, Ernakulam"]))],
    ]
    if rng.random() < 0.3:
        st["grid"].append([("Bill of Lading/LR-RR No.", ""),
                           ("Motor Vehicle No.", rng.choice(["", f"KL-{rng.randint(1, 65):02d}-"
                                                             f"{rng.choice('ABCDEFGH')}{rng.choice('ABCDEFGH')}-"
                                                             f"{rng.randint(1000, 9999)}"]))])
    st["eway"] = None
    if sup["gstin"] and rng.random() < 0.35:
        st["eway"] = "".join(rng.choice("0123456789") for _ in range(12)) if rng.random() < 0.5 else ""
    st["terms"] = rng.choice(["", "", "", "Door Delivery", "Ex-Godown", "Delivery at buyer's premises"])
    # the Terms of Delivery cell is tall and mostly empty on real prints (inv04, inv12)
    st["terms_h"] = rng.uniform(3.6, 8.0)

    # item table
    cols = ["sl", "desc"]
    if rng.random() < 0.6:
        cols.append("hsn")
    if taxed and rng.random() < 0.5:
        cols.append("gst")
    if items and all(it.get("mrp") for it in items) and rng.random() < 0.6:
        cols.append("mrp")
    cols += ["qty", "rate", "per"]
    if rng.random() < 0.5:
        cols.append("disc")
    cols.append("amount")
    st["cols"] = cols
    st["col_jitter"] = {c: rng.uniform(0.9, 1.15) for c in COL_FRAC}
    st["labels"] = {"sl": rng.choice(["Sl\nNo.", "Sl\nNo.", "Sl No.", "S.No"]),
                    "desc": rng.choice(["Description of Goods", "Description of Goods", "Particulars",
                                        "Description of Goods and Services"]),
                    "hsn": "HSN/SAC", "gst": "GST\nRate", "mrp": "MRP/\nMarginal", "qty": "Quantity",
                    "rate": "Rate", "per": "per", "disc": rng.choice(["Disc. %", "Disc. %", "Disc."]),
                    "amount": "Amount"}
    st["sl_dot"] = "." if rng.random() < 0.15 else ""
    st["desc_bold"] = rng.random() < 0.8
    st["qty_bold"] = rng.random() < 0.7
    st["amt_bold"] = rng.random() < 0.75
    st["qty_unit"] = rng.random() < 0.8          # "4 Boxes" vs "4" in the Quantity column
    st["row_gap"] = rng.uniform(0.08, 0.45)
    # A Tally unit has fixed decimal places, so every quantity of that unit prints alike:
    # 12.500 KGS / 8.000 KGS, never 12.5 KGS next to 8 KGS. Whole-number kg bills (inv04) print 80 KG.
    need = {}
    for it in items:
        need[it["unit"]] = max(need.get(it["unit"], 0), _decimals(it["quantity"]))
    kg_dp = rng.choice([2, 3, 3])
    kg_whole_dp = kg_dp if rng.random() < 0.3 else 0
    st["qty_dp"] = {}
    for unit, n in need.items():
        if unit in KG_UNITS:
            st["qty_dp"][unit] = max(n, kg_dp) if n else kg_whole_dp
        else:
            st["qty_dp"][unit] = n
    st["total_qty"] = rng.random() < 0.75

    rates = {it["tax_percent"] for it in items if it["tax_percent"]}
    half = f"{list(rates)[0] / 2:g}" if len(rates) == 1 else None
    st["cgst_label"] = rng.choice(["CGST", "CGST", "Output CGST", "CGST OUTPUT"] +
                                  ([f"Output CGST @ {half}%"] if half else []))
    st["tax_half"] = half if half and "@" not in st["cgst_label"] and rng.random() < 0.7 else None
    st["round_label"] = rng.choice(["Round Off", "ROUND OFF", "Rounded Off", "Round off"])
    st["less"] = rng.random() < 0.4
    st["neg"] = rng.choice(["(-)", "(-)", "-"])
    st["rupee"] = rng.random() < 0.65

    # footer blocks
    st["eoe"] = rng.choice(["E. & O.E", "E. & O.E", "E.& O.E."])
    st["summary"] = taxed and (spec["tax_mode"] == "inclusive" or rng.random() < 0.75)
    st["tax_words"] = rng.random() < 0.8
    st["outstanding"] = None
    if rng.random() < 0.3:
        st["outstanding"] = (round(rng.uniform(2000, 1500000), 2), rng.choice(["", "", " Dr"]))
    st["pan"] = sup["gstin"][2:12] if sup["gstin"] and rng.random() < 0.4 else None
    st["bank"] = None
    if rng.random() < 0.4:
        bank, code = rng.choice(BANKS)
        st["bank"] = [("A/c Holder's Name", sup["name"]), ("Bank Name", bank),
                      ("A/c No.", "".join(rng.choice("0123456789") for _ in range(rng.choice([11, 14, 15])))),
                      ("Branch & IFS Code", f"{city.upper()} & {code}0{rng.randint(1000, 9999):06d}")]
    st["declaration"] = rng.choice(DECLARATIONS)
    st["prepared"] = rng.random() < 0.25
    st["seal"] = rng.random() < 0.2
    st["footer_slack"] = rng.randint(0, 4)
    st["jurisdiction"] = f"SUBJECT TO {city.upper()} JURISDICTION" if rng.random() < 0.45 else None
    st["computer"] = rng.random() < 0.9
    # continued page 1: Tally keeps the footer's space free under the table (about a fifth of inv12)
    st["cont_space"] = rng.uniform(0.14, 0.24)
    st["cont_fill"] = rng.uniform(0.8, 1.0)
    return st


# ---------------------------------------------------------------- drawing helpers

class _Pen:
    """Draws text and rules, returning ink bounding boxes. Without an image it only measures,
    so a layout can be dry-run to find heights before the page is drawn."""

    def __init__(self, st, img=None):
        self.st, self.img = st, img
        self.d = ImageDraw.Draw(img) if img is not None else None

    def f(self, size, bold=False, face=None):
        face = face or self.st["body"]
        if bold and face == "serif":
            face = "serif_bold"
        return hand.font(face, max(9, int(round(size))), bold)

    def text(self, xy, s, f, anchor="ls", italic=False, fill=None):
        fill = fill or self.st["ink"]
        if italic:
            return self._italic(xy, s, f, anchor, fill)
        x, y = xy
        l, t, r, b = f.getbbox(s, anchor=anchor)
        if self.d is not None:
            self.d.text((x, y), s, font=f, fill=fill, anchor=anchor)
        return (x + l, y + t, x + r, y + b)

    def _italic(self, xy, s, f, anchor, fill, k=0.2):
        """Sheared text, since no italic face is bundled. anchor: ls / rs / ms."""
        x, y = xy
        l, t, r, b = f.getbbox(s, anchor="ls")
        length = f.getlength(s)
        ox = x if anchor[0] == "l" else x - length if anchor[0] == "r" else x - length / 2
        shift = k * -t
        if anchor[0] == "r":
            ox -= shift
        if self.img is not None:
            pad = int(f.size * 0.5) + 2
            mask = Image.new("L", (int(r - l + shift) + 2 * pad, int(b - t) + 2 * pad), 0)
            base = pad - t
            ImageDraw.Draw(mask).text((pad - l, base), s, font=f, fill=255, anchor="ls")
            mask = mask.transform(mask.size, Image.AFFINE, (1, k, -k * base, 0, 1, 0), resample=Image.BICUBIC)
            self.img.paste(Image.new("RGB", mask.size, fill), (int(ox + l - pad), int(y - base)), mask)
        return (ox + l, y + t, ox + r + shift, y + b)

    def fit(self, s, maxw, size, bold=False, face=None, min_frac=0.6):
        """Largest font (down to min_frac of size) in which `s` fits maxw."""
        f = self.f(size, bold, face)
        while f.getlength(s) > maxw and f.size > size * min_frac and f.size > 9:
            f = self.f(f.size - 1, bold, face)
        return f

    def hline(self, x0, x1, y, width=None):
        if self.d is not None:
            self.d.line([(x0, y), (x1, y)], fill=self.st["line_ink"], width=width or self.st["lw"])

    def vline(self, x, y0, y1, width=None):
        if self.d is not None:
            self.d.line([(x, y0), (x, y1)], fill=self.st["line_ink"], width=width or self.st["lw"])


def _union(boxes):
    boxes = [b for b in boxes if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _ibox(b):
    return tuple(int(round(v)) for v in b) if b else None


def _logo(pen, st, x, y, L):
    lg = st["logo"]
    col = lg["color"]
    paper = PAPERS[st["paper"]]
    if pen.d is None:
        return (x, y, x + L, y + L)
    d = pen.d
    fi = hand.font("sans", int(L * 0.36), True)
    if lg["shape"] == "circle":
        d.ellipse([x, y, x + L, y + L], outline=col, width=max(2, L // 16))
        d.ellipse([x + L * 0.1, y + L * 0.1, x + L * 0.9, y + L * 0.9], outline=col, width=max(1, L // 40))
        d.text((x + L / 2, y + L / 2), lg["initials"], font=fi, fill=col, anchor="mm")
    elif lg["shape"] == "block":
        d.rounded_rectangle([x, y, x + L, y + L], radius=L // 6, fill=col)
        d.text((x + L / 2, y + L / 2), lg["initials"], font=fi, fill=paper, anchor="mm")
    elif lg["shape"] == "leaf":
        # two leaves on a stem
        for ang, sc in ((-50, 1.0), (-130, 0.75)):
            a = math.radians(ang)
            cx, cy = x + L / 2, y + L * 0.95
            pts = []
            for i in range(21):
                t = i / 20
                w = math.sin(math.pi * t) * L * 0.2 * sc
                pts.append((t * L * 0.85 * sc, w))
            for i in range(20, -1, -1):
                t = i / 20
                pts.append((t * L * 0.85 * sc, -math.sin(math.pi * t) * L * 0.2 * sc))
            rot = [(cx + px * math.cos(a) - py * math.sin(a), cy + px * math.sin(a) + py * math.cos(a))
                   for px, py in pts]
            d.polygon(rot, fill=col)
            d.line([(cx, cy), (cx + L * 0.8 * sc * math.cos(a), cy + L * 0.8 * sc * math.sin(a))],
                   fill=paper, width=max(1, L // 40))
    else:   # a round fruit with a leaf
        d.ellipse([x + L * 0.08, y + L * 0.22, x + L * 0.92, y + L], fill=col)
        d.ellipse([x + L * 0.5, y, x + L * 0.85, y + L * 0.22], fill=col)
        d.line([(x + L * 0.5, y + L * 0.25), (x + L * 0.45, y + L * 0.05)], fill=col, width=max(2, L // 25))
        d.text((x + L / 2, y + L * 0.62), lg["initials"], font=hand.font("sans", int(L * 0.3), True),
               fill=paper, anchor="mm")
    return (x, y, x + L, y + L)


def _qr(pen, st, x, y, size):
    grid = st["einv"]["qr"]
    n = len(grid)
    m = size / n
    if pen.d is None:
        return
    d = pen.d
    ink = st["ink"]
    for i in range(n):
        for j in range(n):
            if grid[i][j]:
                d.rectangle([x + j * m, y + i * m, x + (j + 1) * m - 1, y + (i + 1) * m - 1], fill=ink)
    paper = PAPERS[st["paper"]]
    for fi, fj in ((0, 0), (0, n - 7), (n - 7, 0)):     # finder patterns
        x0, y0 = x + fj * m, y + fi * m
        d.rectangle([x0 - m, y0 - m, x0 + 8 * m, y0 + 8 * m], fill=paper)
        d.rectangle([x0, y0, x0 + 7 * m - 1, y0 + 7 * m - 1], fill=ink)
        d.rectangle([x0 + m, y0 + m, x0 + 6 * m - 1, y0 + 6 * m - 1], fill=paper)
        d.rectangle([x0 + 2 * m, y0 + 2 * m, x0 + 5 * m - 1, y0 + 5 * m - 1], fill=ink)


# ---------------------------------------------------------------- page sections

def _top_band(pen, st, bx0, bx1):
    """Title (and copy label, e-invoice block) above the box. Returns (box_top, title_bbox)."""
    s = st["s"]
    y = st["top"]
    title = pen.text(((bx0 + bx1) / 2, y), st["title"], pen.f(s * 1.35, True), anchor="ms", fill=st["accent"])
    if st["copy"]:
        pen.text((bx1, y), st["copy"], pen.f(s * 0.85), anchor="rs", italic=True)
    y += round(s * 0.6)
    if st["einv"]:
        e = st["einv"]
        q = round(s * 7.5)
        fs, fb = pen.f(s * 0.78), pen.f(s * 0.85, True)
        lh = round(s * 1.3)
        yy = y + round(s * 1.0)
        pen.text((bx0 + 4, yy), "e-Invoice", fb)
        for label, value in (("IRN", e["irn"]), ("Ack No.", e["ack"]), ("Ack Date", e["ack_date"])):
            yy += lh
            pen.text((bx0 + 4, yy), label, fs)
            pen.text((bx0 + 4 + round(s * 4.5), yy), ": " + value, pen.fit(": " + value, bx1 - q - bx0 - 6 * s,
                                                                            s * 0.78))
        _qr(pen, st, bx1 - q, y, q)
        y += max(q, yy - y + lh // 2) + round(s * 0.5)
    return y, title


def _seller(pen, st, spec, x0, x1, y0):
    s = st["s"]
    pad = round(s * 0.5)
    tx, top = x0 + pad, y0 + pad
    boxes = []
    logo_bottom = top
    if st["logo"]:
        L = round(s * st["logo"]["scale"])
        boxes.append(_logo(pen, st, tx, top + 4, L))
        logo_bottom = top + 4 + L
        tx += L + pad
    maxw = x1 - pad - tx
    name = spec["supplier"]["name"]
    face = st["name_face"]
    fn = pen.fit(name, maxw, s * st["name_scale"], True, face, min_frac=0.75)
    names = _wrap(name, fn, maxw)
    y = top + 2 - min(fn.getbbox(ln, anchor="ls")[1] for ln in names[:1])    # ink top just under the rule
    for i, ln in enumerate(names):
        if i:
            y += round(fn.size * 1.15)
        boxes.append(pen.text((tx, y), ln, fn, fill=st["accent"]))
    size = s * st["detail_scale"]
    y += round(size * 0.15)
    for ln in st["seller_lines"]:
        y += round(size * 1.28)
        boxes.append(pen.text((tx, y), ln, pen.fit(ln, maxw, size, min_frac=0.65)))
    y_end = max(y + round(size * 0.35), logo_bottom) + pad
    return y_end, _union(boxes)


def _party(pen, st, x0, x1, y, heading, name, pairs):
    s = st["s"]
    pad = round(s * 0.5)
    fl, fp = pen.f(s * 0.82), pen.f(s * 0.85)
    y += round(s * 1.25)
    pen.text((x0 + pad, y), heading, fl)
    y += round(s * 1.4)
    pen.text((x0 + pad, y), name, pen.fit(name, x1 - x0 - 2 * pad, s * 1.05, True))
    labels = [lab for lab, _ in pairs if lab]
    labw = max(fp.getlength(lab) for lab in labels) + s * 0.5 if labels else 0
    for label, value in pairs:
        y += round(s * 1.25)
        if label:
            pen.text((x0 + pad, y), label, fp)
            v = ": " + value
            pen.text((x0 + pad + labw, y), v, pen.fit(v, x1 - x0 - 2 * pad - labw, s * 0.95))
        else:
            pen.text((x0 + pad, y), value, pen.fit(value, x1 - x0 - 2 * pad, s * 0.85))
    return y + round(s * 0.7)


def _grid(pen, st, spec, xm, x1, y0, compact=False):
    """The Invoice No. / Dated / Delivery Note ... cells. Returns (y_end, inv_bbox, date_bbox).
    compact=True keeps the Terms of Delivery cell short to make room for a long table."""
    s = st["s"]
    pad = round(s * 0.45)
    fl = pen.f(s * 0.8)
    cell_h = round(s * 2.75)
    xg = (xm + x1) // 2
    lab_dy, val_dy = round(s * 0.95), round(s * 2.2)
    inv, dt = spec["invoice_number_printed"], spec["date_printed"]

    y = y0
    # first row: Invoice No. (| e-Way Bill No.) | Dated
    xe = (xm + xg) // 2
    fv = pen.f(s * 1.02, True)
    split = st["eway"] is not None and fv.getlength(inv) <= xe - xm - 2 * pad
    inv_right = xe if split else xg
    pen.text((xm + pad, y + lab_dy), "Invoice No.", fl)
    inv_bbox = pen.text((xm + pad, y + val_dy), inv, pen.fit(inv, inv_right - xm - 2 * pad, s * 1.02, True, min_frac=0.5))
    if split:
        pen.text((xe + pad, y + lab_dy), "e-Way Bill No.", pen.fit("e-Way Bill No.", xg - xe - 2 * pad, s * 0.8))
        if st["eway"]:
            pen.text((xe + pad, y + val_dy), st["eway"], pen.fit(st["eway"], xg - xe - 2 * pad, s * 0.9, True))
        pen.vline(xe, y, y + cell_h)
    pen.text((xg + pad, y + lab_dy), "Dated", fl)
    date_bbox = pen.text((xg + pad, y + val_dy), dt, pen.fit(dt, x1 - xg - 2 * pad, s * 1.02, True, min_frac=0.5))
    y += cell_h
    pen.hline(xm, x1, y)

    for row in st["grid"]:
        for j, (label, value) in enumerate(row):
            cx0, cx1 = (xm, xg) if j == 0 else (xg, x1)
            pen.text((cx0 + pad, y + lab_dy), label, pen.fit(label, cx1 - cx0 - 2 * pad, s * 0.8))
            if value:
                pen.text((cx0 + pad, y + val_dy), value, pen.fit(value, cx1 - cx0 - 2 * pad, s * 0.92, True))
        y += cell_h
        pen.hline(xm, x1, y)
    pen.vline(xg, y0, y)
    pen.text((xm + pad, y + lab_dy), "Terms of Delivery", fl)
    if st["terms"]:
        pen.text((xm + pad, y + val_dy), st["terms"], pen.fit(st["terms"], x1 - xm - 2 * pad, s * 0.92))
    return y + round(s * (3.6 if compact else st["terms_h"])), inv_bbox, date_bbox


def _header(pen, st, spec, bx0, bx1, y0, compact=False):
    """Seller + buyer on the left, the grid on the right. Draws the line under it."""
    s = st["s"]
    xm = bx0 + int((bx1 - bx0) * st["left_frac"])
    yl, seller_bbox = _seller(pen, st, spec, bx0, xm, y0)
    disp = spec["buyer"]["display"]
    if st["consignee"]:
        pen.hline(bx0, xm, yl)
        yl = _party(pen, st, bx0, xm, yl, "Consignee (Ship to)", disp, st["buyer_pairs"])
    pen.hline(bx0, xm, yl)
    yl = _party(pen, st, bx0, xm, yl, st["buyer_head"], disp, st["buyer_pairs"])
    yg, inv_bbox, date_bbox = _grid(pen, st, spec, xm, bx1, y0, compact)
    bottom = max(yl + round(s * 0.8), yg)
    pen.vline(xm, y0, bottom)
    pen.hline(bx0, bx1, bottom)
    return bottom, seller_bbox, inv_bbox, date_bbox


# ---------------------------------------------------------------- item table

def _ledgers(st, spec):
    """Rows under the items: subtotal, CGST/SGST, round off (Tally prints these as ledger lines)."""
    if spec["continued"]:
        return []
    t, mode = spec["totals"], spec["tax_mode"]
    ro = t["round_off"] or 0.0
    out = []
    if mode == "exclusive" and st["taxed"]:
        out.append({"label": "", "amount": _money(t["subtotal"], st), "rule": True})
        for key, label in (("cgst", st["cgst_label"]), ("sgst", st["cgst_label"].replace("CGST", "SGST"))):
            out.append({"label": label, "amount": _money(t[key], st),
                        "rate": st["tax_half"] or "", "per": "%" if st["tax_half"] else ""})
        if t["igst"]:
            out.append({"label": "IGST", "amount": _money(t["igst"], st)})
        if t["cess"]:
            out.append({"label": "Cess", "amount": _money(t["cess"], st)})
    elif ro:
        line_sum = round(sum(it["amount"] for it in spec["items"]) + 1e-9, 2)
        out.append({"label": "", "amount": _money(line_sum, st), "rule": True})
    if ro:
        amt = (st["neg"] + _money(-ro, st)) if ro < 0 else _money(ro, st)
        label = ("Less : " if ro < 0 and st["less"] else "") + st["round_label"]
        out.append({"label": label, "amount": amt})
    return out


def _cells(st, spec):
    """Printed text of every cell of every item row."""
    rows = []
    for i, it in enumerate(spec["items"]):
        q = _qty(it["quantity"], st["qty_dp"].get(it["unit"], 0))
        rows.append({"sl": f"{i + 1}{st['sl_dot']}", "desc": it["description"], "hsn": it["hsn"],
                     "gst": f"{it['tax_percent']:g} %", "mrp": _money(it["mrp"], st) if it.get("mrp") else "",
                     "qty": f"{q} {it['unit']}" if st["qty_unit"] else q, "rate": _rate(it["rate"], st),
                     "per": it["unit"], "disc": "", "amount": _money(it["amount"], st)})
    return rows


def _total_texts(pen, st, spec):
    """(qty text, amount text) of the Total row, or None for a continued page."""
    if spec["continued"]:
        return None
    items = spec["items"]
    units = {it["unit"] for it in items}
    tq = ""
    if st["total_qty"] and len(units) == 1:
        unit = units.pop()
        q = round(sum(it["quantity"] for it in items) + 1e-9, 3)
        tq = _qty(q, st["qty_dp"].get(unit, 0)) + " " + unit
    amt = _money(spec["totals"]["grand_total"], st)
    if st["rupee"]:
        amt = ("₹ " if st["body"] in RUPEE_FACES else "Rs. ") + amt
    return tq, amt


def _table_plan(pen, st, spec, x0, x1, s, gap=None):
    """Column widths, fonts and wrapped rows for table font size s (gap: space between rows)."""
    pad = max(5, round(s * 0.35))
    fonts = {"sl": pen.f(s * 0.92), "desc": pen.f(s, st["desc_bold"]), "hsn": pen.f(s * 0.88),
             "gst": pen.f(s * 0.88), "mrp": pen.f(s * 0.92), "qty": pen.f(s, st["qty_bold"]),
             "rate": pen.f(s * 0.95), "per": pen.f(s * 0.8), "disc": pen.f(s * 0.9),
             "amount": pen.f(s, st["amt_bold"])}
    flab = pen.f(min(s, st["s"]) * 0.8)       # header labels keep their size when rows grow
    cells = _cells(st, spec)
    ledgers = _ledgers(st, spec)
    total = _total_texts(pen, st, spec)
    fb = pen.f(s, True)
    tab_w = x1 - x0

    def need(col):
        f = fonts[col]
        w = max([f.getlength(c[col]) for c in cells] + [0])
        w = max([w] + [flab.getlength(ln) for ln in st["labels"][col].split("\n")])
        if col == "amount":
            w = max([w] + [fb.getlength(lg["amount"]) for lg in ledgers] + ([fb.getlength(total[1]) * 1.05] if total else []))
        if col == "qty" and total:
            w = max(w, fb.getlength(total[0]))
        if col in ("rate", "per"):
            w = max([w] + [f.getlength(lg.get(col, "")) for lg in ledgers])
        return w + 2 * pad

    cols = list(st["cols"])
    while True:
        widths = {c: max(need(c), COL_FRAC[c] * tab_w * st["col_jitter"][c]) for c in cols if c != "desc"}
        desc_w = tab_w - sum(widths.values())
        if desc_w < 12 * s:      # too crowded: use the bare measured widths
            widths = {c: need(c) for c in cols if c != "desc"}
            desc_w = tab_w - sum(widths.values())
        optional = [c for c in ("disc", "gst", "mrp", "hsn") if c in cols]
        if desc_w >= 12 * s or not optional:
            break
        cols.remove(optional[0])
    widths["desc"] = desc_w

    xs, x = {}, x0
    for c in cols:
        xs[c] = (x, x + widths[c])
        x += widths[c]
    lh = round(s * 1.3)
    gap = round(s * st["row_gap"]) if gap is None else gap
    wraps = [_wrap(c["desc"], fonts["desc"], desc_w - 2 * pad) for c in cells]
    row_h = [len(w) * lh + gap for w in wraps]
    head_lines = max(len(st["labels"][c].split("\n")) for c in cols)
    head_h = head_lines * round(flab.size * 1.2) + 2 * pad
    top_gap = round(s * 0.5)
    led_h = (round(s * 0.4) + len(ledgers) * lh) if ledgers else 0
    total_h = (lh + 2 * pad) if total else 0
    blank = round(lh * 1.2) if total else round(s * 0.6)
    need_h = head_h + top_gap + sum(row_h) + led_h + blank + total_h
    return {"s": s, "pad": pad, "fonts": fonts, "flab": flab, "fb": fb, "cells": cells, "ledgers": ledgers,
            "total": total, "cols": cols, "xs": xs, "lh": lh, "gap": gap, "wraps": wraps, "row_h": row_h,
            "head_h": head_h, "top_gap": top_gap, "total_h": total_h, "need": need_h}


def _draw_table(pen, st, plan, x0, x1, y0, y1):
    """Item table between the header's bottom rule (y0) and y1. Returns (rows, total_bbox)."""
    s, pad, lh, xs, cols = plan["s"], plan["pad"], plan["lh"], plan["xs"], plan["cols"]
    fonts, flab = plan["fonts"], plan["flab"]
    # header labels, centred
    hl = round(flab.size * 1.2)
    for c in cols:
        lines = st["labels"][c].split("\n")
        cx = (xs[c][0] + xs[c][1]) / 2
        yy = y0 + pad + (plan["head_h"] - 2 * pad - len(lines) * hl) / 2 + round(flab.size * 0.95)
        for ln in lines:
            if c == "sl":
                pen.text((xs[c][0] + pad * 0.6, yy), ln, flab)
            else:
                pen.text((cx, yy), ln, flab, anchor="ms")
            yy += hl
    pen.hline(x0, x1, y0 + plan["head_h"])

    rows = []
    y = y0 + plan["head_h"] + plan["top_gap"]
    for c, wrap, h in zip(plan["cells"], plan["wraps"], plan["row_h"]):
        base = y + round(s * 0.98)
        boxes = []
        for k, ln in enumerate(wrap):
            boxes.append(pen.text((xs["desc"][0] + pad, base + k * lh), ln, fonts["desc"]))
        desc_bbox = _union(boxes)
        row = {"desc_bbox": desc_bbox}
        for col in cols:
            if col == "desc" or not c[col]:
                continue
            cx0, cx1 = xs[col]
            if col in ("per",):
                bb = pen.text((cx0 + pad * 0.7, base), c[col], fonts[col])
            elif col in ("hsn", "gst"):
                bb = pen.text(((cx0 + cx1) / 2, base), c[col], fonts[col], anchor="ms")
            else:
                bb = pen.text((cx1 - pad, base), c[col], fonts[col], anchor="rs")
            boxes.append(bb)
            if col == "qty":
                row["qty_bbox"] = bb
            elif col == "amount":
                row["amount_bbox"] = bb
        u = _union(boxes)
        row["y0"], row["y1"] = u[1], u[3]
        rows.append(row)
        y += h

    # ledgers: subtotal / CGST / SGST / round off
    if plan["ledgers"]:
        y += round(s * 0.4)
    ax0, ax1 = xs["amount"]
    for lg in plan["ledgers"]:
        base = y + round(s * 0.98)
        if lg.get("rule"):
            pen.hline(ax0 + pad, ax1 - pad, y + round(s * 0.05), width=max(1, st["lw"] - 1))
        if lg["label"]:
            pen.text((xs["desc"][1] - pad, base), lg["label"], plan["fb"], anchor="rs", italic=True)
        if lg.get("rate"):
            pen.text((xs["rate"][1] - pad, base), lg["rate"], fonts["rate"], anchor="rs")
        if lg.get("per"):
            pen.text((xs["per"][0] + pad * 0.7, base), lg["per"], fonts["per"])
        pen.text((ax1 - pad, base), lg["amount"], fonts["amount"], anchor="rs")
        y += lh

    # Total row at the bottom of the stretched table
    total_bbox = None
    if plan["total"]:
        ty = y1 - plan["total_h"]
        pen.hline(x0, x1, ty)
        base = ty + pad + round(s * 0.98)
        pen.text((xs["desc"][1] - pad, base), "Total", plan["fb"], anchor="rs")
        tq, amt = plan["total"]
        if tq:
            pen.text((xs["qty"][1] - pad, base), tq, plan["fb"], anchor="rs")
        f = pen.fit(amt, ax1 - ax0 - pad * 1.5, s * 1.05, True)
        total_bbox = pen.text((ax1 - pad, base), amt, f, anchor="rs")
    for c in cols[1:]:
        pen.vline(xs[c][0], y0, y1)
    pen.hline(x0, x1, y1)
    return rows, total_bbox


# ---------------------------------------------------------------- below the table

def _tax_summary(pen, st, spec, x0, x1, y):
    """Tally's HSN/SAC summary: Taxable Value | Central Tax | State Tax | Total Tax Amount."""
    s = st["s"]
    f, fb = pen.f(s * 0.78), pen.f(s * 0.78, True)
    pad = round(s * 0.35)
    lh = round(s * 1.15)
    groups = {}
    for it in spec["items"]:
        g = groups.setdefault((it["hsn"], it["tax_percent"]), [0.0, 0.0, 0.0])
        g[0] += it["taxable"]
        g[1] += it["cgst"]
        g[2] += it["sgst"]
    t = spec["totals"]
    w = x1 - x0
    fr = [0.27, 0.16, 0.075, 0.13, 0.075, 0.13, 0.16]
    xs = [x0]
    for v in fr:
        xs.append(xs[-1] + v * w)
    xs[-1] = x1
    pen.hline(x0, x1, y)
    top = y
    # two-line header with Central Tax / State Tax spanning Rate + Amount
    b1, b2 = y + round(s * 0.95), y + round(s * 0.95) + lh
    pen.text(((xs[0] + xs[1]) / 2, (b1 + b2) / 2), "HSN/SAC", f, anchor="ms")
    pen.text(((xs[1] + xs[2]) / 2, (b1 + b2) / 2), "Taxable Value", f, anchor="ms")
    pen.text(((xs[2] + xs[4]) / 2, b1), "Central Tax", f, anchor="ms")
    pen.text(((xs[4] + xs[6]) / 2, b1), "State Tax", f, anchor="ms")
    pen.text(((xs[6] + xs[7]) / 2, b1), "Total", f, anchor="ms")
    for k in (2, 4):
        pen.text(((xs[k] + xs[k + 1]) / 2, b2), "Rate", f, anchor="ms")
        pen.text(((xs[k + 1] + xs[k + 2]) / 2, b2), "Amount", f, anchor="ms")
    pen.text(((xs[6] + xs[7]) / 2, b2), "Tax Amount", f, anchor="ms")
    pen.hline(xs[2], xs[6], b1 + round(s * 0.3), width=1)
    y = b2 + pad
    pen.hline(x0, x1, y)
    for (hsn, pct), (taxable, cg, sg) in groups.items():
        y += lh
        rate = f"{pct / 2:g}%"
        vals = [_money(round(taxable + 1e-9, 2), st), rate, _money(round(cg + 1e-9, 2), st), rate,
                _money(round(sg + 1e-9, 2), st), _money(round(cg + sg + 1e-9, 2), st)]
        pen.text((xs[0] + pad, y), hsn, f)
        for k, v in enumerate(vals):
            pen.text((xs[k + 2] - pad, y), v, f, anchor="rs")
    y += round(s * 0.45)
    pen.hline(x0, x1, y)
    y += lh
    vals = [_money(t["subtotal"], st), "", _money(t["cgst"], st), "", _money(t["sgst"], st),
            _money(round(t["cgst"] + t["sgst"] + 1e-9, 2), st)]
    pen.text((xs[1] - pad, y), "Total", fb, anchor="rs")
    for k, v in enumerate(vals):
        if v:
            pen.text((xs[k + 2] - pad, y), v, fb, anchor="rs")
    y += round(s * 0.45)
    pen.hline(x0, x1, y)
    for k in range(1, 7):
        y_start = b1 + round(s * 0.3) if k in (3, 5) else top
        pen.vline(xs[k], y_start, y)
    return y


def _footer(pen, st, spec, x0, x1, y0, drop):
    """Amount in words ... Authorised Signatory. Returns the y of the box bottom.
    drop=True leaves out the optional middle blocks to make room for a long table."""
    s = st["s"]
    pad = round(s * 0.5)
    fs, fb = pen.f(s * 0.82), pen.f(s, True)
    lh = round(s * 1.3)
    if spec["continued"]:
        y = y0 + round(s * 1.6)
        pen.text((x1 - pad * 2, y), "continued ...", pen.f(s * 0.9), anchor="rs")
        return y0 + max(round(st["H"] * st["cont_space"]), round(s * 3))

    y = y0 + round(s * 1.15)
    pen.text((x0 + pad, y), "Amount Chargeable (in words)", fs)
    pen.text((x1 - pad, y), st["eoe"], fs, anchor="rs", italic=True)
    for ln in _wrap(spec["amount_in_words"] or "", fb, x1 - x0 - 2 * pad):
        y += lh
        pen.text((x0 + pad, y), ln, fb)
    y += round(s * 0.6)
    if st["summary"]:
        y = _tax_summary(pen, st, spec, x0, x1, y + round(s * 0.3))
        if st["tax_words"]:
            y += lh
            head = "Tax Amount (in words) :  "
            pen.text((x0 + pad, y), head, fs)
            words = _words(round(spec["totals"]["cgst"] + spec["totals"]["sgst"] + 1e-9, 2))
            pen.text((x0 + pad + fs.getlength(head), y), words,
                     pen.fit(words, x1 - x0 - 2 * pad - fs.getlength(head), s * 0.9, True))
        y += round(s * 0.5)

    xm = (x0 + x1) // 2
    yl = yr = y
    if st["outstanding"] and not drop:
        prev, suffix = st["outstanding"]
        cur = spec["totals"]["grand_total"]
        yl += lh
        pen.text((x0 + pad, yl), "Outstanding Details", pen.f(s * 0.85))
        rows = [("Previous Outstanding", prev), ("Current Invoice", cur), ("Total Outstanding", round(prev + cur, 2))]
        for label, v in rows:
            yl += round(s * 1.2)
            pen.text((x0 + pad, yl), label, fs)
            pen.text((x0 + pad + s * 10, yl), ":", fs)
            pen.text((x0 + pad + s * 17.5, yl), _money(v, st) + suffix, fs, anchor="rs")
    if st["pan"]:
        yl += round(s * 1.4)
        pen.text((x0 + pad, yl), "Company's PAN", fs)
        pen.text((x0 + pad + s * 6.5, yl), ":  " + st["pan"], pen.f(s * 0.85, True))
    if st["bank"] and not drop:
        yr += lh
        bx = xm + pad
        pen.text((bx, yr), "Company's Bank Details", pen.f(s * 0.85))
        labw = max(fs.getlength(lab) for lab, _ in st["bank"]) + s * 0.4
        for label, value in st["bank"]:
            yr += round(s * 1.2)
            pen.text((bx, yr), label, fs)
            v = ": " + value
            pen.text((bx + labw, yr), v, pen.fit(v, x1 - bx - labw - pad, s * 0.85, True))
    y = max(yl, yr) + round(s * (1.2 + (0 if drop else st["footer_slack"])))

    # declaration (left) and signatory box (right)
    sig_top = y
    yd = y + round(s * 0.9)
    if st["seal"]:
        yd += round(s * 2.6)
    dw = xm - x0 - 2 * pad
    fdecl = pen.f(s * 0.8)
    d_head = pen.text((x0 + pad, yd), "Declaration", fdecl)
    pen.hline(d_head[0], d_head[2], d_head[3] + 2, width=1)
    for ln in _wrap(st["declaration"], fdecl, dw):
        yd += round(s * 1.08)
        pen.text((x0 + pad, yd), ln, fdecl)
    sig_h = round(s * 4.8)
    end = max(yd + pad, sig_top + sig_h)
    pen.hline(xm, x1, sig_top)
    pen.vline(xm, sig_top, end)
    for_name = "for " + spec["supplier"]["name"]
    pen.text((x1 - pad, sig_top + round(s * 1.2)), for_name, pen.fit(for_name, x1 - xm - 2 * pad, s * 0.92, True),
             anchor="rs")
    pen.text((x1 - pad, end - pad), "Authorised Signatory", fs, anchor="rs")
    if st["prepared"]:
        pen.text((xm + pad, end - pad), "Prepared by", fs)
        pen.text((xm + pad + s * 7, end - pad), "Verified by", fs)
    if st["seal"]:
        pen.text((x0 + pad, sig_top + round(s * 1.2)), "Customer's Seal and Signature", fs)
    return end


def _below_box(pen, st, W, y):
    """Small print under the box. Returns its height."""
    s = st["s"]
    fs = pen.f(s * 0.8)
    y0 = y
    if st["jurisdiction"]:
        y += round(s * 1.3)
        pen.text((W / 2, y), st["jurisdiction"], fs, anchor="ms")
    if st["computer"]:
        y += round(s * 1.3)
        pen.text((W / 2, y), "This is a Computer Generated Invoice", fs, anchor="ms")
    return y - y0 + round(s * 0.4)


# ---------------------------------------------------------------- render

def render(spec, rng):
    st = _style(spec, rng)
    W, H = st["W"], st["H"]
    bx0, bx1 = st["ml"], W - st["mr"]

    # dry run: measure header, footer and table, shrink or drop blocks until the table fits
    dry = _Pen(st)
    box_top, _ = _top_band(dry, st, bx0, bx1)
    below_h = _below_box(dry, st, W, 0)
    tries = [(False, st["ts"])] + [(True, ts) for ts in range(st["ts"], 13, -1)]
    for drop, ts in tries:
        head_bottom = _header(dry, st, spec, bx0, bx1, box_top, drop)[0]
        foot_h = _footer(dry, st, spec, bx0, bx1, 0, drop)
        plan = _table_plan(dry, st, spec, bx0, bx1, ts, round(ts * 0.1) if drop else None)
        if head_bottom + plan["need"] + foot_h + below_h + st["bottom"] <= H:
            break
    H = max(H, head_bottom + plan["need"] + foot_h + below_h + st["bottom"])   # very long bills grow the page
    st["H"] = H
    box_bottom = H - st["bottom"] - below_h
    table_bottom = box_bottom - foot_h
    if spec["continued"]:
        # Tally broke the page where the rows reached the space it keeps free for the totals. As on
        # inv12, the rows run in big type with loose spacing, the table ends at that reserve and
        # "continued ..." is printed under it.
        room = (table_bottom - head_bottom) * st["cont_fill"]
        for ts in range(round(st["s"] * 1.45), plan["s"], -1):
            p = _table_plan(dry, st, spec, bx0, bx1, ts, round(ts * 0.3))
            if p["need"] <= room:
                plan = p
                break
        n = max(1, len(spec["items"]))
        gap = (room - (plan["need"] - n * plan["gap"])) / n
        gap = int(max(plan["gap"], min(gap, plan["s"] * 0.6)))
        plan = _table_plan(dry, st, spec, bx0, bx1, plan["s"], gap)

    page = Image.new("RGB", (W, H), PAPERS[st["paper"]])
    pen = _Pen(st, page)
    _, title_bbox = _top_band(pen, st, bx0, bx1)
    head_bottom, seller_bbox, inv_bbox, date_bbox = _header(pen, st, spec, bx0, bx1, box_top, drop)
    rows, total_bbox = _draw_table(pen, st, plan, bx0, bx1, head_bottom, table_bottom)
    _footer(pen, st, spec, bx0, bx1, table_bottom, drop)
    _below_box(pen, st, W, box_bottom)
    # outer box
    lw = st["lw"] + (1 if st["lw"] < 3 else 0)
    pen.d.rectangle([bx0, box_top, bx1, box_bottom], outline=st["line_ink"], width=lw)

    notes_right = min(title_bbox[0] - 30, bx0 + (bx1 - bx0) * 0.42)
    layout = {
        "table_bbox": _ibox((bx0, head_bottom, bx1, table_bottom)),
        "header_bbox": _ibox(seller_bbox),
        "invoice_number_bbox": _ibox(inv_bbox),
        "date_bbox": _ibox(date_bbox),
        "rows": [{k: (_ibox(v) if isinstance(v, tuple) else int(round(v))) for k, v in r.items()} for r in rows],
        "total_bbox": _ibox(total_bbox),
        "notes_area": _ibox((bx0, 12, notes_right, title_bbox[1] - 10)),
        "paper": st["paper"],
    }
    return page, layout
