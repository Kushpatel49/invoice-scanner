"""Carbon-copy B2B tax invoice on pink or yellow paper (template "carbon").

The duplicate / triplicate sheet of a multi-part bill set, in one of two families:

  computer - an A4 tax invoice printed by billing software on coloured paper, like
             ALMOVA INTERNATIONAL (eval inv09): condensed bold serif letterhead,
             Original/Duplicate/Triplicate boxes, a wide many-column item table with a
             big empty body, a totals box, bank details and a Previous Balance /
             Closing Balance ledger box that must not be mistaken for the bill total.
  form     - a pre-printed bill-book form in coloured ink, like AVEES (eval inv05):
             numbered, mostly empty rows (sometimes the product list itself is
             pre-printed), filled in by an impact printer through carbon, so the values
             sit a little off the printed lines and in a different ink. A numeric bill
             number is sometimes the book's own red serial.

Ink is laid onto the paper colour with a slight blur, uneven pressure and a faint
double strike, the soft lower-contrast print of a carbon copy, plus the odd faint carbon
smudge. The page is otherwise clean: effects.py adds the photo, the receiving stamp and
the pen notes.
"""
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from bench.synth import hand
from bench.synth.spec import CATALOG, r2

# multi-part sets come pink and yellow mostly, sometimes green; a bill book's top sheet is white
PAPERS = {"pink": [(247, 196, 212), (244, 184, 204), (249, 206, 221), (241, 178, 199)],
          "yellow": [(251, 242, 172), (248, 236, 158), (252, 246, 192), (246, 233, 150)],
          "green": [(214, 236, 204), (206, 232, 198), (222, 241, 212)],
          "white": [(247, 246, 241), (250, 249, 245), (244, 243, 236)]}
LASER_INKS = [(28, 26, 30), (40, 36, 46), (52, 30, 62)]
FORM_INKS = [(120, 26, 42), (30, 40, 118), (24, 88, 60), (38, 34, 42), (78, 36, 112)]
ACCENT_INKS = [(180, 30, 40), (30, 42, 140), (20, 100, 55)]
CARBON_INKS = [(38, 44, 128), (66, 42, 120), (42, 40, 52), (30, 30, 90)]
SEAL_INKS = [(40, 62, 170), (88, 52, 160), (45, 50, 140)]
SERIAL_INKS = [(196, 36, 48), (178, 30, 44), (205, 52, 60)]
STD_CODES = {"Kerala": ["0484", "0477", "0487", "0485", "0480"], "Tamil Nadu": ["0422", "0423", "04254"],
             "Karnataka": ["080"]}

TAGLINES = {
    "packaged": ["Importers & Distributors of Honey, Dates & Dry Fruits", "Wholesale Distributors - Gourmet Foods",
                 "Authorised Distributors : Langnese Honey"],
    "packaged_food": ["Manufacturers of Instant Food Products", "Makers of Quality Instant Foods Since 1978"],
    "fruit_import": ["Importers & Wholesale Dealers in Fresh Fruits", "Fresh Fruit Importers & Distributors"],
    "spices": ["Wholesale Dealers in Spices & Condiments", "Exporters & Suppliers of Kerala Spices"],
    "other": ["Wholesale Dealers & Distributors"],
}
BRAND_WORDS = {"packaged": "GOURMET FOODS", "packaged_food": "FOOD PRODUCTS", "fruit_import": "FRUIT IMPORTERS",
               "spices": "SPICES & CONDIMENTS"}
TITLES = {"none": ["BILL OF SUPPLY", "B2B SUPPLY", "INVOICE", "CREDIT BILL"],
          "exclusive": ["TAX INVOICE", "B2B SUPPLY", "GST INVOICE", "TAX INVOICE (B2B)"],
          "inclusive": ["B2B SUPPLY", "TAX INVOICE", "GST INVOICE"]}
BANKS = [("HDFC BANK", "HDFC"), ("FEDERAL BANK", "FDRL"), ("SOUTH INDIAN BANK", "SIBL"),
         ("STATE BANK OF INDIA", "SBIN"), ("CANARA BANK", "CNRB"), ("DHANLAXMI BANK", "DLXB"), ("ICICI BANK", "ICIC"), ("CSB BANK", "CSBK")]
TERMS = [
    "Return Policy: Goods can be returned within 7 days from the date of delivery, subject to approval and "
    "provided they are in their original condition.",
    "Damaged/Short Supply: Any damage or shortage must be reported within 24 hours of delivery.",
    "Return Policy: No returns or exchanges will be accepted for imported items.",
    "Goods once sold will not be taken back or exchanged.",
    "Interest @ 18% p.a. will be charged on bills not paid within 30 days.",
    "Our responsibility ceases as soon as the goods leave our premises.",
    "Payment by A/c Payee Cheque / RTGS / NEFT only.",
]
TRAP_LABELS = [["Previous Balance", "Bill Amount", "Cash Received", "Closing Balance"],
               ["Old Balance", "This Bill", "Received", "Balance Due"],
               ["Opening Balance", "Current Bill", "Amount Paid", "Closing Balance"]]

HEADS = {
    "sl": [["Sl"], ["Sl", "No"], ["S.No"]],
    "desc": [["Description Of Goods"], ["Description of Goods"], ["Particulars"], ["Item Description"]],
    "hsn": [["HSN", "SAC"], ["HSN", "Code"], ["HSN"]],
    "uom": [["UOM"], ["Unit"]],
    "qty": [["QTY"], ["Qty"], ["Quantity"]],
    "mrp": [["MRP"]],
    "rate": [["Rate"]],
    "incl": [["INCL", "Rate"], ["Rate", "Incl.Tax"]],
    "disc": [["Less", "Discount"], ["Disc", "%"], ["Disc."]],
    "taxable": [["Taxable", "Value"], ["Taxable", "Amount"]],
    "gst": [["GST", "%"], ["Tax", "%"], ["GST", "Rate"]],
    "cgst": [["CGST", "Amount"], ["CGST", "Amt"]],
    "sgst": [["SGST", "Amount"], ["SGST", "Amt"]],
    "cess": [["Cess", "Amount"], ["Cess"]],
}
AMOUNT_HEADS = {"inclusive": [["Total"], ["Total", "Amount"], ["Net", "Amount"]],
                "exclusive": [["Amount"], ["Taxable", "Amount"], ["Value"]],
                "none": [["Amount"], ["Total"], ["Value"]]}
ALIGN = {"sl": "c", "desc": "l", "hsn": "c", "uom": "c", "gst": "c"}   # everything else right-aligned


# ---------------------------------------------------------------- formatting

def indian_groups(digits):
    """'10160920' -> '1,01,60,920'"""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + groups + [tail])


def money(v, style="plain"):
    """1609.2 -> '1609.20' (plain), '1,609.20' (comma), '1,609.20' / '1,01,609.20' (indian),
    and for 'trim' whole rupees lose the paise: '1609' (but 1609.20 stays '1609.20')."""
    s = f"{abs(v):.2f}"
    whole, paise = s.split(".")
    if style == "comma":
        whole = f"{int(whole):,}"
    elif style == "indian":
        whole = indian_groups(whole)
    out = whole if style == "trim" and paise == "00" else f"{whole}.{paise}"
    return "-" + out if v < 0 and s != "0.00" else out


def num_style(style, items):
    """Billing software formats a whole column alike: 'trim' (no paise on whole rupees) only
    when every rate and amount on the bill is whole, otherwise plain 2-decimal numbers."""
    if style == "trim" and not all(float(v).is_integer() for it in items for v in (it["rate"], it["amount"])):
        return "plain"
    return style


def qty_text(q, decimals):
    """Quantity with at least `decimals` places, never fewer than the value needs (2.375 stays 2.375)."""
    need = 0 if float(q).is_integer() else len(repr(float(q)).split(".")[1])
    d = max(need, decimals)
    return f"{float(q):.{d}f}" if d else str(int(q))


def pct_text(t, style):
    if style == "2dp":
        return f"{t:.2f}"
    if style == "pct":
        return f"{t:g}%"
    return f"{t:g}"


# ---------------------------------------------------------------- drawing helpers

def F(kind, size, bold=False):
    """Font by PRINT_FONTS key; the static serif / typewriter faces have separate bold files."""
    if kind in ("serif", "typewriter"):
        return hand.font(kind + "_bold" if bold else kind, size)
    return hand.font(kind, size, bold)


def fit(kind, size, bold, text, width, min_size=11):
    """The largest font of `kind` (up to `size`) in which `text` fits `width`."""
    while size > min_size and F(kind, size, bold).getlength(text) > width:
        size -= 1
    return F(kind, size, bold)


def wrap(text, f, width):
    """Greedy word wrap; a single word longer than the width is broken by characters."""
    lines, cur = [], ""
    for word in text.split():
        while f.getlength(word) > width and len(word) > 1:
            if cur:
                lines.append(cur)
                cur = ""
            k = len(word) - 1
            while k > 1 and f.getlength(word[:k]) > width:
                k -= 1
            lines.append(word[:k])
            word = word[k:]
        trial = word if not cur else cur + " " + word
        if f.getlength(trial) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def union(boxes):
    boxes = [b for b in boxes if b]
    return (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
            int(math.ceil(max(b[2] for b in boxes))), int(math.ceil(max(b[3] for b in boxes))))


