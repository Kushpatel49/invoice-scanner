"""GST tax invoice printed on A4 by a billing / ERP system (laser print, ruled boxes).

Two families, modelled on real bills in eval/samples:

  erp      dense ERP print (inv03, Muralya Dairy): one-line letterhead with CIN/PAN/FSSAI,
           an INVOICE box with two columns of "Label: value" fields, receiver / consignee
           blocks, a wide grid table with per-row CGST/SGST/IGST rate+amount column pairs,
           an "Add : CGST ..." totals stack, certification + signatory, declaration, QR, IRN.
  classic  TAX INVOICE (inv07, SH Foods): GSTIN on top, centred letterhead, invoice/transport
           field grid, Billed to / Shipped to, IRN + Ack line, item table whose column lines
           run down to the totals band, tax summary, amount in words, bank details and a
           terms | e-invoice QR | signatory footer.

Fonts, inks, column sets, number formats and optional blocks vary per bill. All random
choices are made up front in _pick_style, so a page can be drawn twice (measure, then
final) and come out identical.
"""
import numpy as np
from PIL import Image, ImageDraw

from bench.synth import hand

# family -> (regular font, bold font, has a rupee glyph). PT Serif draws a wrong glyph for U+20B9.
FAMILIES = {
    "sans": ("sans", "sans", True), "sans2": ("sans2", "sans2", False), "narrow": ("narrow", "narrow", True),
    "serif": ("serif", "serif_bold", False), "condensed": ("condensed", "condensed", True),
}
RUPEE = "₹"

PAPERS = {"white": (255, 255, 255), "cream": (249, 245, 234)}
INKS = [(20, 20, 24), (30, 30, 34), (38, 38, 44), (50, 50, 56)]
ACCENTS = [(25, 55, 135), (135, 28, 40), (20, 95, 60), (45, 45, 120), (150, 70, 20)]

BANKS = [("KOTAK MAHINDRA BANK", "KKBK"), ("STATE BANK OF INDIA", "SBIN"), ("THE FEDERAL BANK LTD", "FDRL"),
         ("SOUTH INDIAN BANK", "SIBL"), ("HDFC BANK LTD", "HDFC"), ("ICICI BANK", "ICIC"),
         ("CANARA BANK", "CNRB"), ("DHANLAXMI BANK", "DLXB"), ("CSB BANK", "CSBK"), ("AXIS BANK", "UTIB")]
TERMS = [
    "Goods once sold will not be taken back.",
    "Interest @ 18% p.a. will be charged if the payment is not made within the stipulated time.",
    "Subject to 'ERNAKULAM' Jurisdiction only.",
    "Our responsibility ceases as soon as the goods leave our premises.",
    "Please check the goods at the time of delivery. No complaints entertained afterwards.",
    "Payment within 30 days from the date of invoice.",
    "Cheques subject to realisation.",
]
DECLARATIONS = [
    "We hereby certify that food / foods mentioned in this invoice is / are warranted to be of the nature "
    "and quality which it / these purports / purport to be.",
    "We declare that this invoice shows the actual price of the goods described and that all particulars "
    "are true and correct.",
    "Certified that the particulars given above are true and correct and the amount indicated represents "
    "the price actually charged.",
]
COPY_LABELS = ["(ORIGINAL/DUPLICATE/TRIPLICATE)", "Original for Recipient", "ORIGINAL FOR RECIPIENT",
               "(ORIGINAL FOR BUYER)", "Duplicate for Transporter", "Triplicate for Supplier"]
TRANSPORTS = ["Road", "By Road", "Truck", "Van", "Own Vehicle", "Tempo"]
STATIONS = ["KAKKANAD", "KUSUMAGIRI", "ERNAKULAM", "INFOPARK", "KOCHI"]


# ---------------------------------------------------------------- number formatting

def _group(digits, style):
    if style == "western":
        return f"{int(digits):,}"
    if style == "indian" and len(digits) > 3:
        head, parts = digits[:-3], [digits[-3:]]
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        return ",".join([head] + parts)
    return digits


def _num(x, dec, group="none"):
    s = f"{abs(x):.{dec}f}"
    ip, _, fp = s.partition(".")
    neg = x < 0 and float(s) != 0
    return ("-" if neg else "") + _group(ip, group) + ("." + fp if fp else "")


def _need(x, most=3):
    """Fewest decimals that print x exactly."""
    for d in range(most + 1):
        if abs(round(x, d) - x) < 1e-9:
            return d
    return most


def _money(x, st):
    return _num(x, 2, st["group"])


def _qty(q, st):
    d = _need(q) if st["qd"] is None else st["qd"]
    return _num(q, d)


def _rate(r, st):
    d = _need(r, 2) if st["rd"] is None else st["rd"]
    return _num(r, d, st["group"] if r >= 1000 else "none")


def _pct(p, st):
    return st["pct"].format(p)


def _grand(x, st):
    """Grand total as this bill prints it: 9,655.00 / 9,655 / 9655.0 (only when that is still exact)."""
    style = st["gt"]
    if style == "int" and _need(x) == 0:
        return _num(x, 0, st["group"])
    if style == "1dp" and _need(x) <= 1:
        return _num(x, 1, st["group"])
    return _money(x, st)


# ---------------------------------------------------------------- drawing helpers

def _font(family, size, bold=False):
    reg, bold_name, _ = FAMILIES[family]
    return hand.font(bold_name if bold else reg, max(8, int(round(size))), bold=bold)


def _union(*boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _wrap(text, font, width):
    """Greedy word wrap; a word wider than the column is split rather than clipped."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}" if cur else word
        if font.getlength(trial) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        while font.getlength(word) > width and len(word) > 1:
            k = len(word) - 1
            while k > 1 and font.getlength(word[:k]) > width:
                k -= 1
            lines.append(word[:k])
            word = word[k:]
        cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


class Sheet:
    """The page plus the drawing helpers every block needs. Text defaults to anchor "la":
    (x, y) is the top-left of the line box, so successive lines step y by a line height."""

    def __init__(self, st, height):
        self.st = st
        self.img = Image.new("RGB", (st["W"], height), st["paper_rgb"])
        self.d = ImageDraw.Draw(self.img)

    def font(self, size, bold=False, family=None):
        return _font(family or self.st["family"], size, bold)

    def text(self, x, y, s, size, bold=False, fill=None, anchor="la", family=None, font=None):
        if not s:
            return None
        f = font or self.font(size, bold, family)
        self.d.text((x, y), s, font=f, fill=fill or self.st["ink"], anchor=anchor)
        return self.d.textbbox((x, y), s, font=f, anchor=anchor)

    def w(self, s, size, bold=False, family=None):
        return self.font(size, bold, family).getlength(s)

    def hline(self, x0, x1, y, width=None, fill=None):
        self.d.line([(x0, y), (x1, y)], fill=fill or self.st["line"], width=width or self.st["lw"])

    def vline(self, x, y0, y1, width=None, fill=None):
        self.d.line([(x, y0), (x, y1)], fill=fill or self.st["line"], width=width or self.st["lw"])

    def frame(self, x0, y0, x1, y1, width=None, fill=None):
        self.d.rectangle((x0, y0, x1, y1), outline=fill or self.st["line"], width=width or self.st["lw"])

    def fields(self, x, y, w, rows, size, aligned=False, gap=1.32):
        """'Label : value' lines in a column of width w. rows: (label, value, key or None).
        Returns (y below the block, {key: bbox of the value text})."""
        st = self.st
        fl = self.font(size, st["label_bold"])
        fv = self.font(size, False)
        lh = int(size * gap)
        boxes = {}
        lw = max((fl.getlength(r[0]) for r in rows), default=0) + size * 0.5
        for label, value, key in rows:
            if aligned:
                self.text(x, y, label, size, font=fl)
                cb = self.text(x + lw, y, ":", size, font=fl)
                vx = cb[2] + size * 0.5
            else:
                lb = self.text(x, y, label + st["colon"], size, font=fl)
                vx = lb[2] + size * 0.35
            vfont = self.font(size, True) if key == "inv" and st["inv_bold"] else fv
            lines = _wrap(value, vfont, x + w - vx) if value else []
            for i, line in enumerate(lines):
                b = self.text(vx, y + i * lh, line, size, font=vfont)
                if key:
                    boxes[key] = _union(boxes.get(key), b)
            y += lh * max(1, len(lines))
        return y, boxes


def _qr_matrix(rng, n):
    """Random modules with the three finder squares and timing lines - reads as a QR at a glance."""
    nbytes = (n * n + 7) // 8
    raw = rng.getrandbits(8 * nbytes).to_bytes(nbytes, "little")
    m = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n * n].reshape(n, n).astype(bool)
    m[6, :] = np.arange(n) % 2 == 0
    m[:, 6] = np.arange(n) % 2 == 0
    for r, c in ((0, 0), (0, n - 7), (n - 7, 0)):
        m[max(r - 1, 0):r + 8, max(c - 1, 0):c + 8] = False
        m[r:r + 7, c:c + 7] = True
        m[r + 1:r + 6, c + 1:c + 6] = False
        m[r + 2:r + 5, c + 2:c + 5] = True
    a = n - 9
    m[a:a + 5, a:a + 5] = True
    m[a + 1:a + 4, a + 1:a + 4] = False
    m[a + 2, a + 2] = True
    return m


def _draw_qr(sh, x, y, size, m):
    n = m.shape[0]
    mod = max(2, int(size // n))
    mask = Image.fromarray(np.where(m, 255, 0).astype(np.uint8), "L").resize((n * mod, n * mod), Image.NEAREST)
    sh.img.paste(Image.new("RGB", mask.size, sh.st["ink"]), (int(x), int(y)), mask)
    return (int(x), int(y), int(x) + n * mod, int(y) + n * mod)


def _leaf(cx, cy, length, width, angle):
    """Points of a pointed leaf whose base is at (cx, cy), pointing along `angle` (radians)."""
    pts = []
    for i in range(25):
        t = np.pi * i / 24
        pts.append((length * (1 - np.cos(t)) / 2, width * np.sin(t)))
    pts += [(u, -v) for u, v in reversed(pts)]
    ca, sa = np.cos(angle), np.sin(angle)
    return [(cx + u * ca - v * sa, cy + u * sa + v * ca) for u, v in pts]


def _logo(sh, cx, cy, r, st):
    """A simple drawn logo; returns its bbox."""
    kind, color, initials = st["logo"], st["accent"], st["initials"]
    d = sh.d
    box = (cx - r, cy - r, cx + r, cy + r)
    lw = max(2, int(r / 9))
    fam = "sans" if st["family"] == "serif" else st["family"]
    if kind == "ring":
        d.ellipse(box, outline=color, width=lw)
        d.ellipse((cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82), outline=color, width=max(1, lw // 2))
        sh.text(cx, cy, initials, r * 0.75, bold=True, fill=color, anchor="mm", family=fam)
    elif kind == "disc":
        d.ellipse(box, fill=color)
        sh.text(cx, cy, initials, r * 0.8, bold=True, fill=st["paper_rgb"], anchor="mm", family=fam)
    elif kind == "badge":
        d.rounded_rectangle(box, radius=int(r * 0.3), fill=color)
        sh.text(cx, cy, initials, r * 0.75, bold=True, fill=st["paper_rgb"], anchor="mm", family=fam)
    elif kind == "leaf":
        # one broad leaf with a pale midrib and a short stem, pointing up and to the right
        angle = -np.pi / 4
        base = (cx - r * 0.62, cy + r * 0.62)
        d.polygon(_leaf(*base, r * 1.75, r * 0.5, angle), fill=color)
        tip = (base[0] + r * 1.45 * np.cos(angle), base[1] + r * 1.45 * np.sin(angle))
        d.line([base, tip], fill=st["paper_rgb"], width=max(1, lw // 2))
        d.line([base, (base[0] - r * 0.25, base[1] + r * 0.3)], fill=color, width=lw)
    else:  # drop
        top = (cx, cy - r)
        d.ellipse((cx - r * 0.62, cy - r * 0.1, cx + r * 0.62, cy + r), fill=color)
        d.polygon([top, (cx - r * 0.58, cy + r * 0.3), (cx + r * 0.58, cy + r * 0.3)], fill=color)
        d.ellipse((cx - r * 0.2, cy + r * 0.25, cx + r * 0.05, cy + r * 0.55), fill=st["paper_rgb"])
    return tuple(int(v) for v in box)


# ---------------------------------------------------------------- style

def _initials(name):
    words = [w for w in name.replace(".", " ").split() if w not in ("THE", "ST", "&")]
    if words and len(words[0]) <= 3:
        return words[0][:3]
    return "".join(w[0] for w in words[:2])


def _pick_style(spec, rng):
    """Every random decision for one bill. Drawing itself uses no randomness."""
    sup, items, mode = spec["supplier"], spec["items"], spec["tax_mode"]
    erp = rng.random() < 0.4
    dpi = rng.uniform(184, 200)
    pt = dpi / 72
    family = rng.choice(["sans", "sans", "sans2", "narrow", "serif"])
    paper = "white" if rng.random() < 0.85 else "cream"
    ink = rng.choice(INKS)
    st = {
        "kind": "erp" if erp else "classic", "dpi": dpi, "W": int(8.27 * dpi), "H": int(11.69 * dpi),
        "ml": int(dpi * rng.uniform(0.28, 0.5)), "mr": int(dpi * rng.uniform(0.28, 0.5)),
        "top": int(dpi * rng.uniform(0.3, 0.55)), "bottom": int(dpi * rng.uniform(0.35, 0.6)),
        "family": family, "paper": paper, "paper_rgb": PAPERS[paper], "ink": ink,
        "tfamily": family if rng.random() < 0.65 else rng.choice(["narrow", "sans", "sans2"]),
        "nfamily": rng.choice([family, family, "condensed", "serif", "sans"]),
        "accent": ink if rng.random() < 0.4 else rng.choice(ACCENTS),
        "body0": rng.uniform(7.8, 9.0) * pt,
        "tsize0": (rng.uniform(6.9, 8.0) if erp else rng.uniform(7.5, 8.8)) * pt,
        "name_size": (rng.uniform(15, 24) if not erp else rng.uniform(14, 20)) * pt,
        "lw": rng.choice([1, 2, 2, 2, 3]),
        "label_bold": rng.random() < 0.55,
        "inv_bold": rng.random() < 0.35,
        "colon": rng.choice([": ", " : ", ":"]),
        # number formats
        "group": rng.choices(["indian", "western", "none"], [0.45, 0.2, 0.35])[0],
        "qd": rng.choice([3, 3, 2, None] if erp else [None, 2, 2, 3]),
        "rd": rng.choice([2, 6, 2] if erp else [2, 2, 2, None]),
        "pct": rng.choice(["{}%", "{:.2f}", "{:.2f}%", "{:.1f}%"]),
        "gt": rng.choice(["2dp", "2dp", "int", "rupee"] + (["1dp"] if erp else [])),
        # optional blocks
        "einvoice": bool(sup["gstin"]) and rng.random() < 0.75,
        "bank": rng.random() < 0.7, "terms": rng.random() < 0.8, "declaration": rng.random() < 0.6,
        "consignee": rng.random() < 0.75, "computer_generated": rng.random() < 0.4,
        "compact": False,
    }
    gray = tuple(min(255, c + rng.randint(40, 90)) for c in ink)
    st["line"] = gray if (erp and rng.random() < 0.6) else ink
    if erp:
        st["lw"] = rng.choice([1, 1, 2])
    # a bill's quantity / rate columns use one decimal count wide enough for every row
    if st["qd"] is not None:
        st["qd"] = max([st["qd"]] + [_need(it["quantity"]) for it in items])
    if st["rd"] is not None:
        st["rd"] = max([st["rd"]] + [_need(it["rate"], 2) for it in items])
    st["has_rupee"] = FAMILIES[st["tfamily"]][2]     # table font (headers, cells, totals band)
    if st["gt"] == "rupee" and not st["has_rupee"]:
        st["gt"] = "rs"
    st["logo"] = rng.choice([None, "ring", "disc", "badge", "leaf", "drop"])
    st["initials"] = _initials(sup["name"])
    st["logo_r"] = int(dpi * rng.uniform(0.22, 0.38))
    st["copy_label"] = rng.choice(COPY_LABELS) if rng.random() < 0.75 else None
    st["qr"] = _qr_matrix(rng, rng.choice([41, 49, 57, 65]))
    st["qr_in"] = rng.uniform(0.95, 1.35)

    # made-up but plausible reference numbers
    hexd = "0123456789abcdef"
    st["irn"] = "".join(rng.choice(hexd) for _ in range(64))
    st["ack"] = "1526" + "".join(rng.choice("0123456789") for _ in range(11))
    st["ewb"] = "".join(rng.choice("0123456789") for _ in range(12)) if rng.random() < 0.4 else ""
    st["vehicle"] = (f"KL-{rng.choice(['07', '39', '40', '41', '42', '44', '63'])}-"
                     f"{rng.choice('ABCDEFGHJK')}{rng.choice('ABCDEFGHJK')}-{rng.randint(1000, 9999)}"
                     if rng.random() < 0.6 else "")
    st["transport"] = rng.choice(TRANSPORTS)
    st["station"] = rng.choice(STATIONS)
    st["po"] = f"PO/{rng.randint(1000, 9999)}" if rng.random() < 0.25 else ""
    st["retailer"] = "".join(rng.choice("ABCDEFGHKLMNPRS") for _ in range(6)) + f"{rng.randint(100, 9999):04d}"
    st["buyer_mobile"] = rng.choice("98") + "".join(rng.choice("0123456789") for _ in range(9))
    bank, code = rng.choice(BANKS)
    town = sup["address_lines"][-1].split(",")[0].upper()
    st["bank_lines"] = [f"{bank}, {town} BRANCH",
                        f"A/c No.: {rng.randint(10 ** 11, 10 ** 14 - 1)}, IFSC : {code}0{rng.randint(100000, 999999)}"]
    st["terms_list"] = rng.sample(TERMS, rng.randint(2, 4))
    st["decl"] = rng.choice(DECLARATIONS)
    is_company = any(w in sup["name"] for w in ("PVT", "PRIVATE", "LTD"))
    cin_state = {"Kerala": "KL", "Tamil Nadu": "TN", "Karnataka": "KA"}.get(sup["state"], "KL")
    st["cin"] = (f"U{rng.randint(10000, 99999)}{cin_state}{rng.randint(1995, 2022)}PTC{rng.randint(10000, 99999):06d}"
                 if is_company and rng.random() < 0.8 else None)
    st["place_of_supply"] = rng.choice(["Kerala (32)", "KERALA (32)", "32-Kerala", "ERNAKULAM", "Kerala"])

    if erp:
        st["head"] = rng.choice(["line", "line", "left"])
        st["notes_gap"] = int(dpi * rng.uniform(0.3, 0.55))
        st["title"] = rng.choice(["INVOICE", "TAX INVOICE", "Tax Invoice"] if sup["gstin"] else ["INVOICE", "Invoice"])
        st["inv_label"] = rng.choice(["Invoice Serial Number", "Invoice No", "Invoice Number", "Bill No"])
        st["date_label"] = rng.choice(["Invoice Date", "Invoice Date", "Date"])
        st["grid"] = "grid"
        st["head_fill"] = None
        st["delivery_date"] = rng.random() < 0.6
        st["show_retailer"] = rng.random() < 0.6
        st["igst_col"] = rng.random() < 0.75
        st["cess_col"] = rng.random() < 0.4
        st["total_col"] = rng.random() < 0.6 or mode == "inclusive"
        st["disc_col"] = rng.random() < 0.5
        # "2,180.80 ₹" in cells and in the totals stack, which uses the body font
        st["rupee_suffix"] = st["has_rupee"] and FAMILIES[family][2] and rng.random() < 0.4
        st["sub_heads"] = rng.choice([("Rate", "Amount"), ("%", "Amt"), ("Rate", "Amt")])
        st["words_label"] = rng.choice(["Invoice Value (In Words): ", "Amount in Words : ", "Total in words: "])
        st["reverse_row"] = rng.random() < 0.7
        st["extra_tax_rows"] = rng.random() < 0.6
    else:
        st["head"] = rng.choice(["center", "center", "left"])
        st["grid"] = rng.choice(["columns", "columns", "grid", "open"])
        st["fill_frac"] = rng.uniform(0.0, 0.35) if st["grid"] == "open" else rng.uniform(0.55, 1.0)
        st["head_fill"] = rng.choice([None, None, "gray", "tint"] + (["dark"] if st["grid"] == "open" else []))
        st["title"] = "TAX INVOICE" if sup["gstin"] else rng.choice(["INVOICE", "BILL"])
        st["title_underline"] = rng.random() < 0.6
        st["head_in_box"] = rng.random() < 0.7
        st["meta_split"] = rng.uniform(0.48, 0.56)
        # grid: invoice | transport fields above Billed to | Shipped to (inv07)
        # buyer_left: buyer on the left, "Label : value" invoice fields on the right
        # tally: buyer on the left, Tally-style label-over-value cells on the right
        st["meta"] = rng.choice(["grid", "grid", "buyer_left", "tally"])
        st["inv_label"] = rng.choice(["Invoice No.", "Invoice No.", "Inv. No.", "Bill No.", "Invoice Number"])
        st["date_label"] = "Dated" if st["meta"] == "tally" or rng.random() < 0.4 else \
            rng.choice(["Date", "Invoice Date", "Inv. Date"])
        st["bill_label"] = rng.choice(["Billed to :", "Billed to :", "Bill To :", "Buyer (Bill to)",
                                       "Details of Buyer :", "Party :"])
        st["ship_label"] = rng.choice(["Shipped to :", "Ship To :", "Consignee (Ship to)", "Delivery Address :"])
        st["pay_terms"] = rng.choice(["", "", "Credit", "15 Days", "30 Days", "Cash/Credit"])
        st["fit_desc"] = rng.random() < 0.7
        st["per_row_tax"] = mode == "inclusive" and rng.random() < 0.7
        st["igst_col"] = st["per_row_tax"] and rng.random() < 0.5
        st["taxable_col"] = st["per_row_tax"] and rng.random() < 0.4
        st["unit_after_rate"] = rng.random() < 0.3
        st["disc_col"] = rng.random() < 0.25
        st["mrp_col"] = any(it["mrp"] for it in items) or rng.random() < 0.04
        st["total_qty"] = len({it["unit"] for it in items}) == 1 and rng.random() < 0.5
        st["summary"] = mode != "none" and (mode == "inclusive" or rng.random() < 0.65)
        st["summary_kind"] = rng.choice(["rate", "rate", "hsn"])
        st["words_label"] = rng.choice(["", "", "Amount Chargeable (in words) : ", "Rupees in words : "])
        st["tax_label"] = rng.choice(["Add : {}", "{}", "Output {}"])
        st["round_style"] = rng.choice(["sign_label", "signed"])

    heads = ERP_HEADS if erp else CLASSIC_HEADS
    st["heads"] = {k: rng.choice(v) for k, v in heads.items()}
    if not erp:   # one naming for all the per-row tax columns: "CGST Amt" / "SGST Amt", never mixed
        tax_head = rng.choice(["{} Amt", "{}", "{} Amt.", "{}\nAmount"])
        for tax in ("cgst", "sgst", "igst"):
            st["heads"][tax] = tax_head.format(tax.upper())
    # billing software prints fixed column widths, so numeric columns usually have slack and the
    # description column is narrower than "whatever is left" (inv03 wraps its descriptions)
    st["desc_frac"] = rng.uniform(0.18, 0.3) if erp else rng.uniform(0.3, 0.46)
    if not st["has_rupee"] and RUPEE in st["heads"]["amount"]:
        st["heads"]["amount"] = st["heads"]["amount"].replace(RUPEE, "Rs.")
    st["sn_align"] = rng.choice(["l", "c", "r"])
    st["sn_dot"] = rng.random() < 0.4
    st["cont_text"] = rng.choice(["Continued...", "continued on next page...", "Contd..."])
    st["page_no"] = rng.random() < 0.35
    return st


CLASSIC_HEADS = {
    "sn": ["S.N.", "S.No", "Sl.\nNo.", "#", "Sr."],
    "desc": ["Description of Goods", "Particulars", "Item Description", "Description of Goods/Services",
             "Product Name"],
    "hsn": ["HSN/SAC", "HSN Code", "HSN"],
    "taxp": ["Tax %", "GST %", "GST\nRate", "Tax\nRate"],
    "qty": ["Qty.", "Qty", "Quantity"],
    "unit": ["Unit", "UOM", "Unit"],
    "mrp": ["MRP", "M.R.P."],
    "rate": ["Price", "Rate", "Unit Price", "Rate"],
    "disc": ["Disc %", "Disc.", "Discount"],
    "taxable": ["Taxable\nValue", "Taxable Amt"],
    "amount": ["Amount(" + RUPEE + ")", "Amount", "Total", "Net Amount", "Value"],
}
ERP_HEADS = {
    "sn": ["No", "Sl", "S.No"],
    "desc": ["Description of Goods", "Item Description", "Product"],
    "hsn": ["HSN Code\n(GST)", "HSN/SAC", "HSN Code"],
    "qty": ["Qty", "Quantity"],
    "unit": ["UOM", "Unit"],
    "rate": ["Rate", "Unit Rate", "Price"],
    "total": ["Total", "Gross\nAmount", "Value"],
    "disc": ["Disc", "Discount"],
    "taxable": ["Taxable\nValue", "Taxable values", "Taxable\nAmount"],
    "cess": ["KFC", "Cess", "KFC"],
    "amount": ["Total\nAmount", "Net\nAmount", "Amount", "Line Total"],
}


def _compact(st, level):
    """Shrink a bill that does not fit: smaller table text first, then drop optional blocks."""
    tscale = [1, 0.92, 0.86, 0.78, 0.7, 0.63][level]
    bscale = [1, 1, 0.95, 0.92, 0.86, 0.8][level]
    st["tsize"] = st["tsize0"] * tscale
    st["body"] = st["body0"] * bscale
    st["compact"] = level >= 2
    st["gap"] = [1, 0.85, 0.7, 0.6, 0.5, 0.4][level]


# ---------------------------------------------------------------- item table

def _columns(spec, st):
    items, mode, h = spec["items"], spec["tax_mode"], st["heads"]
    cols = []

    def add(key, head, cells, align="r", group=None, optional=False):
        cols.append({"key": key, "head": head, "cells": cells, "align": align, "group": group,
                     "optional": optional})

    def money_cells(key, suffix=False):
        tail = " " + RUPEE if suffix else ""
        return [_money(it[key], st) + tail for it in items]

    add("sn", h["sn"], [f"{i + 1}." if st["sn_dot"] else str(i + 1) for i in range(len(items))], st["sn_align"])
    add("desc", h["desc"], [it["description"] for it in items], "l")
    add("hsn", h["hsn"], [it["hsn"] for it in items], "l")
    qty = [_qty(it["quantity"], st) for it in items]
    units = [it["unit"] for it in items]
    rates = [_rate(it["rate"], st) for it in items]

    if st["kind"] == "erp":
        sub_r, sub_a = st["sub_heads"]
        suffix = st["rupee_suffix"]
        add("qty", h["qty"], qty)
        add("unit", h["unit"], units, "l")
        add("rate", h["rate"], rates)
        if st["total_col"]:
            add("total", h["total"], money_cells("taxable"), optional=mode != "inclusive")
        if st["disc_col"]:
            add("disc", h["disc"], ["0.0"] * len(items), optional=True)
        if mode == "none":
            add("amount", h["amount"].replace("Total\n", ""), money_cells("amount"))
            return cols
        add("amount" if mode == "exclusive" else "taxable", h["taxable"], money_cells("taxable", suffix))
        for tax in ("cgst", "sgst"):
            add(tax + "_r", sub_r, [_pct(it["tax_percent"] / 2, st) for it in items], group=tax.upper())
            add(tax + "_a", sub_a, money_cells(tax, suffix), group=tax.upper())
        zero = "0.00" + (" " + RUPEE if suffix else "")
        if st["igst_col"]:
            add("igst_r", sub_r, [_pct(0, st)] * len(items), group="IGST", optional=True)
            add("igst_a", sub_a, [zero] * len(items), group="IGST", optional=True)
        if st["cess_col"]:
            add("cess_r", sub_r, [_pct(0, st)] * len(items), group=h["cess"], optional=True)
            add("cess_a", sub_a, [zero] * len(items), group=h["cess"], optional=True)
        if mode == "inclusive":
            add("amount", h["amount"], money_cells("amount"))
        return cols

    if mode != "none":
        add("taxp", h["taxp"], [_pct(it["tax_percent"], st) for it in items])
    add("qty", h["qty"], qty)
    if not st["unit_after_rate"]:
        add("unit", h["unit"], units, "l")
    if st["mrp_col"]:
        add("mrp", h["mrp"], [_money(it["mrp"], st) if it["mrp"] else "" for it in items], optional=True)
    add("rate", h["rate"], rates)
    if st["unit_after_rate"]:
        add("unit", "per", units, "l")
    if st["disc_col"]:
        add("disc", h["disc"], ["0.00"] * len(items), optional=True)
    if st["per_row_tax"]:
        if st["taxable_col"]:
            add("taxable", h["taxable"], money_cells("taxable"), optional=True)
        add("cgst", h["cgst"], money_cells("cgst"))
        add("sgst", h["sgst"], money_cells("sgst"))
        if st["igst_col"]:
            add("igst", h["igst"], [""] * len(items), optional=True)
    add("amount", h["amount"], money_cells("amount"))
    return cols


def _size_columns(cols, f, fh, width, pad, extra=None, fx=None):
    """Set c["w"] for every column; the description column takes what is left.
    extra: {key: [strings]} that must also fit in that column (totals under the table), in font fx."""
    for c in cols:
        if c["key"] != "desc" and "\n" not in c["head"] and " " in c["head"]:
            cw = max([f.getlength(v) for v in c["cells"]] + [0])
            if fh.getlength(c["head"]) > cw * 1.15 + 2 * pad:   # long header over a narrow column: two lines
                words = c["head"].split(" ")
                k = (len(words) + 1) // 2
                c["head"] = " ".join(words[:k]) + "\n" + " ".join(words[k:])
        heads = c["head"].split("\n")
        c["w"] = max([fh.getlength(t) for t in heads] + [f.getlength(v) for v in c["cells"]]) + 2 * pad
        if extra and c["key"] in extra:
            c["w"] = max([c["w"]] + [fx.getlength(v) + 3 * pad for v in extra[c["key"]]])
    groups = {}
    for c in cols:
        if c["group"]:
            groups.setdefault(c["group"], []).append(c)
    for name, members in groups.items():
        need = fh.getlength(name) + 2 * pad - sum(c["w"] for c in members)
        if need > 0:
            members[-1]["w"] += need
    desc = next(c for c in cols if c["key"] == "desc")
    desc["w"] = width - sum(c["w"] for c in cols if c is not desc)
    return desc["w"]


def _table(sh, spec, st, x0, x1, y, filler, extra=None):
    """Draw the item table from y. Returns dict(bbox, rows, colx, y_end, size)."""
    items = spec["items"]
    cols = _columns(spec, st)
    ts = st["tsize"]
    head_bold = st["kind"] == "classic" or st["label_bold"]
    while True:
        f = _font(st["tfamily"], ts)
        fh = _font(st["tfamily"], ts, head_bold)
        pad = max(4, int(ts * 0.32))
        desc_w = _size_columns(cols, f, fh, x1 - x0, pad, extra, _font(st["tfamily"], ts * 1.05, True))
        long_word = max([f.getlength(w) for it in items for w in it["description"].split()] + [0])
        min_desc = max((x1 - x0) * 0.2, long_word + 2 * pad)
        if desc_w >= min_desc:
            break
        optional = [c for c in cols if c["optional"]]
        if optional:
            drop = optional[-1]
            cols = [c for c in cols if c is not drop and not (drop["group"] and c["group"] == drop["group"])]
            continue
        if ts <= st["tsize"] * 0.6:
            break
        ts *= 0.93

    # hand the description column's excess to the other columns, as a fixed-width template would
    desc = next(c for c in cols if c["key"] == "desc")
    target = st["desc_frac"] * (x1 - x0)
    if st.get("fit_desc"):   # most classic templates leave room for the longest name
        target = max(target, max(f.getlength(it["description"]) for it in items) + 2 * pad if items else 0)
    target = max([target] + [fh.getlength(t) + 2 * pad for t in desc["head"].split("\n")])
    others = [c for c in cols if c["key"] not in ("desc", "sn")]
    spare = desc["w"] - max(target, min_desc)
    if spare > 0 and others:
        base = sum(c["w"] for c in others)
        grow = min(spare, base * 0.9)   # no column ends up more than ~1.9x its content
        for c in others:
            c["w"] += grow * c["w"] / base
        desc["w"] -= grow
    words = desc["head"].split()
    if "\n" not in desc["head"] and len(words) > 1 and fh.getlength(desc["head"]) + 2 * pad > desc["w"]:
        k = (len(words) + 1) // 2   # crowded table: "Description of / Goods/Services"
        desc["head"] = " ".join(words[:k]) + "\n" + " ".join(words[k:])

    lh = int(ts * 1.28)
    vp = int(ts * (0.32 if st["grid"] == "columns" else 0.42) * (0.8 if st["compact"] else 1))
    xs, x = [], x0
    for c in cols:
        xs.append((x, x + c["w"]))
        x += c["w"]
    xs[-1] = (xs[-1][0], x1)
    colx = {c["key"]: xs[i] for i, c in enumerate(cols)}
    has_group = any(c["group"] for c in cols)

    # header
    hp = int(ts * 0.35)
    plain_lines = max(len(c["head"].split("\n")) for c in cols if not c["group"])
    sub_lines = max([len(c["head"].split("\n")) for c in cols if c["group"]] + [0])
    gh = lh + 2 * hp if has_group else 0
    head_h = max(plain_lines * lh + 2 * hp, gh + sub_lines * lh + 2 * hp)
    y_head = y
    hfill = st["head_fill"]
    head_ink = st["ink"]
    if hfill:
        color = {"gray": (228, 228, 228), "dark": st["accent"]}.get(
            hfill, tuple(int(p * 0.85 + a * 0.15) for p, a in zip(st["paper_rgb"], st["accent"])))
        sh.d.rectangle((x0, y, x1, y + head_h), fill=color)
        if hfill == "dark":
            head_ink = st["paper_rgb"]

    def head_text(c, cx0, cx1, top, height):
        lines = c["head"].split("\n")
        ty = top + (height - len(lines) * lh) / 2 + ts * 0.1
        for i, t in enumerate(lines):
            if c["key"] == "desc" and st["kind"] == "classic":
                sh.text(cx0 + pad, ty + i * lh, t, ts, font=fh, fill=head_ink)
            else:
                sh.text((cx0 + cx1) / 2, ty + i * lh, t, ts, font=fh, fill=head_ink, anchor="ma")

    done_groups = set()
    for i, c in enumerate(cols):
        cx0, cx1 = xs[i]
        if not c["group"]:
            head_text(c, cx0, cx1, y, head_h)
            continue
        head_text(c, cx0, cx1, y + gh, head_h - gh)
        if c["group"] not in done_groups:
            done_groups.add(c["group"])
            members = [j for j, m in enumerate(cols) if m["group"] == c["group"]]
            gx0, gx1 = xs[members[0]][0], xs[members[-1]][1]
            sh.text((gx0 + gx1) / 2, y + hp + ts * 0.1, c["group"], ts, font=fh, fill=head_ink, anchor="ma")
            if st["grid"] != "open":
                sh.hline(gx0, gx1, y + gh)
    y += head_h
    light = tuple(int(p * 0.55 + q * 0.45) for p, q in zip(st["paper_rgb"], st["line"]))
    if st["grid"] != "open":
        sh.hline(x0, x1, y)

    # rows
    rows = []
    for r, it in enumerate(items):
        desc_lines = _wrap(it["description"], f, colx["desc"][1] - colx["desc"][0] - 2 * pad)
        rh = len(desc_lines) * lh + 2 * vp
        ty = y + vp - ts * 0.04   # capitals centred in the row; descenders stay above the rule
        boxes = {}
        for i, c in enumerate(cols):
            cx0, cx1 = xs[i]
            if c["key"] == "desc":
                b = None
                for k, line in enumerate(desc_lines):
                    b = _union(b, sh.text(cx0 + pad, ty + k * lh, line, ts, font=f))
                boxes["desc"] = b
                continue
            val = c["cells"][r]
            if c["align"] == "l":
                b = sh.text(cx0 + pad, ty, val, ts, font=f)
            elif c["align"] == "c":
                b = sh.text((cx0 + cx1) / 2, ty, val, ts, font=f, anchor="ma")
            else:
                b = sh.text(cx1 - pad, ty, val, ts, font=f, anchor="ra")
            boxes[c["key"]] = b
        rows.append({"y0": int(y), "y1": int(y + rh), "desc_bbox": _ibox(boxes["desc"]),
                     "qty_bbox": _ibox(boxes["qty"]), "amount_bbox": _ibox(boxes["amount"])})
        y += rh
        if st["grid"] == "grid":
            sh.hline(x0, x1, y)
        elif st["grid"] == "open" and r < len(items) - 1:
            sh.hline(x0, x1, y, width=1, fill=light)
    if spec["continued"]:
        y += vp
        sh.text(colx["desc"][0] + pad, y, st["cont_text"], ts, font=fh)
        y += lh + vp
    if st["grid"] == "grid" and filler < lh * 1.5:
        filler = 0   # a sliver of blank space would print as a double rule under the last row
    y += filler
    sh.hline(x0, x1, y)

    # column rules
    if st["grid"] != "open":
        for i, c in enumerate(cols[1:], 1):
            top = y_head
            if c["group"] and cols[i - 1]["group"] == c["group"]:
                top = y_head + gh
            sh.vline(xs[i][0], top, y)
        sh.frame(x0, y_head, x1, y)
    else:
        sh.hline(x0, x1, y_head)
    return {"bbox": (int(x0), int(y_head), int(x1), int(y)), "rows": rows, "colx": colx, "y_end": y,
            "size": ts, "font": f, "pad": pad, "lh": lh}


def _ibox(b):
    return tuple(int(round(v)) for v in b) if b else None


# ---------------------------------------------------------------- letterheads

def _head_center(sh, spec, st, x0, x1, y, title):
    """inv07 style: GSTIN top left, copy label top right, centred title, name, address, contact."""
    sup, b = spec["supplier"], st["body"]
    lh = int(b * 1.35)
    boxes = []
    if sup["gstin"] or st["copy_label"]:
        if sup["gstin"]:
            boxes.append(sh.text(x0, y, f"GSTIN : {sup['gstin']}", b * 1.05, bold=True))
        if st["copy_label"]:
            sh.text(x1, y, st["copy_label"], b * 0.85, anchor="ra")
        y += int(lh * 1.15)
    cx = (x0 + x1) / 2
    if title:
        tb = sh.text(cx, y, title, b * 1.15, bold=True, anchor="ma")
        if st["title_underline"]:
            sh.hline(tb[0], tb[2], tb[3] + 3, width=2, fill=st["ink"])
        y += int(b * 1.65)
    ns = st["name_size"]
    while ns > b and sh.w(sup["name"], ns, True, st["nfamily"]) > (x1 - x0) * 0.86:
        ns *= 0.95
    nb = sh.text(cx, y, sup["name"], ns, bold=True, fill=st["accent"], anchor="ma", family=st["nfamily"])
    boxes.append(nb)
    y = nb[3] + int(b * 0.45)
    text_boxes = [nb]
    lines = []
    for line in sup["address_lines"]:
        lines += _wrap(line, sh.font(b), (x1 - x0) * 0.8)
    for line in lines:
        text_boxes.append(sh.text(cx, y, line, b, anchor="ma"))
        y += lh
    contact = f"Tel. : {sup['phone']}" + (f"   email : {sup['email']}" if sup["email"] else "")
    text_boxes.append(sh.text(cx, y, contact, b * 0.92, bold=True, anchor="ma"))
    y += lh
    if sup["fssai"]:
        text_boxes.append(sh.text(cx, y, f"FSSAI Lic. No. : {sup['fssai']}", b * 0.85, anchor="ma"))
        y += lh
    boxes += text_boxes
    if st["logo"]:
        r = st["logo_r"]
        left_edge = min(t[0] for t in text_boxes)
        if left_edge - x0 > 2 * r + 20:
            boxes.append(_logo(sh, x0 + r + 6, (nb[1] + y) / 2, r, st))
    # blank paper right of the centred block: where "Bil 618" was written on inv07
    st["_head_free"] = (max(max(t[2] for t in text_boxes) + 30, x0 + (x1 - x0) * 0.62), nb[1], x1 - 12, y)
    return y, _union(*boxes)


def _head_left(sh, spec, st, x0, x1, y, title):
    """Logo at left, name and address beside it; title, copy label and GSTIN on the right."""
    sup, b = spec["supplier"], st["body"]
    lh = int(b * 1.35)
    right = []
    if title:
        right.append((title, b * 1.3, True))
    if st["copy_label"] and st["kind"] == "classic":   # erp prints it above the invoice box instead
        right.append((st["copy_label"], b * 0.82, False))
    if sup["gstin"]:
        right.append((f"GSTIN : {sup['gstin']}", b, True))
    if sup["fssai"]:
        right.append((f"FSSAI : {sup['fssai']}", b * 0.88, False))
    if st["kind"] == "erp":
        right.append((f"State : {sup['state']}, Code : {sup['state_code']}", b * 0.88, False))
    right_w = max([sh.w(t, s, bo) for t, s, bo in right] + [0])
    r = st["logo_r"]
    tx = x0 + (2 * r + int(b) if st["logo"] else 0)
    avail = x1 - right_w - int(b * 1.5) - tx
    boxes = []
    ns = st["name_size"] * 0.85
    while ns > b and sh.w(sup["name"], ns, True, st["nfamily"]) > avail:
        ns *= 0.95
    lines = [(sup["name"], ns, True, st["accent"], st["nfamily"])]
    for line in sup["address_lines"]:
        lines += [(t, b, False, None, None) for t in _wrap(line, sh.font(b), avail)]
    for t in [f"Ph : {sup['phone']}"] + ([f"Email : {sup['email']}"] if sup["email"] else []):
        lines.append((t, b * 0.92, False, None, None))
    y0 = ty = y
    for t, s, bo, fill, fam in lines:
        bb = sh.text(tx, ty, t, s, bold=bo, fill=fill, family=fam)
        boxes.append(bb)
        ty = bb[3] + int(s * 0.38) if bo else ty + int(s * 1.35)
    text_right = max(bb[2] for bb in boxes)
    ry = y
    for t, s, bo in right:
        boxes.append(sh.text(x1, ry, t, s, bold=bo, anchor="ra"))
        ry += int(s * 1.45)
    y = max(ty, ry)
    if st["logo"]:
        boxes.append(_logo(sh, x0 + r, (y0 + y) / 2, r, st))
    st["_head_free"] = (text_right + 30, y0, x1 - right_w - 30, y)   # blank middle of the letterhead
    return y + int(lh * 0.2), _union(*boxes)


def _head_line(sh, spec, st, x0, x1, y):
    """inv03 style: small logo + wordmark centred, then name and address run together on one line
    and a bold CIN / PAN / FSSAI line."""
    sup, b = spec["supplier"], st["body"]
    cx = (x0 + x1) / 2
    boxes = []
    if st["logo"]:
        r = int(st["logo_r"] * 0.55)
        boxes.append(_logo(sh, cx, y + r, r, st))
        y += 2 * r + 4
        words = sup["name"].split()
        # wordmark: the first real word ("ST. JUDE", "R K", not a bare "ST" or "R")
        word = " ".join(words[:2]) if len(words) > 1 and len(words[0].strip(".,")) <= 2 else words[0].strip(".,")
        bb = sh.text(cx, y, word, b * 0.95, bold=True, fill=st["accent"], anchor="ma")
        boxes.append(bb)
        y = bb[3] + int(b * 0.3)
    size = b * 1.1
    lh = int(size * 1.3)
    full = ", ".join([sup["name"]] + sup["address_lines"])
    for line in _wrap(full, sh.font(size), x1 - x0):
        boxes.append(sh.text(cx, y, line, size, anchor="ma"))
        y += lh
    parts = []
    if st["cin"]:
        parts.append(f"CIN: {st['cin']}")
    if sup["gstin"]:
        parts.append(f"PAN: {sup['gstin'][2:12]}")
    if sup["fssai"]:
        parts.append(f"FSSAI License Number: {sup['fssai']}")
    parts2 = [f"Ph: {sup['phone']}"] + ([f"Email: {sup['email']}"] if sup["email"] else [])
    for group in (parts, parts2):
        if group:
            for line in _wrap(", ".join(group), sh.font(size, True), x1 - x0):
                boxes.append(sh.text(cx, y, line, size, bold=True, anchor="ma"))
                y += lh
    st["_head_free"] = None
    return y, _union(*boxes)


# ---------------------------------------------------------------- erp family

def _erp(sh, spec, st, layout, free):
    x0, x1 = st["ml"], st["W"] - st["mr"]
    b, g = st["body"], st["gap"]
    pad = int(b * 0.45)
    lh = int(b * 1.32)
    sup, buyer = spec["supplier"], spec["buyer"]
    date = spec["date_printed"]
    y = st["top"]
    if st["head"] == "line":
        y, hb = _head_line(sh, spec, st, x0, x1, y)
    else:
        y, hb = _head_left(sh, spec, st, x0, x1, y, None)
    layout["header_bbox"] = _ibox(hb)
    gap_top = y
    y += int(st["notes_gap"] * g)
    if st["copy_label"]:
        sh.text(x1, y, st["copy_label"], b * 0.88, anchor="ra")
        y += lh
    notes = [(x0 + (x1 - x0) * 0.35, gap_top + 6, x1 - 10, y - lh - 4)] if st["copy_label"] else \
        [(x0 + (x1 - x0) * 0.35, gap_top + 6, x1 - 10, y - 4)]
    box_top = y

    # title + invoice fields
    y += pad
    sh.text((x0 + x1) / 2, y, st["title"], b * 1.75, anchor="ma")
    y += int(b * 2.2)
    mid = x0 + (x1 - x0) * 0.5
    left = []
    if sup["gstin"]:
        left.append(("Gstin Number", sup["gstin"], None))
    left.append(("Tax Is Payable On Reverse Charge", "No", None))
    left.append((st["inv_label"], spec["invoice_number_printed"], "inv"))
    if st["delivery_date"]:
        left.append(("Delivery Invoice Date", date, None))
    left.append((st["date_label"], date, "date"))
    if st["show_retailer"]:
        left.append(("Name of Retailer", st["retailer"], None))
    right = [("Transportation Mode", st["transport"], None),
             ("Vehicle No", st["vehicle"] or st["transport"].upper(), None)]
    if st["einvoice"]:
        right.append(("E-Invoice ACK Number", st["ack"], None))
    right += [("Date of Supply", date, None), ("Place of Supply", st["place_of_supply"], None)]
    fy = y
    yl, boxes = sh.fields(x0 + pad, fy, mid - x0 - 2 * pad, left, b)
    yr, _ = sh.fields(mid + pad, fy, x1 - mid - 2 * pad, right, b)
    layout["invoice_number_bbox"] = _ibox(boxes["inv"])
    layout["date_bbox"] = _ibox(boxes["date"])
    y = max(yl, yr) + int(pad * 0.5)
    sh.hline(x0, x1, y)

    # receiver / consignee
    y += int(pad * 0.4)
    addr = ", ".join(buyer["address_lines"])
    rec = [("Name", buyer["display"], None), ("Address", addr, None), ("State", "KERALA", None),
           ("GSTIN Number", buyer["gstin"], None), ("Mobile", st["buyer_mobile"], None)]
    show_cons = st["consignee"] and not st["compact"]
    half = mid if show_cons else x1
    sh.text((x0 + half) / 2, y, "Details of Receiver" + (" (Billed to)" if show_cons else ""), b, bold=True,
            anchor="ma")
    if show_cons:
        sh.text((mid + x1) / 2, y, "Details of Consignee (Shipped to)", b, bold=True, anchor="ma")
    y += int(b * 1.5)
    sh.hline(x0, half, y, width=1)
    yl, _ = sh.fields(x0 + pad, y + 4, half - x0 - 2 * pad, rec, b)
    yr = y
    if show_cons:
        cons = [("Name", buyer["name"], None), ("Address", addr, None), ("State", "KERALA", None),
                ("GSTIN Number", buyer["gstin"], None)]
        yr, _ = sh.fields(mid + pad, y + 4, x1 - mid - 2 * pad, cons, b)
        sh.vline(mid, fy - 2, max(yl, yr) + 2)
    else:
        sh.vline(mid, fy - 2, y - lh)
    y = max(yl, yr) + 2

    # items
    t = _table(sh, spec, st, x0, x1, y, 0)
    layout["table_bbox"], layout["rows"] = t["bbox"], t["rows"]
    y = t["y_end"]

    if spec["continued"]:
        layout["total_bbox"] = None
    else:
        y = _erp_totals(sh, spec, st, layout, x0, x1, y)

    # certification and signatory
    y += int(pad * 0.5)
    cert_top = y
    split = x0 + (x1 - x0) * 0.52
    sh.text((x0 + split) / 2, y, "Certified that the Particulars given above are true and correct", b * 0.95,
            bold=True, anchor="ma")
    ly = y + lh
    if st["terms"] and not st["compact"]:
        sh.text((x0 + split) / 2, ly, "YOUR TERM and CONDITION OF SALE", b * 0.95, bold=True, anchor="ma")
        ly += lh
        for term in st["terms_list"][:2]:
            for line in _wrap(term, sh.font(b * 0.85), split - x0 - 2 * pad):
                sh.text(x0 + pad, ly, line, b * 0.85)
                ly += int(b * 1.15)
    ry = y
    rh = int(b * 1.6)   # ruled rows leave room for descenders above the next rule
    if st["einvoice"]:
        sh.text((split + x1) / 2, ry, "Electronic Reference Number :", b, bold=True, anchor="ma")
        ry += lh
    sh.text((split + x1) / 2, ry, f"For {sup['name']}", b, bold=True, anchor="ma")
    ry += rh
    sh.hline(split, x1, ry, width=1)
    sign_space = min(int(free * 0.3), int(st["dpi"] * 0.8))
    for label in ("Signature:", None, "Name:Dispatch", "Designation:"):
        if label:
            sh.text(split + pad, ry + b * 0.08, label, b * 0.9)
        else:
            sh.text((split + x1) / 2 + b * 2, ry + b * 0.08, "Authorised Signatory", b, bold=True, anchor="ma")
        ry += rh + (sign_space if label == "Signature:" else 0)
        sh.hline(split, x1, ry, width=1)
    sh.vline(split, cert_top - int(pad * 0.5), ry)
    y = max(ly, ry) + 2
    sh.hline(x0, x1, y)
    sh.vline(x0, box_top, y)
    sh.vline(x1, box_top, y)
    sh.hline(x0, x1, box_top)
    box_bottom = y

    # outside the box: declaration, QR, IRN
    y += int(lh * 0.8 * g)
    if st["declaration"] and not st["compact"]:
        for line in _wrap("Declaration : " + st["decl"], sh.font(b * 0.92), x1 - x0):
            sh.text(x0, y, line, b * 0.92)
            y += int(b * 1.25)
        y += int(lh * 0.6 * g)
    if st["einvoice"]:
        qb = _draw_qr(sh, x0, y, st["qr_in"] * st["dpi"] * (0.8 if st["compact"] else 1), st["qr"])
        y = qb[3] + int(b * 0.5)
        sh.text(x0, y, f"IRN : {st['irn']}", b * 1.02)
        y += lh
    y = _page_footer(sh, spec, st, x0, x1, y)
    notes.append((x0 + (x1 - x0) * 0.45, box_bottom + 10, x1 - 10, box_bottom + 10 + int(b * 5)))
    if st["_head_free"]:
        notes.insert(1, st["_head_free"])
    layout["_notes"] = notes
    return y


def _erp_totals(sh, spec, st, layout, x0, x1, y):
    """Amount in words on the left, 'Add : CGST' stack on the right (inv03)."""
    tot, mode, b = spec["totals"], spec["tax_mode"], st["body"]
    pad = int(b * 0.45)
    lh = int(b * 1.32)
    split = x0 + (x1 - x0) * 0.52
    suffix = " " + RUPEE if st["rupee_suffix"] else ""
    money = lambda v: _money(v, st) + suffix  # noqa: E731
    rows = [("Total" if mode != "inclusive" else "Total Taxable Value", money(tot["subtotal"]), None)]
    if mode != "none":
        rows += [("Add : CGST", money(tot["cgst"]), None), ("Add : SGST", money(tot["sgst"]), None),
                 ("Add : IGST", money(tot["igst"]), None)]
        if st["extra_tax_rows"]:
            rows += [("Tax Amount : GST", money(round(tot["cgst"] + tot["sgst"], 2)), None),
                     ("Tax Amount : KFC", money(tot["cess"]), None), ("TCS Amount : TCS", money(0), None)]
    if tot["round_off"]:
        rows.append(("Round Off", _num(tot["round_off"], 2), None))
    gt = _grand(tot["grand_total"], st)
    rows.append(("Total Amount After Tax" if mode != "none" else "Net Amount", gt, "grand"))
    fb = sh.font(b, True)
    fv = sh.font(b)
    vw = max((fb if key else fv).getlength(v) for _, v, key in rows)
    vx = x1 - pad
    lx = vx - vw - b * 0.6
    rh = int(b * 1.55)   # each row ruled off below, with room for descenders
    ry = y + 1
    for label, value, key in rows:
        lb = sh.text(lx, ry - b * 0.04, label, b, font=fb, anchor="ra")
        vb = sh.text(vx, ry - b * 0.04, value, b, font=fb if key else fv, anchor="ra")
        if key == "grand":
            layout["total_bbox"] = _ibox(_union(lb, vb))
        ry += rh
        sh.hline(split, x1, ry - 1, width=1)
    # words on the left
    wy = y + 3
    words = st["words_label"] + spec["amount_in_words"]
    for line in _wrap(words, sh.font(b), split - x0 - 2 * pad):
        sh.text(x0 + pad, wy, line, b)
        wy += lh
    sh.text(x0 + (split - x0) * 0.4, wy, gt, b, anchor="ma")
    wy += lh
    y_end = max(ry, wy) + 2
    sh.vline(split, y, y_end)
    y = y_end
    sh.hline(x0, x1, y)
    if st["reverse_row"]:
        sh.text(split, y + b * 0.06, "Amount of Tax Subject to Reverse Charge", b, bold=True, anchor="ra")
        sh.text(split + pad, y + b * 0.06, money(0), b)
        y += int(b * 1.6)
        sh.hline(x0, x1, y)
    return y


# ---------------------------------------------------------------- classic family

def _classic(sh, spec, st, layout, free):
    x0, x1 = st["ml"], st["W"] - st["mr"]
    b, g = st["body"], st["gap"]
    pad = int(b * 0.5)
    lh = int(b * 1.35)
    y_top = st["top"]
    y = y_top + pad
    if st["head"] == "center":
        y, hb = _head_center(sh, spec, st, x0 + pad, x1 - pad, y, st["title"])
    else:
        y, hb = _head_left(sh, spec, st, x0 + pad, x1 - pad, y, st["title"])
    layout["header_bbox"] = _ibox(hb)
    notes = [st["_head_free"]] if st["_head_free"] else []
    y += int(pad * 0.6)
    box_top = y_top if st["head_in_box"] else y
    if not st["head_in_box"]:
        y += int(pad * 0.4)
    sh.hline(x0, x1, y)

    # invoice fields and the buyer
    split = x0 + (x1 - x0) * st["meta_split"]
    date = spec["date_printed"]
    if st["meta"] == "grid":
        y = _meta_grid(sh, spec, st, layout, x0, x1, split, y)
    else:
        y = _meta_side(sh, spec, st, layout, x0, x1, split, y)

    if st["einvoice"]:
        s = b * 0.9
        irn = f"IRN : {st['irn']}"
        ack = f"Ack.No. : {st['ack']}      Ack. Date : {date}"
        iy = y + int(pad * 0.6)
        if sh.w(irn + "      " + ack, s) < x1 - x0 - 2 * pad:
            sh.text(x0 + pad, iy, irn, s, bold=st["label_bold"])
            sh.text(x1 - pad, iy, ack, s, bold=st["label_bold"], anchor="ra")
            iy += int(s * 1.35)
        else:
            sh.text(x0 + pad, iy, irn, s, bold=st["label_bold"])
            sh.text(x0 + pad, iy + int(s * 1.35), ack, s, bold=st["label_bold"])
            iy += int(s * 2.7)
        y = iy + int(pad * 0.4)
        sh.hline(x0, x1, y)
    y += int(pad * 0.8 * g)

    # items
    filler = int(free * st["fill_frac"])
    extra = None
    if not spec["continued"]:
        extra = {"amount": [v for _, v, _ in _classic_total_rows(spec, st)]}
        if st["total_qty"]:
            extra["qty"] = [_total_qty(spec, st)]
    t = _table(sh, spec, st, x0, x1, y, filler, extra)
    layout["table_bbox"], layout["rows"] = t["bbox"], t["rows"]
    if t["rows"]:   # blank table space under the last row: used only when nothing better is free
        dx0, dx1 = t["colx"]["desc"]
        layout["_notes_late"] = [(dx0 + 10, t["rows"][-1]["y1"] + 12, dx1 - 10, t["y_end"] - 12)]
    y = t["y_end"]

    if spec["continued"]:
        layout["total_bbox"] = None
    else:
        y = _classic_totals(sh, spec, st, layout, t, x0, x1, y)
        if st["summary"]:
            y = _tax_summary(sh, spec, st, x0, x1, y)
        words = st["words_label"] + spec["amount_in_words"]
        y += int(pad * 0.6)
        for line in _wrap(words, sh.font(b * 1.05, True), x1 - x0 - 2 * pad):
            sh.text(x0 + pad, y, line, b * 1.05, bold=True)
            y += int(b * 1.45)
        y += int(pad * 0.4)
        sh.hline(x0, x1, y)

    if st["bank"] and not st["compact"]:
        y += int(pad * 0.6)
        lb = sh.text(x0 + pad, y + int(b * 0.3), "Bank Details :", b * 1.05, bold=True)
        by = y
        for line in st["bank_lines"]:
            sh.text(lb[2] + b, by, line, b)
            by += lh
        y = by + int(pad * 0.3)
        sh.hline(x0, x1, y)

    y = _classic_footer(sh, spec, st, x0, x1, y)
    sh.frame(x0, box_top, x1, y)
    y = _page_footer(sh, spec, st, x0, x1, y)
    layout["_notes"] = notes
    return y


def _party(sh, st, label, buyer, cx0, cx1, y):
    """Billed to / Shipped to block: label, name, address, GSTIN and state. Returns y below it."""
    b = st["body"]
    pad = int(b * 0.5)
    lh = int(b * 1.35)
    w = cx1 - cx0 - 2 * pad
    sh.text(cx0 + pad, y, label, b, bold=True)
    y += lh
    for part in _wrap(buyer["display"], sh.font(b, st["label_bold"]), w):
        sh.text(cx0 + pad, y, part, b, bold=st["label_bold"])
        y += lh
    for line in buyer["address_lines"]:
        for part in _wrap(line, sh.font(b), w):
            sh.text(cx0 + pad, y, part, b)
            y += lh
    y += int(lh * 0.3)
    y, _ = sh.fields(cx0 + pad, y, w, [("GSTIN / UIN", buyer["gstin"], None), ("State", "Kerala, Code : 32", None)],
                     b, aligned=True)
    return y


def _meta_grid(sh, spec, st, layout, x0, x1, split, y):
    """inv07: invoice | transport fields in two columns, then Billed to | Shipped to."""
    b = st["body"]
    pad = int(b * 0.5)
    left = [(st["inv_label"], spec["invoice_number_printed"], "inv"), (st["date_label"], spec["date_printed"], "date"),
            ("Place of Supply", st["place_of_supply"], None), ("Reverse Charge", "N", None)]
    if not st["compact"]:
        left.append(("GR/RR No.", "", None))
    right = [("Transport", st["transport"], None), ("Vehicle No.", st["vehicle"], None),
             ("Station", st["station"], None), ("E-Way Bill No.", st["ewb"], None)]
    if not st["compact"]:
        right.append(("P.O No.", st["po"], None))
    fy = y + int(pad * 0.7)
    yl, boxes = sh.fields(x0 + pad, fy, split - x0 - 2 * pad, left, b, aligned=True)
    yr, _ = sh.fields(split + pad, fy, x1 - split - 2 * pad, right, b, aligned=True)
    layout["invoice_number_bbox"] = _ibox(boxes["inv"])
    layout["date_bbox"] = _ibox(boxes["date"])
    y2 = max(yl, yr) + int(pad * 0.5)
    sh.vline(split, y, y2)
    y = y2
    sh.hline(x0, x1, y)

    buyer = spec["buyer"]
    show_cons = st["consignee"] and not st["compact"]
    py = y + int(pad * 0.7)
    ends = [_party(sh, st, st["bill_label"], buyer, x0, split if show_cons else x1, py)]
    if show_cons:
        ends.append(_party(sh, st, st["ship_label"], buyer, split, x1, py))
    y2 = max(ends) + int(pad * 0.4)
    if show_cons:
        sh.vline(split, y, y2)
    sh.hline(x0, x1, y2)
    return y2


def _meta_side(sh, spec, st, layout, x0, x1, split, y):
    """Buyer (and consignee) on the left; on the right either "Label : value" invoice fields or
    Tally's grid of cells with a small label over each value."""
    b = st["body"]
    pad = int(b * 0.5)
    buyer, date, inv = spec["buyer"], spec["date_printed"], spec["invoice_number_printed"]
    ly = _party(sh, st, st["bill_label"], buyer, x0, split, y + int(pad * 0.7)) + int(pad * 0.4)
    if st["consignee"] and not st["compact"]:
        sh.hline(x0, split, ly)
        ly = _party(sh, st, st["ship_label"], buyer, x0, split, ly + int(pad * 0.7)) + int(pad * 0.4)
    if st["meta"] == "buyer_left":
        rows = [(st["inv_label"], inv, "inv"), (st["date_label"], date, "date"),
                ("Place of Supply", st["place_of_supply"], None), ("Reverse Charge", "N", None),
                ("Transport", st["transport"], None), ("Vehicle No.", st["vehicle"], None)]
        if not st["compact"]:
            rows += [("E-Way Bill No.", st["ewb"], None), ("P.O No.", st["po"], None)]
        ry, boxes = sh.fields(split + pad, y + int(pad * 0.7), x1 - split - 2 * pad, rows, b, aligned=True)
        ry += int(pad * 0.5)
        y2 = max(ly, ry)
    else:
        rows = [((st["inv_label"], inv, "inv"), ("Dated", date, "date")),
                (("Delivery Note", "", None), ("Mode/Terms of Payment", st["pay_terms"], None)),
                (("Buyer's Order No.", st["po"], None), ("Dated", "", None)),
                (("Dispatch Doc No.", "", None), ("Delivery Note Date", "", None)),
                (("Dispatched through", st["transport"], None), ("Destination", st["station"], None)),
                (("Vehicle No.", st["vehicle"], None), ("E-Way Bill No.", st["ewb"], None))]
        if st["compact"]:
            rows = rows[:1] + rows[4:]
        mid = (split + x1) / 2
        ry, boxes = y, {}
        for i, row in enumerate(rows):
            top = ry
            for (label, value, key), (cx0, cx1) in zip(row, ((split, mid), (mid, x1))):
                sh.text(cx0 + pad, top + pad * 0.5, label, b * 0.82)
                vb = sh.text(cx0 + pad, top + pad * 0.5 + b * 1.15, value, b, bold=True)
                if key:
                    boxes[key] = vb
            ry = top + int(pad + b * 1.15 + b * 1.4)
            if i < len(rows) - 1:
                sh.hline(split, x1, ry)
        y2 = max(ly, ry)
        sh.vline(mid, y, y2)
    layout["invoice_number_bbox"] = _ibox(boxes["inv"])
    layout["date_bbox"] = _ibox(boxes["date"])
    sh.vline(split, y, y2)
    sh.hline(x0, x1, y2)
    return y2


def _classic_total_rows(spec, st):
    """(label, value, key) rows of the totals band; key "grand" marks the grand total."""
    tot, mode = spec["totals"], spec["tax_mode"]
    rows = []
    if mode == "exclusive":
        rows.append(("Sub Total", _money(tot["subtotal"], st), None))
        for tax in ("CGST", "SGST"):
            rows.append((st["tax_label"].format(tax), _money(tot[tax.lower()], st), None))
    elif mode == "inclusive":
        total = round(sum(it["amount"] for it in spec["items"]) + 1e-9, 2)
        rows.append(("Total", _money(total, st), None))
    else:
        rows.append(("Total", _money(tot["subtotal"], st), None))
    ro = tot["round_off"]
    if ro:
        if st["round_style"] == "sign_label":
            label = "Less : Rounded Off (-)" if ro < 0 else "Add : Rounded Off (+)"
            rows.append((label, _num(abs(ro), 2), None))
        else:
            rows.append(("Round Off", ("+" if ro > 0 else "") + _num(ro, 2), None))
    gt = _grand(tot["grand_total"], st)
    if st["gt"] == "rupee":
        gt = RUPEE + " " + gt
    elif st["gt"] == "rs":
        gt = "Rs. " + gt
    rows.append(("Grand Total", gt, "grand"))
    return rows


def _total_qty(spec, st):
    return _qty(round(sum(it["quantity"] for it in spec["items"]), 3), st)


def _classic_totals(sh, spec, st, layout, t, x0, x1, y):
    """Totals band under the table: labels right-aligned before the amount column (inv07)."""
    ts, f, pad = t["size"], t["font"], t["pad"]
    fb = _font(st["tfamily"], ts * 1.05, True)
    ax0, ax1 = t["colx"]["amount"]
    rows = _classic_total_rows(spec, st)
    rh = int(ts * 1.75)
    open_grid = st["grid"] == "open"
    top = y
    for label, value, key in rows:
        font = fb if key else f
        ty = y + (rh - ts * 1.2) / 2
        if key and st["total_qty"] and "qty" in t["colx"] and not open_grid:
            sh.hline(x0, x1, y)
            qx0, qx1 = t["colx"]["qty"]
            sh.text(qx1 - pad, ty, _total_qty(spec, st), ts, font=font, anchor="ra")
            lb = sh.text(qx0 - pad * 2, ty, label, ts, font=font, anchor="ra")
        else:
            if key and not open_grid:
                sh.hline(x0, x1, y)
            lb = sh.text(ax0 - pad * 2, ty, label, ts, font=font, anchor="ra")
        vb = sh.text(ax1 - pad, ty, value, ts, font=font, anchor="ra")
        if key:
            layout["total_bbox"] = _ibox(_union(lb, vb))
        y += rh
    if not open_grid:
        sh.vline(ax0, top, y)
    sh.hline(x0, x1, y)
    return y


def _tax_summary(sh, spec, st, x0, x1, y):
    """Rate-wise (inv07) or HSN-wise breakdown of the tax. The total row repeats the spec totals."""
    items, tot = spec["items"], spec["totals"]
    b = st["body"] * 0.92
    pad = int(b * 0.45)
    lh = int(b * 1.35)
    groups = {}
    for it in items:
        key = (it["hsn"], it["tax_percent"]) if st["summary_kind"] == "hsn" else it["tax_percent"]
        groups.setdefault(key, []).append(it)

    def sums(its):
        tx = round(sum(i["taxable"] for i in its) + 1e-9, 2)
        c = round(sum(i["cgst"] for i in its) + 1e-9, 2)
        s = round(sum(i["sgst"] for i in its) + 1e-9, 2)
        return tx, c, s

    if st["summary_kind"] == "hsn":
        head = ["HSN/SAC", "Taxable Value", "CGST Rate", "CGST Amount", "SGST Rate", "SGST Amount", "Total Tax"]
        body = []
        for (hsn, p), its in groups.items():
            tx, c, s = sums(its)
            body.append([hsn, _money(tx, st), _pct(p / 2, st), _money(c, st), _pct(p / 2, st), _money(s, st),
                         _money(round(c + s, 2), st)])
        body.append(["Total", _money(tot["subtotal"], st), "", _money(tot["cgst"], st), "",
                     _money(tot["sgst"], st), _money(round(tot["cgst"] + tot["sgst"], 2), st)])
        width = x1 - x0
    else:
        head = ["Tax Rate", "Taxable Amt.", "CGST Amt.", "SGST Amt.", "Total Tax"]
        body = []
        for p in sorted(groups):
            tx, c, s = sums(groups[p])
            body.append([_pct(p, st), _money(tx, st), _money(c, st), _money(s, st), _money(round(c + s, 2), st)])
        if len(body) > 1:
            body.append(["Total", _money(tot["subtotal"], st), _money(tot["cgst"], st), _money(tot["sgst"], st),
                         _money(round(tot["cgst"] + tot["sgst"], 2), st)])
        width = (x1 - x0) * 0.62
    fh = sh.font(b, True)
    f = sh.font(b)
    ws = [max([fh.getlength(head[i])] + [f.getlength(r[i]) for r in body]) + 2 * pad for i in range(len(head))]
    scale = (width - 2 * pad) / sum(ws)
    if st["summary_kind"] == "rate":
        scale = min(1.25, scale)
    ws = [w * scale for w in ws]
    y += pad
    x = x0 + pad
    for i, h in enumerate(head):
        hb = sh.text(x + ws[i] - pad, y, h, b, font=fh, anchor="ra")
        sh.hline(hb[0], hb[2], hb[3] + 2, width=1, fill=st["ink"])
        x += ws[i]
    y += lh + 3
    for r, row in enumerate(body):
        x = x0 + pad
        bold = row[0] == "Total"
        for i, v in enumerate(row):
            if i == 0:
                sh.text(x + pad, y, v, b, font=fh if bold else f)
            else:
                sh.text(x + ws[i] - pad, y, v, b, font=fh if bold else f, anchor="ra")
            x += ws[i]
        y += lh
    return y


def _classic_footer(sh, spec, st, x0, x1, y):
    """Terms & Conditions | E-Invoice QR Code | receiver's signature + 'for SUPPLIER' (inv07)."""
    b = st["body"]
    pad = int(b * 0.5)
    lh = int(b * 1.3)
    s = b * 0.9
    qr_size = st["qr_in"] * st["dpi"] * (0.75 if st["compact"] else 1)
    if st["einvoice"]:
        widths = [0.38, 0.27, 0.35]
    else:
        widths = [0.55, 0, 0.45]
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + (x1 - x0) * w)
    top = y
    # terms
    ty = y + pad
    if st["terms"]:
        tb = sh.text(xs[0] + pad, ty, "Terms & Conditions", s, bold=True)
        sh.hline(tb[0], tb[2], tb[3] + 2, width=1, fill=st["ink"])
        ty += lh
        sh.text(xs[0] + pad, ty, "E.& O.E.", s)
        ty += lh
        terms = st["terms_list"][:1] if st["compact"] else st["terms_list"]
        for i, term in enumerate(terms):
            for line in _wrap(f"{i + 1}. {term}", sh.font(s), xs[1] - xs[0] - 2 * pad):
                sh.text(xs[0] + pad, ty, line, s)
                ty += lh
    else:
        sh.text(xs[0] + pad, ty, "E.& O.E.", s)
        ty += lh
    # QR
    qy = y + pad
    if st["einvoice"]:
        sh.text((xs[1] + xs[2]) / 2, qy, "E-Invoice QR Code", s, bold=True, anchor="ma")
        qy += lh
        qx = (xs[1] + xs[2]) / 2 - qr_size / 2
        qb = _draw_qr(sh, qx, qy, qr_size, st["qr"])
        qy = qb[3] + pad
    # signatures
    sx0, sx1 = xs[2], x1
    sy = y + pad
    sh.text(sx0 + pad, sy, "Receiver's Signature :", s, bold=True)
    sy += int(lh * 2.2)
    sig_bottom = sy + int(lh * 2.5)
    h = max(ty + pad, qy, sig_bottom + lh) - top
    h = max(h, int(st["dpi"] * 1.0))
    y = top + h
    name = spec["supplier"]["name"]
    fs = s
    while fs > 8 and sh.w(f"for {name}", fs, True) > sx1 - sx0 - 2 * pad:
        fs *= 0.94
    sh.text(sx1 - pad, sy, f"for {name}", fs, bold=True, anchor="ra")
    sh.text(sx1 - pad, y - pad - lh, "Authorised Signatory", s, bold=True, anchor="ra")
    for x in xs[1:3]:
        if x > xs[0] and x < x1:
            sh.vline(x, top, y)
    return y