class Ink:
    """Coverage mask for one printing ink (255 = full ink), composited onto the paper at the end.

    offset shifts everything drawn: an impact printer's fill never lines up exactly with the
    pre-printed form. With dry=True nothing is drawn but text boxes are still measured, so a
    block can be laid out once to learn its height and then drawn for real.
    """

    def __init__(self, size, offset=(0, 0)):
        self.mask = Image.new("L", size, 0)
        self.d = ImageDraw.Draw(self.mask)
        self.ox, self.oy = offset
        self.dry = False

    def text(self, x, y, s, f, anchor="ls", fill=255):
        x, y = x + self.ox, y + self.oy
        if not self.dry:
            self.d.text((x, y), s, font=f, fill=fill, anchor=anchor)
        return self.d.textbbox((x, y), s, font=f, anchor=anchor)

    def line(self, x0, y0, x1, y1, w=2):
        if not self.dry:
            self.d.line([(x0 + self.ox, y0 + self.oy), (x1 + self.ox, y1 + self.oy)], fill=255, width=w)

    def rect(self, box, w=2):
        if not self.dry:
            x0, y0, x1, y1 = box
            self.d.rectangle([x0 + self.ox, y0 + self.oy, x1 + self.ox, y1 + self.oy], outline=255, width=w)

    def dashes(self, x0, x1, y, w=2, on=10, off=7):
        x = x0
        while x < x1:
            self.line(x, y, min(x + on, x1), y, w)
            x += on + off

    def dots(self, x0, x1, y, step=7):
        """A dotted leader line, as on a pre-printed form."""
        if self.dry:
            return
        for x in range(int(x0), int(x1), step):
            self.d.ellipse([x + self.ox - 1, y + self.oy - 1, x + self.ox + 1, y + self.oy + 1], fill=255)

    def squeezed(self, x, y, s, f, sx, anchor="ms"):
        """Text squeezed (sx < 1) or stretched horizontally: condensed letterhead faces.
        (x, y) is the baseline point; anchor 'ls', 'ms' or 'rs'."""
        asc, desc = f.getmetrics()
        w, h = int(f.getlength(s)) + 8, asc + desc + 8
        tile = Image.new("L", (w, h), 0)
        ImageDraw.Draw(tile).text((4, 4 + asc), s, font=f, fill=255, anchor="ls")
        nw = max(1, round(w * sx))
        tile = tile.resize((nw, h), Image.LANCZOS)
        tw = f.getlength(s) * sx
        left = x - 4 * sx - {"ls": 0, "ms": tw / 2, "rs": tw}[anchor] + self.ox
        top = y - 4 - asc + self.oy
        if not self.dry:
            self.mask.paste(255, (round(left), round(top)), tile)
        b = tile.getbbox() or (0, 0, 1, 1)
        return (round(left) + b[0], round(top) + b[1], round(left) + b[2], round(top) + b[3])


def lay_ink(arr, mask, color, rng, blur=0.6, strength=0.9, ghost=None, smear=0, patchy=0.0):
    """Multiply one ink onto the paper array (H, W, 3 float). Blur, a faint double strike (ghost),
    a sideways smear (0, 3 or 5 px wide) and uneven pressure give the soft look of carbon / toner
    on a copy sheet."""
    m = mask
    if ghost:
        m = ImageChops.lighter(m, ImageChops.offset(m, *ghost).point(lambda v: int(v * 0.3)))
    if smear == 5:
        m = m.filter(ImageFilter.Kernel((5, 5), [0] * 10 + [1, 2, 3, 2, 1] + [0] * 10, scale=9))
    elif smear:
        m = m.filter(ImageFilter.Kernel((3, 3), [0, 0, 0, 1, 2, 1, 0, 0, 0], scale=4))
    if blur:
        m = m.filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(m, np.float32) * (strength / 255)
    if patchy:
        grid = np.array([[rng.uniform(1 - patchy, 1) for _ in range(5)] for _ in range(7)], np.float32)
        field = Image.fromarray((grid * 255).astype(np.uint8)).resize(m.size, Image.BICUBIC)
        a *= np.asarray(field, np.float32) / 255
    arr *= 1 - a[..., None] * (1 - np.array(color, np.float32) / 255)


def smear_px(font_kind):
    """A 5 px smear closes the tight gaps of a condensed face (64.00 -> 6400): 3 px there."""
    return 3 if font_kind == "narrow" else 5


def initials(name):
    words = [w for w in name.replace(".", " ").split() if w not in ("&", "PVT", "LTD", "THE")]
    return "".join(w[0] for w in words[:2]) or name[:2]


def draw_logo(ink, x, y, s, kind, letters):
    """A simple printed logo in an s x s box at (x, y). Returns its bbox."""
    d = ink.d
    if kind == "ring":
        d.ellipse([x, y, x + s, y + s], outline=255, width=max(3, s // 22))
        d.ellipse([x + s * 0.09, y + s * 0.09, x + s * 0.91, y + s * 0.91], outline=255, width=2)
        d.text((x + s / 2, y + s / 2), letters, font=hand.font("serif_bold", int(s * 0.36)), fill=255, anchor="mm")
    elif kind == "leaf":
        pts = []
        for i in range(21):
            t = i / 20
            pts.append((x + s * (0.08 + 0.84 * t), y + s * (0.62 - 0.36 * t) - math.sin(t * math.pi) * s * 0.24))
        for i in range(21):
            t = 1 - i / 20
            pts.append((x + s * (0.08 + 0.84 * t), y + s * (0.62 - 0.36 * t) + math.sin(t * math.pi) * s * 0.2))
        d.polygon(pts, fill=255)
        d.line([(x + s * 0.02, y + s * 0.7), (x + s * 0.88, y + s * 0.27)], fill=0, width=max(2, s // 40))
        d.line([(x, y + s * 0.92), (x + s * 0.16, y + s * 0.62)], fill=255, width=max(3, s // 30))
    elif kind == "diamond":
        d.polygon([(x + s / 2, y), (x + s, y + s / 2), (x + s / 2, y + s), (x, y + s / 2)], outline=255,
                  width=max(3, s // 25))
        d.text((x + s / 2, y + s / 2), letters[0], font=hand.font("serif_bold", int(s * 0.46)), fill=255, anchor="mm")
    else:  # sun
        cx, cy, r = x + s / 2, y + s / 2, s * 0.2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        for k in range(12):
            a = k * math.pi / 6
            d.line([(cx + math.cos(a) * r * 1.4, cy + math.sin(a) * r * 1.4),
                    (cx + math.cos(a) * s * 0.48, cy + math.sin(a) * s * 0.48)], fill=255, width=max(3, s // 30))
    return (int(x), int(y), int(x + s), int(y + s))


def draw_seal(mask, cx, cy, r, ring_text, centre):
    """The supplier's round rubber seal: two rings, the name around, a word and a star inside."""
    d = ImageDraw.Draw(mask)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=255, width=5)
    d.ellipse([cx - r * 0.64, cy - r * 0.64, cx + r * 0.64, cy + r * 0.64], outline=255, width=3)
    n = len(ring_text)
    step = min(320 / max(n, 1), 24)
    s = max(11, int(min(r * 0.24, r * 0.82 * math.radians(step) * 1.3)))
    f = hand.font("serif_bold", s)
    for i, ch in enumerate(ring_text):
        if ch == " ":
            continue
        ang = (i - (n - 1) / 2) * step
        px, py = cx + math.sin(math.radians(ang)) * r * 0.82, cy - math.cos(math.radians(ang)) * r * 0.82
        tile = Image.new("L", (s * 2, s * 2), 0)
        ImageDraw.Draw(tile).text((s, s), ch, font=f, fill=255, anchor="mm")
        mask.paste(255, (int(px - s), int(py - s)), tile.rotate(-ang, resample=Image.BICUBIC))
    cs = max(10, int(r * 0.2))
    while cs > 10 and hand.font("serif_bold", cs).getlength(centre) > r * 1.1:
        cs -= 1
    d.text((cx, cy - r * 0.12), centre, font=hand.font("serif_bold", cs), fill=255, anchor="mm")
    sr = r * 0.12
    pts = [(cx + math.sin(k * math.pi / 5) * (sr if k % 2 == 0 else sr * 0.45),
            cy + r * 0.3 - math.cos(k * math.pi / 5) * (sr if k % 2 == 0 else sr * 0.45)) for k in range(10)]
    d.polygon(pts, fill=255)


# ---------------------------------------------------------------- shared bill content

def cell_text(key, i, it, st):
    if key == "sl":
        return f"{i + 1}." if st["sl_dot"] else str(i + 1)
    if key == "desc":
        return it["description"]
    if key == "hsn":
        return it["hsn"]
    if key == "uom":
        return it["unit"]
    if key == "qty":
        return qty_text(it["quantity"], st["qdec"])
    if key == "mrp":
        return money(it["mrp"], st["num"]) if it["mrp"] is not None else ""
    if key == "rate":
        return money(it["rate"], st["num"])
    if key == "incl":
        return money(r2(it["rate"] * (1 + it["tax_percent"] / 100)), st["num"])
    if key in ("disc", "cess"):
        return money(0.0, st["num"])
    if key == "taxable":
        return money(it["taxable"], st["num"])
    if key == "gst":
        return pct_text(it["tax_percent"], st["pct"])
    if key in ("cgst", "sgst"):
        return money(it[key], st["num"])
    return money(it["amount"], st["num"])


def total_cells(keys, spec, st, with_qty):
    """The table's column-total row (empty for a continued page)."""
    if spec["continued"]:
        return {}
    items, tot, M = spec["items"], spec["totals"], lambda v: money(v, st["num"])
    t = {}
    if with_qty and "qty" in keys:
        qs = [it["quantity"] for it in items]
        dec = max([st["qdec"]] + [0 if float(q).is_integer() else len(repr(float(q)).split(".")[1]) for q in qs])
        t["qty"] = qty_text(round(sum(qs), 3), dec)
    for k in ("disc", "cess"):
        if k in keys:
            t[k] = M(0.0)
    if "taxable" in keys:
        t["taxable"] = M(tot["subtotal"])
    for k in ("cgst", "sgst"):
        if k in keys:
            t[k] = M(tot[k])
    t["amount"] = M(r2(sum(it["amount"] for it in items)))
    return t


def fit_columns(keys, heads, cells, fb, fh, x0, x1, pad, desc_frac, min_desc=0.16, force=False):
    """Column edges. Each non-description column is as wide as its widest cell or header word;
    the description column gets `desc_frac` of the table and any surplus is shared out.
    None when even tight columns leave the description too narrow (caller shrinks the font)."""
    tw = x1 - x0
    need = {}
    for k in keys:
        if k != "desc":
            need[k] = max([fb.getlength(c) for c in cells[k]] + [fh.getlength(h) for h in heads[k]]) + 2 * pad
    rest = tw - sum(need.values())
    head_w = max(fh.getlength(h) for h in heads["desc"]) + 2 * pad
    if rest < max(head_w, min_desc * tw) and not force:
        return None
    rest = max(rest, 60)
    desc_w = max(desc_frac * tw, head_w)
    if rest > desc_w:
        extra = (rest - desc_w) / len(need)
        need = {k: v + extra for k, v in need.items()}
    else:
        desc_w = rest
    edges, x = {}, float(x0)
    for k in keys:
        w = desc_w if k == "desc" else need[k]
        edges[k] = (round(x), round(x + w))
        x += w
    last = keys[-1]
    edges[last] = (edges[last][0], x1)
    return edges


def cap_mid(f, y):
    """Baseline that puts the middle of capitals/digits on y (the 'm' anchor centres the whole
    ascender-descender box, which sits typewriter digits visibly high)."""
    return y - f.getbbox("8", anchor="ls")[1] / 2


def put(ink, key, text, edge, y, f, pad, anchor_v="s", align=None):
    """Draw a cell value inside column `edge` on baseline y (anchor_v 's') or centred on y ('m')."""
    a = align or ALIGN.get(key, "r")
    xl, xr = edge
    if anchor_v == "m":
        y, anchor_v = cap_mid(f, y), "s"
    if a == "l":
        return ink.text(xl + pad, y, text, f, "l" + anchor_v)
    if a == "c":
        return ink.text((xl + xr) / 2, y, text, f, "m" + anchor_v)
    return ink.text(xr - pad, y, text, f, "r" + anchor_v)


def bank_and_trap(spec, rng):
    """Bank details and the ledger box. The previous / closing balances are trap numbers:
    big, money-formatted and right next to the bill amount, but not the invoice total."""
    sup = spec["supplier"]
    name, code = rng.choice(BANKS)
    bank = {"name": name, "branch": sup["address_lines"][-1].split(",")[0].strip(),
            "acct": "".join(rng.choice("0123456789") for _ in range(rng.choice([12, 14, 15]))),
            "ifsc": f"{code}000{rng.randint(1000, 9999)}"}
    grand = spec["totals"]["grand_total"]
    trap = None
    if grand is not None:
        prev = r2(rng.choice([rng.uniform(4000, 320000), float(rng.randint(40, 3000) * 100)]))
        cash = rng.choice([0.0, 0.0, float(rng.randint(5, 400) * 100), prev])
        trap = list(zip(rng.choice(TRAP_LABELS), [prev, grand, cash, r2(prev + grand - cash)]))
    return bank, trap


def summary_rows(spec, rng):
    """(label, value, is_grand_total) rows of the totals box, from the spec totals."""
    tot, tax = spec["totals"], spec["tax_mode"]
    rows = []
    if tax == "inclusive":
        rows.append(("TOTAL AMOUNT", r2(sum(it["amount"] for it in spec["items"])), False))
        if rng.random() < 0.6:
            rows.append(("LESS : TOTAL DISCOUNT", 0.0, False))
        rows.append((rng.choice(["GRAND TOTAL BEFORE TAX", "TOTAL BEFORE TAX"]), tot["subtotal"], False))
    else:
        rows.append((rng.choice(["TOTAL BEFORE TAX", "TAXABLE AMOUNT", "TOTAL AMOUNT"]) if tax == "exclusive"
                     else rng.choice(["TOTAL AMOUNT", "GROSS AMOUNT"]), tot["subtotal"], False))
        if rng.random() < 0.4:
            rows.append(("LESS : DISCOUNT", 0.0, False))
    if tax != "none":
        rows += [("ADD : CGST", tot["cgst"], False), ("ADD : SGST", tot["sgst"], False)]
        if rng.random() < 0.3:
            rows.append(("ADD : IGST", 0.0, False))
        if rng.random() < 0.5:
            rows.append(("ADD : CESS", 0.0, False))
    if rng.random() < 0.5:
        rows.append((rng.choice(["FREIGHT CHARGES", "FRIEGHT CHARGES", "TRANSPORT CHARGES"]), 0.0, False))
    if tot["round_off"] or rng.random() < 0.5:
        rows.append((rng.choice(["ROUND OFF", "ROUNDED OFF", "Round Off (+/-)"]), tot["round_off"], False))
    rows.append((rng.choice(["NET TOTAL", "NET TOTAL", "GRAND TOTAL", "INVOICE TOTAL"]), tot["grand_total"], True))
    return rows


def smudges(size, rng):
    """Faint carbon smudges and sometimes a rubbed streak, the handling marks of a carbon-backed
    copy. Drawn at 1/8 scale and blurred so they stay soft; returns a full-size L mask."""
    W, H = size
    sw, sh = max(8, W // 8), max(8, H // 8)
    m = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(m)
    for _ in range(rng.randint(1, 4)):
        cx, cy = rng.uniform(0, sw), rng.uniform(0, sh)
        rx, ry = rng.uniform(3, 14), rng.uniform(2, 9)
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=rng.randint(90, 255))
    if rng.random() < 0.5:
        x0, y0 = rng.uniform(0, sw), rng.uniform(0, sh)
        a = rng.uniform(-0.5, 0.5) + (0 if rng.random() < 0.5 else math.pi / 2)
        n = rng.uniform(20, 80)
        d.line([(x0, y0), (x0 + math.cos(a) * n, y0 + math.sin(a) * n)], fill=rng.randint(80, 200),
               width=rng.randint(2, 5))
    m = m.filter(ImageFilter.GaussianBlur(rng.uniform(2.5, 5)))
    return m.resize((W, H), Image.BICUBIC)


def composite(W, H, paper_rgb, layers, rng):
    """Paper colour plus each (mask, colour, treatment) ink layer -> RGB page."""
    arr = np.empty((H, W, 3), np.float32)
    arr[:] = paper_rgb
    for mask, color, kw in layers:
        lay_ink(arr, mask.crop((0, 0, W, H)), color, rng, **kw)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def add_seal_and_sign(spec, rng, size, area):
    """The supplier's own seal and signature in the signatory box (part of the bill as issued)."""
    mask = Image.new("L", size, 0)
    x0, y0, x1, y1 = area
    if x1 - x0 < 120 or y1 - y0 < 60:
        return mask
    if rng.random() < 0.55:
        r = min((y1 - y0) * 0.62, (x1 - x0) * 0.28, 120)
        cx = rng.uniform(x0 + r, max(x0 + r, x1 - r))
        cy = rng.uniform(y0 + r * 0.6, max(y0 + r * 0.6, y1 - r * 0.4))
        draw_seal(mask, cx, cy, r, spec["supplier"]["name"],
                  spec["supplier"]["address_lines"][-1].split(",")[0].strip().upper())
    if rng.random() < 0.7:
        hand.signature(mask, (rng.uniform(x0 + 10, x0 + (x1 - x0) * 0.4), (y0 + y1) / 2 + rng.uniform(-10, 15)),
                       min(220, (x1 - x0) * 0.5), rng, ink=255)
    return mask


# ---------------------------------------------------------------- computer-printed A4 (Almova)

def _computer(spec, rng):
    sup, buyer, items = spec["supplier"], spec["buyer"], spec["items"]
    tax, cont = spec["tax_mode"], spec["continued"]
    W = rng.randint(1600, 1700)
    H = round(W * rng.uniform(1.40, 1.43))
    paper = rng.choice(["pink"] * 6 + ["yellow"] * 3 + ["green"])
    X0, X1 = rng.randint(55, 95), W - rng.randint(55, 95)
    BW = X1 - X0
    top = rng.randint(140, 200)
    st = {"num": num_style(rng.choice(["plain", "plain", "plain", "comma", "indian", "trim"]), items),
          "qdec": rng.choice([3, 3, 2, 0]),
          "pct": rng.choice(["2dp", "2dp", "int", "pct"]), "sl_dot": rng.random() < 0.2}
    body = rng.choice(["sans", "sans2", "narrow"])
    fs = rng.randint(21, 24)
    lp = round(fs * rng.uniform(1.45, 1.6))
    lab_fill = rng.choice([255, 255, 185])           # labels sometimes print lighter than values
    flab, flab_b, fval = F(body, fs), F(body, fs, True), F(body, fs + 1, True)
    lw = rng.choice([1, 2, 2])
    ink = Ink((W, H + 4000))
    lay = {"paper": paper, "style": "computer"}

    # letterhead: centred (like Almova), or name and address on the left with the contact /
    # GSTIN block ranged right
    hb = []
    cx = (X0 + X1) / 2
    head_left = rng.random() < 0.35
    logo = rng.choice([None, None, None, "ring", "leaf", "diamond", "sun"])
    ls = rng.randint(118, 150)
    xl = X0 + (ls + 28 if logo else 6)
    text_w = round(X0 + BW * 0.62) - xl if head_left else BW - (2 * (ls + 30) if logo else 20)
    hk = rng.choice(["serif", "serif", "condensed", "sans"])
    sx = rng.uniform(0.74, 0.86) if hk == "serif" else rng.uniform(0.9, 1.0)
    size = rng.randint(72, 88) - (8 if head_left else 0)
    while size > 30 and F(hk, size, True).getlength(sup["name"]) * sx > text_w:
        size -= 2
    y = top + round(size * 0.75)
    hb.append(ink.squeezed(xl if head_left else cx, y, sup["name"], F(hk, size, True), sx,
                           "ls" if head_left else "ms"))
    if logo:
        hb.append(draw_logo(ink, X0 + 12, top - 6, ls, logo, initials(sup["name"])))
    sk = rng.choice(["serif", "serif", "sans"])
    ss = rng.randint(26, 30) - (3 if head_left else 0)
    ssx = rng.uniform(0.84, 0.95) if sk == "serif" else 1.0
    sub = []
    if rng.random() < 0.45:
        sub.append(rng.choice(TAGLINES.get(spec["supplier_kind"], TAGLINES["other"])))
    upper = rng.random() < 0.65
    sub += [a.upper() if upper else a for a in sup["address_lines"]]
    contact = [rng.choice(["PH: +91 ", "Ph: ", "Phone: ", "Mob: +91 "]) + sup["phone"]]
    if sup["email"] and rng.random() < 0.6:
        contact.append("E-mail: " + sup["email"])
    if sup["fssai"] and rng.random() < 0.8:
        contact.append(rng.choice(["FSSAI: ", "FSSAI Lic. No: ", "FSSAI No. "]) + sup["fssai"])
    if sup["gstin"]:
        contact.append(rng.choice(["GSTIN: ", "GSTIN : ", "GSTIN/UIN: "]) + sup["gstin"])
    if head_left:
        blocks = [(sub, xl, "ls", text_w, y + round(ss * 0.35)),
                  (contact, X1 - 4, "rs", round(BW * 0.34), top - round(ss * 0.4))]
    else:
        if len(contact) > 1 and contact[1].startswith("E-mail"):
            contact[0:2] = [contact[0] + "   " + contact[1]]
        blocks = [(sub + contact, cx, "ms", text_w, y + round(ss * 0.35))]
    for lines, x, anchor, width, yy in blocks:
        for s in lines:
            big = s.startswith("GSTIN")
            sz = ss + (3 if big else 0)
            while sz > 14 and F(sk, sz, True).getlength(s) * ssx > width:
                sz -= 1
            yy += round(sz * 1.22)
            hb.append(ink.squeezed(x, yy, s, F(sk, sz, True), ssx, anchor))
    lay["header_bbox"] = union(hb)
    lay["notes_area"] = (round(W * 0.52), 18, W - 30, max(60, lay["header_bbox"][1] - 10))
    y_box = lay["header_bbox"][3] + rng.randint(20, 36)

    # title row with the Original / Duplicate / Triplicate boxes
    y = y_box
    cw = round(BW * rng.uniform(0.27, 0.32))
    xc = X1 - cw
    copy_boxes = rng.random() < 0.7
    th = 84 if copy_boxes else 72
    ink.text((X0 + xc) / 2, y + th / 2, rng.choice(TITLES[tax]), F(body, fs + 1, True), "mm")
    ink.line(xc, y, xc, y + th, lw)
    if copy_boxes:
        labels = ["Original for Recipient", "Duplicate for Supplier/Transporter", "Triplicate for Supplier"]
        fc = fit(body, 19, True, labels[1], cw - 50)
        rh = th / 3
        mark = rng.choice([None, None, 1, 2])
        for k, t in enumerate(labels):
            yy = y + k * rh
            if k:
                ink.line(xc, yy, X1, yy, 1)
            b = (xc + 8, yy + 5, xc + rh - 2, yy + rh - 5)
            ink.rect(b, 2)
            if mark == k:
                ink.line(b[0] + 3, b[1] + 3, b[2] - 3, b[3] - 3, 2)
                ink.line(b[2] - 3, b[1] + 3, b[0] + 3, b[3] - 3, 2)
            ink.text(xc + rh + 6, yy + rh / 2, t, fc, "lm")
    else:
        lab = rng.choice(["DUPLICATE", "DUPLICATE COPY", "TRANSPORTER COPY", "TRIPLICATE", "OFFICE COPY"])
        ink.text(xc + cw / 2, y + th / 2, lab, fit(body, fs + 8, True, lab, cw - 30), "mm")
    y += th
    ink.line(X0, y, X1, y, lw)

    # invoice no / date (left) and transport details (right)
    mid = X0 + round(BW * rng.uniform(0.54, 0.58))
    left = [("Reverse Charge", rng.choice(["", "N", "No"])),
            (rng.choice(["Invoice No.", "Invoice No", "Inv. No."]), None),   # values drawn below
            (rng.choice(["Invoice Date", "Dated", "Date"]), None), ("State", sup["state"])]
    clock = rng.randint(0, 99)
    right = [("Transportation Mode", rng.choice(["", "", "By Road", "ROAD"])),
             ("Vehicle Number", rng.choice(["", f"KL-{rng.randint(1, 65):02d}-{rng.choice(['AB', 'BX', 'K', 'Q'])}-"
                                                f"{rng.randint(1000, 9999)}"])),
             ("Date of Supply", rng.choice(["", f"{8 + clock % 10:02d}:{clock % 60:02d}:{rng.randint(10, 59)}"])),
             ("Supplier's Ref / Order No", "")]
    if rng.random() < 0.5:
        right.insert(3, ("Place of Supply", "Kerala (32)"))
    colon = X0 + 16 + max(flab.getlength(t) for t, _ in left) + 10
    rcolon = mid + 12 + max(flab.getlength(t) for t, _ in right) + 10
    yy = y + 6
    for k, (lab, val) in enumerate(left):
        yy += lp
        ink.text(X0 + 14, yy, lab, flab, fill=lab_fill)
        ink.text(colon, yy, ":", flab)
        if k == 1:
            f = fit(body, fs + 5, True, spec["invoice_number_printed"], mid - colon - 30)
            lay["invoice_number_bbox"] = ink.text(colon + 16, yy + 2, spec["invoice_number_printed"], f)
        elif k == 2:
            lay["date_bbox"] = ink.text(colon + 16, yy, spec["date_printed"], fval)
        elif val:
            ink.text(colon + 16, yy, val, fval)
    # state code box on the State row
    sb = (mid - round(BW * 0.17), yy - lp + 12, mid - 6, yy + 10)
    ink.rect(sb, lw)
    ink.line(sb[2] - 60, sb[1], sb[2] - 60, sb[3], lw)
    ink.text(sb[2] - 70, yy, "State Code :", flab, "rs")
    ink.text(sb[2] - 30, yy, sup["state_code"], fval, "ms")
    ry = y + 6
    fr = F(body, fs - 1)
    for lab, val in right:
        ry += lp
        ink.text(mid + 12, ry, lab, fr, fill=lab_fill)
        ink.text(rcolon, ry, ":", flab)
        if val:
            ink.text(rcolon + 30, ry, val, flab)
    y_end = max(yy, ry) + 16
    ink.line(mid, y, mid, y_end, lw)
    y = y_end
    ink.line(X0, y, X1, y, lw)

    # billed to / shipped to
    if rng.random() < 0.5:
        ink.dashes(X0, X1, y + 4, 1)
    hh = lp + 6
    ink.text((X0 + mid) / 2, y + hh / 2 + 3, rng.choice(["Details", "Details of Receiver | Billed to:", "Bill To"]),
             flab_b, "mm")
    ink.text((mid + X1) / 2, y + hh / 2 + 3, rng.choice(["Details of Consignee | Shipped to:", "Ship To", "Consignee"]),
             flab_b, "mm")
    y += hh
    ink.line(X0, y, X1, y, lw)
    same = rng.random() < 0.35
    bill = [("Name", buyer["display"]), ("Address", buyer["address_lines"][0]), ("", buyer["address_lines"][1]),
            ("GSTIN", buyer["gstin"]), ("State", "Kerala")]
    bcolon = X0 + 16 + flab.getlength("Address") + 40
    scolon = mid + 12 + flab.getlength("Address") + 40
    yy = y
    for lab, val in bill:
        yy += lp
        for xl, xcol, xr, show in ((X0 + 14, bcolon, mid, True), (mid + 12, scolon, X1, same or lab == "State")):
            if lab:
                ink.text(xl, yy, lab, flab, fill=lab_fill)
                ink.text(xcol, yy, ":", flab)
            if show and val:
                ink.text(xcol + 16, yy, val, fit(body, fs, False, val, xr - xcol - 30 - (220 if lab == "State" else 0)))
    for xr in (mid, X1):
        b = (xr - round(BW * 0.17), yy - lp + 12, xr - 6, yy + 10)
        ink.rect(b, lw)
        ink.line(b[2] - 60, b[1], b[2] - 60, b[3], lw)
        ink.text(b[2] - 70, yy, "State Code :", flab, "rs")
        ink.text(b[2] - 30, yy, "32", flab, "ms")
    y_end = yy + 16
    ink.line(mid, y, mid, y_end, lw)
    y = y_end
    ink.line(X0, y, X1, y, lw)
    if rng.random() < 0.5:
        fa = F(body, fs - 4, True)
        yy = y + round(lp * 0.75)
        for k, t in enumerate(["Ack No:", "Ack Date:", "IRN:"]):
            ink.text(X0 + 14 + k * round(BW * 0.18), yy, t, fa)
        y += lp
        ink.line(X0, y, X1, y, lw)

    # item table columns
    keys = ["sl", "desc", "hsn", "uom", "qty"]
    if rng.random() < 0.25:
        keys[3], keys[4] = "qty", "uom"
    if any(it["mrp"] is not None for it in items) and rng.random() < 0.8:
        keys.append("mrp")
    keys.append("rate")
    if tax == "inclusive":
        keys += [k for k, p in (("incl", 0.7), ("disc", 0.6)) if rng.random() < p]
        keys += ["taxable", "gst", "cgst", "sgst"] + (["cess"] if rng.random() < 0.6 else [])
    else:
        keys += ["disc"] if rng.random() < 0.45 else []
        keys += ["gst"] if tax == "exclusive" else []
    keys.append("amount")
    heads = {k: rng.choice(HEADS[k]) for k in keys if k != "amount"}
    heads["amount"] = rng.choice(AMOUNT_HEADS[tax])
    cells = {k: [cell_text(k, i, it, st) for i, it in enumerate(items)] for k in keys}
    tcells = total_cells(keys, spec, st, rng.random() < 0.7)
    for k in keys:
        cells[k] = cells[k] + [tcells.get(k, "")]
    desc_frac = rng.uniform(0.2, 0.3) if len(keys) > 10 else rng.uniform(0.3, 0.4)
    pad = 8

    # bottom part (totals box, bank, ledger box, terms) is measured first so the table body
    # can take whatever height is left, like the big empty item area of a real A4 bill
    ctx = _computer_bottom_ctx(spec, rng, st, body, fs, lp, lw, X0, X1)
    ink.dry = True
    bot_h = _computer_bottom(ink, 0, ctx)[0]
    ink.dry = False
    footer = rng.random() < 0.75
    foot_h = 70 if footer else 30

    fsb0 = rng.randint(21, 24)
    min_row = rng.randint(54, 76)
    row_lines = rng.random() < 0.2
    # long bills: first drop the generous row height, then the padding, then shrink the font
    # (down to 17px); if the rows still do not fit, the page grows
    for fsb in range(fsb0, 12, -1):
        fb, fh = F(body, fsb), F(body, fsb - 1)
        edges = fit_columns(keys, heads, cells, fb, fh, X0, X1, pad, desc_frac, force=fsb <= 17)
        if edges is None:
            continue
        dw = edges["desc"][1] - edges["desc"][0] - 2 * pad
        wrapped = [wrap(it["description"], fb, dw) for it in items]
        lh = round(fsb * 1.28)
        head_h = round(fsb * 2.9)
        tot_h = round(fsb * 2.1)
        avail = H - foot_h - bot_h - tot_h - head_h - y - 8
        for least, vpad in ((min_row, 10), (0, 10), (0, 4)):
            hts = [max(least, len(w) * lh + 2 * vpad) for w in wrapped] + ([lh + 2 * vpad] if cont else [])
            if sum(hts) + 10 <= avail:
                break
        if sum(hts) + 10 <= avail or fsb <= 17:
            break
    body_h = max(sum(hts) + 10, avail)
    H = max(H, y + head_h + body_h + tot_h + bot_h + foot_h + 8)

    # table header
    yt = y
    fdh = F(body, fsb + 3)
    for k in keys:
        xl, xr = edges[k]
        f = fdh if k == "desc" and len(heads[k]) == 1 and fdh.getlength(heads[k][0]) < xr - xl - 2 * pad else fh
        n = len(heads[k])
        for j, h in enumerate(heads[k]):
            ink.text((xl + xr) / 2, yt + head_h / 2 + (j - (n - 1) / 2) * fsb * 1.12, h, f, "mm")
    yb = yt + head_h
    ink.line(X0, yb, X1, yb, lw)

    # rows: numbers on the first line of the description, like the billing software prints them
    asc = fb.getmetrics()[0]
    yr = yb + 10
    rows = []
    for i, it in enumerate(items):
        base = yr + vpad + asc * 0.85
        db = [put(ink, "desc", t, edges["desc"], base + j * lh, fb, pad) for j, t in enumerate(wrapped[i])]
        boxes = {k: put(ink, k, cells[k][i], edges[k], base, fb, pad) for k in keys if k != "desc"}
        rows.append({"y0": int(yr), "y1": int(yr + hts[i]), "desc_bbox": union(db),
                     "qty_bbox": tuple(boxes["qty"]), "amount_bbox": tuple(boxes["amount"])})
        yr += hts[i]
        if row_lines and i < len(items) - 1:
            ink.dashes(X0, X1, yr, 1, 4, 6)
    if cont:
        put(ink, "desc", rng.choice(["continued...", "Continued...", "...continued on next page"]), edges["desc"],
            yr + vpad + asc * 0.85, F(body, fsb, True), pad)
    ybody = yb + body_h
    ink.line(X0, ybody, X1, ybody, lw)
    for k in keys:
        if k in tcells:
            put(ink, k, tcells[k], edges[k], ybody + tot_h / 2, F(body, fsb, True), pad, "m")
    ytab = ybody + tot_h
    ink.line(X0, ytab, X1, ytab, lw)
    for k in keys[1:]:
        ink.line(edges[k][0], yt, edges[k][0], ytab, lw)
    lay["table_bbox"] = (X0, int(yt), X1, int(ytab))
    lay["rows"] = rows

    y_end, boxes = _computer_bottom(ink, ytab, ctx)
    lay["total_bbox"] = boxes.get("total_bbox")
    ink.rect((X0, y_box, X1, y_end), lw + 1)
    if footer:
        ink.text(W / 2, y_end + 42, rng.choice(["This is a Computer Generated Invoice",
                                                "This is a computer generated invoice",
                                                "* This is a Computer Generated Invoice *"]), F(body, fs - 3), "ms")
    H = max(H, y_end + foot_h)

    paper_rgb = rng.choice(PAPERS[paper])
    inkc = rng.choice(LASER_INKS + CARBON_INKS[:2])
    # soft but not out of focus, and as dark as the real pink copies (inv09 photographs at
    # about the same text contrast as a white original): the photo adds its own blur and haze
    layers = [(ink.mask, inkc, dict(blur=rng.uniform(0.25, 0.5), strength=rng.uniform(0.93, 0.99),
                                    ghost=(rng.randint(1, 2), rng.randint(0, 1)) if rng.random() < 0.4 else None,
                                    smear=smear_px(body) if rng.random() < 0.25 else 0,
                                    patchy=rng.uniform(0.03, 0.12)))]
    if "sign_area" in boxes:
        layers.append((add_seal_and_sign(spec, rng, ink.mask.size, boxes["sign_area"]), rng.choice(SEAL_INKS),
                       dict(blur=0.7, strength=rng.uniform(0.55, 0.8), patchy=0.35)))
    if rng.random() < 0.55:
        layers.append((smudges((W, H), rng), rng.choice(CARBON_INKS), dict(blur=0, strength=rng.uniform(0.05, 0.12))))
    return composite(W, H, paper_rgb, layers, rng), lay


def _computer_bottom_ctx(spec, rng, st, body, fs, lp, lw, X0, X1):
    """Everything random about the bottom blocks, decided up front (the block is drawn twice)."""
    sup = spec["supplier"]
    c = {"X0": X0, "X1": X1, "xs": X0 + round((X1 - X0) * rng.uniform(0.6, 0.64)), "lp": lp, "lw": lw, "body": body,
         "fl": F(body, fs), "fb": F(body, fs, True), "fsum": F(body, fs - 1, True), "fbig": F(body, fs + 6, True),
         "ft": F(body, fs - 4, rng.random() < 0.5), "cont": spec["continued"], "num": st["num"]}
    xs = c["xs"]
    wk = rng.choice([body, "serif"])
    c["fwords"] = fit(wk, fs + 4, False, spec["amount_in_words"] or "", 3 * (xs - X0 - 60), 16)
    c["words"] = wrap(spec["amount_in_words"] or "", c["fwords"], xs - X0 - 50)
    c["words_title"] = rng.choice(["Total Invoice Amount in Words:", "Amount Chargeable (in words):",
                                   "Rupees in words:"])
    c["summary"] = summary_rows(spec, rng) if not spec["continued"] else []
    bank, c["trap"] = bank_and_trap(spec, rng)
    c["bank_kind"] = rng.choice(["serif", body])
    c["fbank"] = F(c["bank_kind"], fs - 3, True)
    both = f"{bank['name']} {bank['branch'].upper()}"
    room = (xs - X0) * 0.52 - 70 - c["fbank"].getlength("Bank & Branch")
    c["bank"] = [("Account Name", sup["name"]), ("Account No", bank["acct"])]
    c["bank"] += [("Bank & Branch", both)] if c["fbank"].getlength(both) <= room else \
        [("Bank", bank["name"]), ("Branch", bank["branch"].upper())]
    c["bank"].append(("IFSC Code", bank["ifsc"]))
    # printed lines of the bank block: a value too long for its column wraps (a long company
    # name as Account Name) instead of shrinking to an unreadable size
    c["xt"] = X0 + round((xs - X0) * 0.52)
    fbk = c["fbank"]
    c["bcol"] = X0 + 20 + max(fbk.getlength(lab) for lab, _ in c["bank"]) + 14
    room = c["xt"] - c["bcol"] - 24
    c["bank_lines"] = []
    for lab, val in c["bank"]:
        f = fit(c["bank_kind"], fbk.size, True, val, room, fbk.size - 3)
        if f.getlength(val) > room:
            f = F(c["bank_kind"], fbk.size - 2, True)
            parts = wrap(val, f, room)
        else:
            parts = [val]
        c["bank_lines"] += [(lab if j == 0 else "", t, f) for j, t in enumerate(parts)]
    c["ftrap"] = F(body, fs + 1)
    c["breakup"] = None
    if spec["tax_mode"] == "exclusive" and not spec["continued"] and rng.random() < 0.6:
        rates = sorted({it["tax_percent"] for it in spec["items"]})
        c["breakup"] = [(t, r2(sum(it["taxable"] for it in spec["items"] if it["tax_percent"] == t)),
                         r2(sum(it["cgst"] for it in spec["items"] if it["tax_percent"] == t)),
                         r2(sum(it["sgst"] for it in spec["items"] if it["tax_percent"] == t))) for t in rates]
    terms = rng.sample(TERMS, rng.randint(2, 4))
    city = sup["address_lines"][-1].split(",")[0].strip()
    if rng.random() < 0.5:
        terms.append(f"Subject to {city} Jurisdiction only.")
    c["terms"] = [ln for t in terms for ln in wrap(t, c["ft"], xs - X0 - 40)]
    ids = []
    if rng.random() < 0.6:
        ids.append(f"CIN: U{rng.randint(10000, 99999)}KL{rng.randint(2005, 2023)}PTC{rng.randint(10000, 199999):06d}")
    if sup["gstin"] and rng.random() < 0.7:
        ids.append("PAN: " + sup["gstin"][2:12])
    c["ids"] = ids
    c["eoe"] = rng.random() < 0.5
    c["seal_label"] = rng.random() < 0.6
    c["cert"] = wrap("Certified that the particulars given above are true and correct.", c["ft"], X1 - xs - 30)
    c["for"] = rng.choice(["For", "For " + sup["name"]])
    return c


def _computer_bottom(ink, y, c):
    """Totals band and terms band of the A4 invoice. Returns (bottom y, boxes)."""
    X0, X1, xs, lp, lw = c["X0"], c["X1"], c["xs"], c["lp"], c["lw"]
    M = lambda v: money(v, c["num"])
    boxes = {}
    if c["cont"]:
        ink.text(X0 + 20, y + lp + 6, "Continued on next page ...", c["fb"])
        ink.text(X1 - 20, y + lp + 6, "Page 1 of 2", c["fl"], "rs")
        y += lp + 26
        ink.line(X0, y, X1, y, lw)
    else:
        y0 = y
        # left: amount in words, optional GST break-up, then bank details and the ledger box
        yy = y0 + lp
        ink.text((X0 + xs) / 2, yy, c["words_title"], c["fb"], "ms")
        wl = round(c["fwords"].size * 1.3)
        yy += 8
        for ln in c["words"]:
            yy += wl
            ink.text(X0 + 24, yy, ln, c["fwords"])
        yy += 14
        if c["breakup"]:
            ft = c["ft"]
            tl = round(ft.size * 1.45)
            cols = [X0 + 24 + round((xs - X0 - 48) * f) for f in (0.12, 0.42, 0.64, 0.86)]
            yy += tl
            ink.text(X0 + 24, yy, "GST %", ft)
            for x, h in zip(cols, ["Taxable", "CGST", "SGST", "Total Tax"]):
                ink.text(x + 90, yy, h, ft, "rs")
            ink.dashes(X0 + 20, xs - 20, yy + 6, 1, 5, 5)
            for t, tx, cg, sg in c["breakup"]:
                yy += tl
                ink.text(X0 + 24, yy, f"{t:g}%", ft)
                for x, v in zip(cols, [tx, cg, sg, r2(cg + sg)]):
                    ink.text(x + 90, yy, M(v), ft, "rs")
            yy += 14
        trap_rh = round(c["ftrap"].size * 1.75)
        bank_h = round(c["fbank"].size * 1.4) * (len(c["bank_lines"]) + 1) + 24
        low_h = max(bank_h, 4 * trap_rh)
        left_h = yy - y0 + low_h
        n = len(c["summary"])
        sh = min(max(round(lp * 1.15), math.ceil(left_h / n)), round(lp * 1.9))
        band_h = max(left_h, n * sh)
        # right: the totals box, grand total last and biggest
        xv = xs + round((X1 - xs) * 0.56)
        for k, (lab, val, grand) in enumerate(c["summary"]):
            ry = y0 + k * sh
            if k:
                ink.line(xs, ry, X1, ry, 1)
            ink.text(xs + 10, ry + sh / 2, lab, fit(c["body"], c["fb"].size if grand else c["fsum"].size, True, lab,
                                                    xv - xs - 16), "lm")
            b = ink.text(X1 - 14, ry + sh / 2, M(val), c["fbig"] if grand else c["fb"], "rm")
            if grand:
                boxes["total_bbox"] = tuple(b)
        if n * sh < band_h:
            ink.line(xs, y0 + n * sh, X1, y0 + n * sh, 1)
        ink.line(xv, y0, xv, y0 + n * sh, 1)
        # bank details and the Previous / Closing balance box
        yl = y0 + band_h - low_h
        ink.line(X0, yl, xs, yl, lw)
        xt, bcol = c["xt"], c["bcol"]
        fbk = c["fbank"]
        bl = round(fbk.size * 1.4)
        ink.text((X0 + xt) / 2, yl + bl + 4, ": Bank Details :", c["fb"], "ms")
        by = yl + bl + 10
        for lab, val, f in c["bank_lines"]:
            by += bl
            if lab:
                ink.text(X0 + 20, by, lab, fbk)
                ink.text(bcol, by, ":", fbk)
            ink.text(bcol + 14, by, val, f)
        ink.line(xt, yl, xt, y0 + band_h, lw)
        ty = y0 + band_h - 4 * trap_rh
        xtv = xt + round((xs - xt) * 0.55)
        for k, (lab, val) in enumerate(c["trap"]):
            ry = ty + k * trap_rh
            if k:
                ink.line(xt, ry, xs, ry, 1)
            ink.text(xt + 10, ry + trap_rh / 2, lab, fit(c["body"], c["ftrap"].size, False, lab, xtv - xt - 14), "lm")
            ink.text(xs - 10, ry + trap_rh / 2, M(val), c["fb"], "rm")
        ink.line(xtv, ty, xtv, y0 + band_h, 1)
        ink.line(xs, y0, xs, y0 + band_h, lw)
        y = y0 + band_h
        ink.line(X0, y, X1, y, lw)
    # terms and the signatory box
    ft = c["ft"]
    tl = round(ft.size * 1.45)
    yy = y + lp
    ink.text(X0 + 14, yy, "Terms & Condition :-", c["fb"])
    for ln in c["terms"]:
        yy += tl
        ink.text(X0 + 14, yy, ln, ft)
    yy += tl // 2
    for t in c["ids"]:
        yy += tl
        ink.text(X0 + 14, yy, t, ft)
    ry = y + 6
    for ln in c["cert"]:
        ry += tl
        ink.text(xs + 12, ry, ln, ft)
    ry += round(lp * 1.4)
    ink.text(xs + 40, ry, c["for"], fit(c["body"], c["fb"].size, True, c["for"], X1 - xs - 60))
    h = max(yy - y + 50, ry - y + 150 + lp)
    ink.text(X1 - 20, y + h - 16, "Authorised Signatory", c["fb"], "rs")
    if c["seal_label"]:
        ink.text(xs - 150, y + h - 16, "(Common Seal)", ft, "ms")
    if c["eoe"]:
        ink.text(X0 + 14, y + h - 16, "E.&O.E", ft)
    ink.line(xs, y, xs, y + h, c["lw"])
    boxes["sign_area"] = (xs + 10, int(ry + 12), X1 - 10, int(y + h - 16 - lp))
    return y + h, boxes


# ---------------------------------------------------------------- pre-printed bill-book form (AVEES)

def _form(spec, rng):
    sup, buyer, items = spec["supplier"], spec["buyer"], spec["items"]
    tax, cont = spec["tax_mode"], spec["continued"]
    # an A5 landscape book has room for about eight rows; longer bills come on portrait books
    portrait = rng.random() < 0.45 or len(items) > 6
    if portrait:
        W = rng.randint(1150, 1280)
        H = round(W * rng.uniform(1.38, 1.45))
    else:
        W = rng.randint(1480, 1580)
        H = round(W * rng.uniform(0.71, 0.78))
    paper = rng.choice(["pink"] * 5 + ["yellow"] * 3 + ["green", "white"])
    X0, X1 = rng.randint(45, 80), W - rng.randint(45, 80)
    BW = X1 - X0
    top = rng.randint(100, 150)
    st = {"num": num_style(rng.choice(["plain", "plain", "comma", "indian", "trim"]), items),
          "qdec": rng.choice([0, 0, 2, 3]),
          "pct": "pct", "sl_dot": False}
    pf = rng.choice(["sans", "sans2", "narrow", "serif"])          # pre-printed labels
    ff = rng.choice(["typewriter", "typewriter", "narrow"])  # the printer's fill (no slashed zeros)
    fbold = rng.random() < (0.75 if ff == "typewriter" else 0.45)   # thin Courier fades on a carbon
    lfs = rng.randint(20, 23) if portrait else rng.randint(21, 24)
    ffs = rng.randint(21, 24)
    lw = rng.choice([2, 2, 3])
    size = (W, H + 4000)
    form, acc = Ink(size), Ink(size)
    fill = Ink(size, (rng.randint(-6, 5), rng.randint(-6, 4)))
    fl, fv = F(pf, lfs), F(ff, ffs, fbold)
    lay = {"paper": paper, "style": "form"}

    # letterhead: name on top, GSTIN block left, phones right, brand + address between
    hb = []
    cx = (X0 + X1) / 2
    nk = rng.choice(["serif", "serif", "condensed"])
    nbold = nk == "condensed" or rng.random() < 0.5
    nsx = rng.uniform(1.0, 1.08) if nk == "serif" and not nbold else rng.uniform(0.82, 0.95)
    ns = rng.randint(48, 58) if portrait else rng.randint(54, 66)
    while ns > 26 and F(nk, ns, nbold).getlength(sup["name"]) * nsx > BW - 20:
        ns -= 2
    y = top + round(ns * 0.75)
    hb.append(acc.squeezed(cx, y, sup["name"], F(nk, ns, nbold), nsx, "ms"))
    fc = F(pf, lfs + 1)
    left = (["GSTIN : " + sup["gstin"]] if sup["gstin"] else []) + [f"State Code {sup['state_code']}"]
    std = rng.choice(STD_CODES.get(sup["state"], STD_CODES["Kerala"]))
    right = [f"Phone : {std} - {rng.randint(2200000, 2899999)}", "Mob : " + sup["phone"]]
    if sup["email"]:
        right.append("E-mail : " + sup["email"])
    fg = F(pf, lfs + 2)
    cw = max([fc.getlength(s) for s in right] + [(fg if s.startswith("GSTIN") else fc).getlength(s) for s in left])
    cl = round(lfs * 1.32)
    yl = y + 10
    for s in left:
        yl += cl
        hb.append(form.text(X0, yl, s, fg if s.startswith("GSTIN") else fc))
    yr = y + 10
    for s in right:
        yr += cl
        hb.append(form.text(X1, yr, s, fc, "rs"))
    centre_w = BW - 2 * cw - 50
    yc = y + 6
    if rng.random() < 0.55:
        brand = sup["name"].split()[0].strip(".,") + " " + BRAND_WORDS.get(spec["supplier_kind"], "TRADERS")
        bs = rng.randint(34, 42)
        yc += round(bs * 1.1)
        hb.append(acc.text(cx, yc, brand, fit("condensed" if rng.random() < 0.5 else "serif", bs, True, brand,
                                                centre_w), "ms"))
    addr = ", ".join(sup["address_lines"])
    fa = F(pf, lfs + 1)
    parts = [addr] if fa.getlength(addr) <= centre_w else list(sup["address_lines"])
    for s in parts:
        yc += round(lfs * 1.35)
        hb.append(form.text(cx, yc, s, fit(pf, lfs + 1, False, s, centre_w), "ms"))
    lay["header_bbox"] = union(hb)
    lay["notes_area"] = (round(W * 0.55), 14, X1, max(50, lay["header_bbox"][1] - 8))
    y_box = lay["header_bbox"][3] + rng.randint(12, 22)

    # upper box: receiver | vendor / PO fields | INVOICE B2B + number + date
    c2, c3 = X0 + round(BW * 0.41), X0 + round(BW * (0.70 if portrait else 0.72))
    up = round(lfs * rng.uniform(1.6, 1.8))
    y = y_box
    form.text((X0 + c2) / 2, y + up * 0.62, rng.choice(["Details of Receiver | Billed to :", "Billed to :",
                                                        "Details of Receiver"]), F(pf, lfs - 1), "ms")
    rows_a = [("Name", buyer["display"]), ("", buyer["address_lines"][0] if rng.random() < 0.5 else ""),
              ("GST No :", buyer["gstin"]), ("State Code :", "32")]
    # a long name runs on to the next dotted line rather than shrinking out of legibility
    room = c2 - (X0 + 14 + fl.getlength("Name") + 8) - 40
    if F(ff, ffs - 3, fbold).getlength(buyer["display"]) > room:
        lines = wrap(buyer["display"], F(ff, ffs - 2, fbold), room)
        rows_a[0] = ("Name", lines[0])
        rows_a[1] = ("", " ".join(lines[1:]))
    ya = y + up * 0.35
    for lab, val in rows_a:
        ya += up
        x = X0 + 14
        if lab:
            form.text(x, ya, lab, fl)
            x += fl.getlength(lab) + 8
        form.dots(x, c2 - 14, ya + 3)
        if val:
            fill.text(x + 10, ya - 4, val, fit(ff, ffs, fbold, val, c2 - x - 40))
    yb = y + up * 0.35
    fields = ["Vendor Code :", "Store Code :", "Purchase Order No :", "P.O.Date :"]
    po = rng.random() < 0.25
    for k, lab in enumerate(fields):
        yb += up
        form.text(c2 + 12, yb, lab, fl)
        x = c2 + 12 + fl.getlength(lab) + 6
        form.dots(x, c3 - 12, yb + 3)
        if po and k == 2:
            po_no = f"PO/{rng.randint(1000, 9999)}"
            fpo = fit(ff, ffs, fbold, po_no, c3 - x - 30, ffs - 4)
            if fpo.getlength(po_no) <= c3 - x - 30:     # never shrunk tiny or run into the invoice box
                fill.text(x + 10, yb - 4, po_no, fpo)
    form.line(c3, y, c3, y + up * 4.7, lw)
    bh = round(up * 1.3)
    split = c3 + round((X1 - c3) * 0.58)
    form.line(c3, y + bh, X1, y + bh, lw)
    form.line(split, y, split, y + bh, lw)
    t1, t2 = rng.choice([("INVOICE", "B2B"), ("TAX INVOICE", "B2B"), ("INVOICE", "DUPLICATE"), ("BILL", "B2B")])
    form.text((c3 + split) / 2, y + bh / 2, t1, fit(pf, lfs + 10, True, t1, split - c3 - 16), "mm")
    form.text((split + X1) / 2, y + bh / 2, t2, fit(pf, lfs + 10, True, t2, X1 - split - 16), "mm")
    yi = y + bh + up * 0.95
    form.text(c3 + 12, yi, rng.choice(["Invoice No.", "Invoice No", "Bill No."]), fl)
    yi += round(up * 0.95)
    inv = spec["invoice_number_printed"]
    serial = None
    if inv.isdigit() and rng.random() < 0.7:
        # a numbered bill book: the serial was printed in red when the book was made
        serial = Ink(size)
        nk = rng.choice(["serif", "condensed"])
        lay["invoice_number_bbox"] = serial.text(c3 + 30, yi + 2, inv, fit(nk, ffs + 6, True, inv, X1 - c3 - 50))
    else:
        lay["invoice_number_bbox"] = fill.text(c3 + 30, yi, inv, fit(ff, ffs + 3, True, inv, X1 - c3 - 50))
    yi += round(up * 0.95)
    form.text(c3 + 12, yi, "Date", fl)
    xd = c3 + 12 + fl.getlength("Date") + 6
    form.dots(xd, X1 - 12, yi + 3)
    lay["date_bbox"] = fill.text(xd + 14, yi - 4, spec["date_printed"], fit(ff, ffs + 1, True, spec["date_printed"],
                                                                           X1 - xd - 30))
    y = round(max(ya, yb, yi) + up * 0.45)
    form.line(X0, y, X1, y, lw)

    # table columns; sometimes the supplier's product list is pre-printed on the form and
    # only the bought rows are filled (the other printed products are not items)
    if tax == "inclusive":
        keys = ["sl", "desc", "hsn", "gst", "uom", "rate", "qty", "taxable", "cgst", "sgst", "amount"]
    elif tax == "exclusive":
        keys = ["sl", "desc", "hsn", "gst", "uom", "qty", "rate", "amount"]
    else:
        keys = ["sl", "desc", "hsn", "uom", "qty", "rate", "amount"]
    if rng.random() < 0.5:
        qi, ri = keys.index("qty"), keys.index("rate")
        keys[qi], keys[ri] = "rate", "qty"
    rates = {it["tax_percent"] for it in items}
    half = f"{list(rates)[0] / 2:g}%" if len(rates) == 1 else "Amount"
    heads = {"sl": ["Sl", "No."], "desc": [rng.choice(["Name of Product", "Particulars", "Description of Goods"])],
             "hsn": ["HSN", "Code"], "gst": ["Rate", "of Tax"], "uom": ["UOM"], "rate": rng.choice([["Rate"],
             ["Rate /", "Unit"]]), "qty": ["Qty."], "taxable": ["Taxable", "Amount"], "cgst": ["CGST", half],
             "sgst": ["SGST", half], "amount": ["TOTAL"] if tax == "inclusive" else rng.choice([["Amount"], ["Value"]])}
    product_list = (not cont and rng.random() < 0.35 and len(items) <= 10
                    and spec["supplier_kind"] in CATALOG)
    printed = [("item", i) for i in range(len(items))]
    if product_list:
        have = {it["description"] for it in items}
        extra = [row for row in CATALOG[spec["supplier_kind"]] if row[0] not in have]
        n_extra = rng.randint(2, 6) if portrait else min(rng.randint(2, 5), 8 - len(items))
        for row in rng.sample(extra, max(0, min(len(extra), n_extra))):
            printed.insert(rng.randint(0, len(printed)), ("pre", row))
    cells = {k: [cell_text(k, i, it, st) for i, it in enumerate(items)] for k in keys}
    cells["sl"] = ["88"]
    tcells = total_cells(keys, spec, st, rng.random() < 0.4)
    for k in keys:
        cells[k] = cells[k] + [tcells.get(k, "")] + [str(r[1][1]) for r in printed if r[0] == "pre" and k == "hsn"]
    ctx = _form_bottom_ctx(spec, rng, st, pf, ff, fbold, lfs, ffs, lw, X0, X1, BW)
    form.dry = fill.dry = True
    bot_h = _form_bottom(form, fill, 0, ctx)[0]
    form.dry = fill.dry = False

    pad = 13       # values are printed off-register: keep them clear of the column rules
    fh = F(pf, lfs - 1)
    head_h = round(lfs * 2.7)
    tot_h = round(lfs * 1.9)
    row_h = round(ffs * (rng.uniform(1.75, 2.1) if portrait else rng.uniform(1.6, 1.85)))
    dfrac = rng.uniform(0.24, 0.3)
    for fsz in range(ffs, 12, -1):
        fb = F(ff, fsz, fbold)
        edges = fit_columns(keys, heads, cells, fb, fh, X0, X1, pad, dfrac, 0.2, force=fsz == 13)
        if edges is not None:
            break
    dw = edges["desc"][1] - edges["desc"][0] - 2 * pad
    # one type size for every description, as a printer (or the form's own type) has: a few
    # points smaller if that keeps every name on one line, else long names wrap to a second
    # line (shrinking only if even two lines are not enough); every row gets the tallest height
    on_form = product_list
    texts = [items[ref]["description"] if kind == "item" else ref[0] for kind, ref in printed]
    base = lfs - 3 if on_form else fsz      # pre-printed product names are set small (AVEES)

    def desc_lines(size):
        f = F(pf, size) if on_form else F(ff, size, fbold)
        return f, [wrap(t, f, dw) for t in texts]
    for s in range(base, max(base - 5, 15), -1):
        f, wrapped = desc_lines(s)
        if all(len(w) == 1 for w in wrapped):
            break
    else:
        for s in range(base, min(base, 16) - 1, -1):
            f, wrapped = desc_lines(s)
            if max([len(w) for w in wrapped] + [1]) <= 2:
                break
    # (filled-in names also need room for the printer's misregistration)
    n_lines = max([len(w) for w in wrapped] + [1])
    row_h = max(row_h, math.ceil(n_lines * s * 1.15 + 12 + (0 if on_form else 2 * abs(fill.oy))))
    descs = [(f, w, on_form) for w in wrapped]
    avail = H - (40 if ctx["juris"] else 24) - bot_h - tot_h - head_h - y
    n_rows = max(len(printed) + (1 if cont else 0), int(avail // row_h))
    if portrait:
        n_rows = min(n_rows, max(len(printed) + (1 if cont else 0), 22))
    body_h = max(n_rows * row_h, avail)
    row_h = body_h / n_rows
    H = max(H, round(y + head_h + body_h + tot_h + bot_h + (40 if ctx["juris"] else 24)))

    yt = y
    for k in keys:
        xl, xr = edges[k]
        n = len(heads[k])
        for j, h in enumerate(heads[k]):
            form.text((xl + xr) / 2, yt + head_h / 2 + (j - (n - 1) / 2) * lfs * 1.08, h,
                      fit(pf, lfs - 1, k == "desc", h, xr - xl - 6), "mm")
    yb = yt + head_h
    form.line(X0, yb, X1, yb, lw)
    rows = []
    fsl = F(pf, lfs - 2)
    for r in range(n_rows):
        ry0 = yb + r * row_h
        mid = ry0 + row_h / 2
        if r:
            form.line(X0, ry0, X1, ry0, 1)
        form.text((edges["sl"][0] + edges["sl"][1]) / 2, cap_mid(fsl, mid), str(r + 1), fsl, "ms")
        if r >= len(printed):
            if cont and r == len(printed):
                fill.text(edges["desc"][0] + pad, cap_mid(fv, mid), "continued...", fv)
            continue
        kind, ref = printed[r]
        f, lines, on_form = descs[r]
        ink = form if on_form else fill
        lh = f.size * 1.15
        db = [ink.text(edges["desc"][0] + pad, cap_mid(f, mid + (j - (len(lines) - 1) / 2) * lh), ln, f)
              for j, ln in enumerate(lines)]
        if kind == "pre":
            form.text((edges["hsn"][0] + edges["hsn"][1]) / 2, cap_mid(fsl, mid), ref[1], fsl, "ms")
            if "gst" in edges:
                form.text((edges["gst"][0] + edges["gst"][1]) / 2, cap_mid(fsl, mid), f"{ref[5]}%", fsl, "ms")
            continue
        i = ref
        boxes = {}
        for k in keys:
            if k in ("sl", "desc"):
                continue
            if on_form and k in ("hsn", "gst"):
                boxes[k] = form.text((edges[k][0] + edges[k][1]) / 2, cap_mid(fsl, mid), cells[k][i], fsl, "ms")
            else:
                boxes[k] = put(fill, k, cells[k][i], edges[k], mid, fb, pad, "m")
        rows.append({"y0": int(ry0), "y1": int(ry0 + row_h), "desc_bbox": union(db),
                     "qty_bbox": tuple(boxes["qty"]), "amount_bbox": tuple(boxes["amount"])})
    ybody = yb + body_h
    form.line(X0, ybody, X1, ybody, lw)
    form.text((edges["desc"][0] + edges["desc"][1]) / 2, ybody + tot_h / 2, "TOTAL", F(pf, lfs + 2, True), "mm")
    for k in keys:
        if k in tcells:
            put(fill, k, tcells[k], edges[k], ybody + tot_h / 2, fb, pad, "m")
    ytab = ybody + tot_h
    form.line(X0, ytab, X1, ytab, lw)
    for k in keys[1:]:
        form.line(edges[k][0], yt, edges[k][0], ybody if k == "desc" else ytab, lw)
    lay["table_bbox"] = (X0, int(yt), X1, int(ytab))
    lay["rows"] = rows

    y_end, boxes = _form_bottom(form, fill, ytab, ctx)
    lay["total_bbox"] = boxes.get("total_bbox")
    form.rect((X0, y_box, X1, y_end), lw)
    if ctx["juris"]:
        form.text(cx, y_end + 26, f"Subject to {ctx['city']} Jurisdiction", ctx["fs"], "ms")
    H = max(H, y_end + (40 if ctx["juris"] else 24))

    paper_rgb = rng.choice(PAPERS[paper])
    form_c = rng.choice(FORM_INKS)
    acc_c = rng.choice(ACCENT_INKS) if rng.random() < 0.4 else form_c
    layers = [(form.mask, form_c, dict(blur=rng.uniform(0.35, 0.6), strength=rng.uniform(0.85, 0.97),
                                       patchy=rng.uniform(0.0, 0.12))),
              (acc.mask, acc_c, dict(blur=0.5, strength=rng.uniform(0.85, 0.97))),
              (fill.mask, rng.choice(CARBON_INKS), dict(blur=rng.uniform(0.3, 0.55), strength=rng.uniform(0.9, 0.98),
                                                        ghost=(rng.randint(1, 2), rng.randint(-1, 1))
                                                        if rng.random() < 0.7 else None,
                                                        smear=smear_px(ff) if rng.random() < 0.3 else 0,
                                                        patchy=rng.uniform(0.08, 0.22)))]
    if serial:
        layers.append((serial.mask, rng.choice(SERIAL_INKS), dict(blur=0.45, strength=rng.uniform(0.82, 0.95),
                                                                   patchy=0.2)))
    if "sign_area" in boxes:
        layers.append((add_seal_and_sign(spec, rng, form.mask.size, boxes["sign_area"]), rng.choice(SEAL_INKS),
                       dict(blur=0.7, strength=rng.uniform(0.55, 0.8), patchy=0.35)))
    if paper != "white" and rng.random() < 0.55:
        layers.append((smudges((W, H), rng), rng.choice(CARBON_INKS), dict(blur=0, strength=rng.uniform(0.05, 0.12))))
    return composite(W, H, paper_rgb, layers, rng), lay


def _form_bottom_ctx(spec, rng, st, pf, ff, fbold, lfs, ffs, lw, X0, X1, BW):
    sup = spec["supplier"]
    c = {"X0": X0, "X1": X1, "ca": X0 + round(BW * 0.31), "cb": X0 + round(BW * 0.64), "lw": lw,
         "fl": F(pf, lfs), "flb": F(pf, lfs, True), "fs": F(pf, lfs - 3), "fv": F(ff, ffs, fbold),
         "fvb": F(ff, ffs + 2, True), "num": st["num"], "cont": spec["continued"], "pf": pf, "ff": ff,
         "fbold": fbold, "lfs": lfs, "ffs": ffs}
    bank, c["trap"] = bank_and_trap(spec, rng)
    c["bank"] = [("Name of Bank", bank["name"].title()), ("Branch", bank["branch"]), ("Account Number", bank["acct"]),
                 ("Bank IFSC Code", bank["ifsc"])]
    tot, tax = spec["totals"], spec["tax_mode"]
    if spec["continued"]:
        c["summary"] = [("Total Amount Before Tax", None, False), ("Total Amount", None, True)]
    elif tax == "none":
        c["summary"] = [("Gross Amount", tot["subtotal"], False)]
        if tot["round_off"] or rng.random() < 0.5:
            c["summary"].append(("Round Off", tot["round_off"], False))
        c["summary"].append(("Net Amount", tot["grand_total"], True))
    else:
        c["summary"] = [("Total Amount Before Tax", tot["subtotal"], False), ("Total CGST", tot["cgst"], False),
                        ("Total SGST", tot["sgst"], False)]
        if rng.random() < 0.6:
            c["summary"].append(("Total Tax", r2(tot["cgst"] + tot["sgst"]), False))
        if tot["round_off"] or rng.random() < 0.4:
            c["summary"].append(("Round Off", tot["round_off"], False))
        c["summary"].append(("Total Amount", tot["grand_total"], True))
    words = spec["amount_in_words"] or ""
    ww = c["cb"] - c["ca"] - 36
    for s in range(ffs, 14, -1):
        c["fw"] = F(ff, s, fbold)
        c["words"] = wrap(words, c["fw"], ww)
        if len(c["words"]) <= 2:
            break
    c["for"] = "For " + sup["name"].title().replace("Pvt.", "Pvt").replace("Ltd.", "Ltd")
    c["eoe"] = rng.choice(["(E.&O.E)", "E. & O.E.", "(E & OE)"])
    c["juris"] = rng.random() < 0.5
    c["city"] = sup["address_lines"][-1].split(",")[0].strip()
    return c


def _form_bottom(form, fill, y, c):
    """Bank + ledger box | words, certificate, signatory | totals. Returns (bottom y, boxes)."""
    X0, X1, ca, cb, lw = c["X0"], c["X1"], c["ca"], c["cb"], c["lw"]
    fl, flb, fs, fv = c["fl"], c["flb"], c["fs"], c["fv"]
    M = lambda v: money(v, c["num"])
    boxes = {}
    pitch = round(c["lfs"] * 1.5)
    # bank details
    yy = y + pitch
    b = form.text((X0 + ca) / 2, yy, "Bank Details", F(c["pf"], c["lfs"] + 2, True), "ms")
    form.line(b[0], b[3] + 3, b[2], b[3] + 3, 1)
    bcol = X0 + 12 + max(fs.getlength(lab) for lab, _ in c["bank"]) + 8
    for lab, val in c["bank"]:
        yy += round(pitch * 0.78)
        form.text(X0 + 12, yy, lab, fs)
        form.text(bcol, yy, ": " + val, fit(c["pf"], fs.size, False, ": " + val, ca - bcol - 10))
    yy += round(pitch * 0.6)
    if c["trap"]:
        th = round(pitch * 0.86)
        xv = X0 + round((ca - X0) * 0.55)
        form.line(X0, yy, ca, yy, 1)
        for lab, val in c["trap"]:
            form.text(X0 + 12, yy + th / 2, lab, fit(c["pf"], fs.size + 1, False, lab, xv - X0 - 18), "lm")
            fv2 = fit(c["ff"], c["ffs"] - 1, c["fbold"], M(val), ca - xv - 16)
            fill.text(ca - 10, cap_mid(fv2, yy + th / 2), M(val), fv2, "rs")
            yy += th
            form.line(X0, yy, ca, yy, 1)
        form.line(xv, yy - 4 * th, xv, yy, 1)
    h_a = yy - y + 10
    # amount in words, certificate, signatory
    yw = y + pitch
    form.text((ca + cb) / 2, yw, "Total Invoice Amount in words", fl, "ms")
    wl = round(pitch * 1.05)
    for k in range(max(2, len(c["words"]))):   # never drop a wrapped line of the words
        yw += wl
        form.dots(ca + 14, cb - 14, yw + 4)
        if k < len(c["words"]):
            fill.text(ca + 18, yw - 2, c["words"][k], c["fw"])
    yw += round(pitch * 1.1)
    for ln in wrap("Certified that the Particulars given above are true and correct", fs, cb - ca - 30):
        form.text((ca + cb) / 2, yw, ln, fs, "ms")
        yw += round(fs.size * 1.3)
    yw += round(pitch * 0.4)
    form.text((ca + cb) / 2, yw, c["for"], fit(c["pf"], c["lfs"] + 1, True, c["for"], cb - ca - 24), "ms")
    sig_top = yw + 8
    yw += round(pitch * 2.4)
    sb = form.text((ca + cb) / 2, yw, "Authorised Signatory", fs, "ms")
    if fs.getlength(c["eoe"]) < cb - 20 - sb[2]:
        form.text(cb - 12, yw, c["eoe"], fs, "rs")
    else:
        yw += round(pitch * 0.8)
        form.text(cb - 12, yw, c["eoe"], fs, "rs")
    h_b = yw - y + 12
    boxes["sign_area"] = (ca + 10, int(sig_top), cb - 10, int(sb[1] - 4))
    # totals
    n = len(c["summary"])
    rh = round(pitch * 1.25)
    h = max(h_a, h_b, n * rh + 10)
    rh = (h - 10) / n
    xv = cb + round((X1 - cb) * 0.6)
    for k, (lab, val, grand) in enumerate(c["summary"]):
        ry = y + 5 + k * rh
        lines = wrap(lab, fl, xv - cb - 30)
        for j, ln in enumerate(lines):
            form.text(cb + 12, ry + rh / 2 + (j - (len(lines) - 1) / 2) * fl.size * 1.1, ln, flb if grand else fl, "lm")
        form.text(xv - 8, ry + rh / 2, ":", fl, "rm")
        if k:
            form.line(cb, ry, X1, ry, 1)
        if val is not None:
            f = c["fvb"] if grand else fv
            f = fit(c["ff"], f.size, grand or c["fbold"], M(val), X1 - xv - 18)
            bb = fill.text(X1 - 14, cap_mid(f, ry + rh / 2), M(val), f, "rs")
            if grand:
                boxes["total_bbox"] = tuple(bb)
    form.line(ca, y, ca, y + h, lw)
    form.line(cb, y, cb, y + h, lw)
    return y + h, boxes


# ---------------------------------------------------------------- entry point

def render(spec, rng):
    """Draw one carbon-copy bill for `spec`. Returns (RGB page, layout)."""
    page, lay = (_computer if rng.random() < 0.6 else _form)(spec, rng)
    W, H = page.size
    # keep every box on the page (ink offsets can push a fill box a few pixels out)
    clip = lambda b: (max(0, min(W - 1, int(b[0]))), max(0, min(H - 1, int(b[1]))),
                      max(0, min(W - 1, int(b[2]))), max(0, min(H - 1, int(b[3])))) if b else b
    for k in ("table_bbox", "header_bbox", "invoice_number_bbox", "date_bbox", "total_bbox", "notes_area"):
        lay[k] = clip(lay.get(k))
    for r in lay["rows"]:
        r["y0"], r["y1"] = max(0, r["y0"]), min(H - 1, r["y1"])
        for k in ("desc_bbox", "qty_bbox", "amount_bbox"):
            r[k] = clip(r[k])
    return page, lay