# ---------------------------------------------------------------- page

def _page_footer(sh, spec, st, x0, x1, y):
    """'This is a computer generated invoice' and 'Page 1 of N' under the last box."""
    if not (st["computer_generated"] or st["page_no"]):
        return y
    s = st["body"] * 0.8
    y += int(st["body"] * 0.5)
    if st["computer_generated"]:
        text = "This is a Computer Generated Invoice"
        sh.text((x0 + x1) / 2, y, text if st["kind"] == "classic" else text.lower().capitalize(), s, anchor="ma")
    if st["page_no"]:
        sh.text(x1, y, f"Page 1 of {2 if spec['continued'] else 1}", s, anchor="ra")
    return y + int(s * 1.6)


def _compose(spec, st, height, free):
    sh = Sheet(st, height)
    layout = {"paper": st["paper"]}
    if st["kind"] == "erp":
        bottom = _erp(sh, spec, st, layout, free)
    else:
        bottom = _classic(sh, spec, st, layout, free)
    return sh, layout, int(bottom)


def _notes_area(img, layout, st, bottom):
    """First candidate region that is really blank on the page (checked on pixels)."""
    W, H = img.size
    x0, x1 = st["ml"], W - st["mr"]
    arr = np.asarray(img).astype(np.int16)
    paper = np.array(st["paper_rgb"], dtype=np.int16)
    cands = list(layout.pop("_notes", []))
    cands.append((x0 + (x1 - x0) * 0.3, bottom + 20, x1 - 10, H - 20))
    cands += layout.pop("_notes_late", [])
    cands.append((x0, 6, x1, st["top"] - 6))
    cands.append((x0, H - st["bottom"] + 6, x1, H - 6))
    for c in cands:
        bx0, by0, bx1, by1 = (int(round(v)) for v in c)
        bx0, by0, bx1, by1 = max(bx0, 0), max(by0, 0), min(bx1, W), min(by1, H)
        if bx1 - bx0 < 180 or by1 - by0 < 45:
            continue
        if np.abs(arr[by0:by1, bx0:bx1] - paper).max() < 30:
            # a pen note needs a few inches at most
            return (bx0, by0, min(bx1, bx0 + int(st["dpi"] * 3.6)), min(by1, by0 + int(st["dpi"] * 1.3)))
    return (0, 0, W, max(10, st["top"] - 4))


def render(spec, rng):
    st = _pick_style(spec, rng)
    H = st["H"]
    for level in range(6):
        _compact(st, level)
        _, _, bottom = _compose(spec, st, H, 0)
        if bottom <= H - st["bottom"]:
            break
    free = H - st["bottom"] - bottom
    if free < 0:   # still too long at the smallest size: print on a longer sheet rather than clip
        H = bottom + st["bottom"]
        free = 0
    sh, layout, bottom = _compose(spec, st, H, free)
    layout["notes_area"] = _notes_area(sh.img, layout, st, bottom)
    for k in ("table_bbox", "header_bbox", "invoice_number_bbox", "date_bbox", "total_bbox"):
        layout.setdefault(k, None)
    return sh.img, layout
