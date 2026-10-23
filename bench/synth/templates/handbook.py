"""Hand-filled bill book ("handbook").

A small vendor's pre-printed cash-bill pad - egg, mushroom, cut-vegetable and
microgreen sellers - modelled on A.K.S. Traders (inv08), Aadidev Mushroom World
(inv10), Eggs Daily (inv11), hyleaf / Uptown Urban Farms (inv13), Dr. Growmush
(inv14) and Thalir Fresh (inv15) in eval/samples.

The printer's parts (letterhead, logo, red serial number, grid, labels, dotted
lines, small print and sometimes a list of product names) are drawn with print
fonts in one or two ink colours. Everything the vendor fills in (date, customer,
rows, totals, amount in words) is written with one pen for the whole bill.

The page is drawn on a tall canvas and cropped at the end, so the grid can grow
for long bills while short bills keep the empty rows a real pad has.
"""
import math

import numpy as np
from PIL import Image, ImageDraw

from bench.synth import hand
from bench.synth.spec import CATALOG

PAPERS = {"white": (250, 250, 246), "cream": (247, 241, 223), "pink": (248, 227, 231),
          "yellow": (250, 244, 200), "green": (226, 242, 228)}
# mostly white originals, like the store's real bill books; some coloured duplicate pads
PAPER_WEIGHTS = {"white": 62, "cream": 20, "pink": 8, "yellow": 7, "green": 3}
# inks of cheap offset-printed bill books
PRINT_INKS = {"black": (30, 30, 36), "navy": (30, 46, 122), "maroon": (128, 30, 42), "green": (26, 92, 60),
              "violet": (80, 48, 128), "brown": (98, 54, 32)}
SERIAL_REDS = [(206, 36, 44), (190, 30, 54), (214, 54, 42)]
# GochiHand is left out: its 1 reads as 7 and its 5 as S, and these pens write the ground truth
HAND_FONTS = {"Kalam-Regular.ttf": 30, "Kalam-Light.ttf": 14, "Kalam-Bold.ttf": 10, "PatrickHand-Regular.ttf": 20,
              "Caveat.ttf": 18, "ReenieBeanie.ttf": 5}
HAND_INKS = {"blue": 45, "blue_light": 15, "black": 30, "violet": 5, "green": 5}
BOLD_TWIN = {"serif": "serif_bold", "typewriter": "typewriter_bold"}
RUPEE_FONTS = {"sans", "narrow", "condensed"}       # PT Serif draws U+20B9 like a ruble sign

TAGLINES = {
    "eggs": ["NADAN EGGS SUPPLIERS", "Wholesale Egg Dealers", "Farm Fresh Eggs",
             "Dealers in : Chicken, Nadan, Quail & Duck Eggs"],
    "mushroom": ["PREMIUM OYSTER HARVEST", "Fresh Mushrooms Daily", "Mushroom Cultivation & Supply",
                 "MUSH LOVE FOR LIFE"],
    "cut_veg": ["WHOLE SALE - ORGANIC & NADAN VEGETABLES", "Fresh Cut Vegetables", "Ready to Cook Vegetables"],
    "microgreens": ["fresh.hydroponic", "Hydroponic Greens & Microgreens", "Pesticide Free Greens"],
    "veg": ["Wholesale Vegetable Merchants", "Vegetable Commission Agents", "Dealers in Fresh Vegetables"],
    "fruit": ["Fruits Wholesale & Retail", "Fresh Fruit Merchants", "Dealers in Fruits & Vegetables"],
    "bakery": ["Bakery Products Distributors", "Bread, Rusk & Cakes", "Bakery Suppliers"],
}
TITLES = ["CASH BILL", "CASH/CREDIT SALES", "CASH / CREDIT BILL", "BILL", "CREDIT BILL", "INVOICE", "CASH MEMO"]
INVOCATIONS = ["|| Om Sri Ganeshaya Namah ||", "|| Sree Ayyappa Saranam ||", "Jesus is my Shepherd",
               "|| Om Namah Shivaya ||", "|| Sree Guruvayurappa Saranam ||", "In God We Trust"]
TERMS = ["Goods once sold will not be taken back.", "Subject to {city} Jurisdiction.",
         "Certified that the particulars given above are true and correct.",
         "Interest @ 18% p.a. will be charged on bills unpaid after 30 days.", "Thank You, Visit Again!",
         "No Exchange, No Return.", "Please check the goods before accepting."]
PRINTERS = ["Printed at: Sree Durga Printers, {city}", "Bharath Offset, {city}", "St. Mary's Press, {city}",
            "Akshara Graphics, {city}", "Jyothi Printers & Binders, {city}", "Printed by: Sabari Offset, {city}"]
SIGN_NAMES = ["Rajesh", "S. Kumar", "Anil K", "Jose", "Biju", "M Nair", "Shaji", "Rafeeq", "Suresh", "Thomas", "AK",
              "P.V", "Joseph", "Vinod", "Sajeev", "Babu", "Hari", "Rasheed", "J. Mathew", "Unni"]
BANKS = [("State Bank of India", "SBIN"), ("Federal Bank", "FDRL"), ("South Indian Bank", "SIBL"),
         ("Canara Bank", "CNRB"), ("IndusInd Bank", "INDB"), ("ICICI Bank", "ICIC")]

COLUMN_SETS = [
    ["sl", "desc", "rate", "qty", "amount"],           # Thalir Fresh
    ["qty", "hsn", "desc", "rate", "amount"],          # Eggs Daily
    ["desc", "hsn", "qty", "rate", "amount"],          # A.K.S. Traders
    ["sl", "desc", "qty", "rate", "amount"],           # Dr. Growmush, hyleaf, Aadidev
    ["sl", "desc", "qty", "unit", "rate", "amount"],
    ["sl", "desc", "hsn", "qty", "unit", "rate", "amount"],
]
COL_WEIGHT = {"sl": 0.07, "desc": 0.40, "hsn": 0.10, "qty": 0.10, "unit": 0.09, "rate": 0.11, "mrp": 0.10,
              "gst": 0.07, "amount": 0.16}
COL_LABELS = {
    "sl": ["Sl.\nNo.", "Sl.No", "S.No.", "No."],
    "desc": ["Particulars", "Item", "Description", "Particulars/ Item", "PARTICULARS", "Description of Goods"],
    "hsn": ["HSN\nCode", "HSN Code", "HSN"],
    "qty": ["Qty", "Qty.", "Quantity", "Nos."],
    "unit": ["Unit", "UOM"],
    "rate": ["Rate", "Rate\nRs.", "Price"],
    "mrp": ["MRP"],
    "gst": ["GST\n%", "Tax\n%"],
    "amount": ["Amount", "Amount\nRs.", "AMOUNT", "Total"],
}


def _pick(rng, weights):
    """Weighted choice from a {value: weight} dict."""
    keys = list(weights)
    return rng.choices(keys, [weights[k] for k in keys])[0]


def _union(*boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _group_indian(n):
    """1234567 -> '12,34,567'."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def recase(text, style):
    """An item name the way this vendor writes it (or the printer set it): as given (capitals),
    Title Case or Sentence case. The scorer compares descriptions case-insensitively."""
    if style == "upper":
        return text
    out = []
    for k, w in enumerate(text.lower().split(" ")):
        j = 1 if w[:1] == "(" else 0
        if (style == "title" or k == 0) and w[j:j + 1].isalpha():
            w = w[:j] + w[j].upper() + w[j + 1:]
        out.append(w)
    return " ".join(out)


def qty_text(q):
    if isinstance(q, float) and q.is_integer():
        return str(int(q))
    return f"{q:g}" if isinstance(q, float) else str(q)


class Pen:
    """The vendor's pen for this bill: one hand font, ink, slant and sloppiness.

    Text is first written on a scratch canvas (white on black) so the ink's exact
    size is known before it lands on the page; that gives tight bboxes and lets
    numbers be right-aligned or shrunk to fit a cell. The scratch canvas is used
    with the same rng calls a direct hand.hand_text call would make.
    """

    def __init__(self, page, rng, font_name, ink, jitter, slant):
        self.page, self.rng, self.font, self.jitter, self.slant = page, rng, font_name, jitter, slant
        self.ink = hand.INKS.get(ink, ink) if isinstance(ink, str) else ink
        f = hand.font(font_name, 100)
        b = f.getbbox("8")
        self.scale = 72 / max(30, b[3] - b[1])   # same digit height whatever the font

    def render(self, text, size):
        """Returns (coverage mask cropped to the ink, (dx, dy) of its top-left from the pen origin)."""
        size = max(9, int(size))
        pad = size * 2
        w = int(hand.text_width(text, int(size * 1.15), self.font) * 1.12) + 2 * pad
        canvas = Image.new("RGB", (w, size * 4), (0, 0, 0))
        base = int(size * 2.4)
        hand.hand_text(canvas, (pad, base), text, size, self.rng, font_name=self.font, ink=(255, 255, 255),
                       slant=self.slant + self.rng.uniform(-1.5, 1.5), jitter=self.jitter)
        mask = canvas.getchannel("G")
        box = mask.point(lambda v: 255 if v > 50 else 0).getbbox()
        if box is None:
            return None, (0, 0)
        return mask.crop(box), (box[0] - pad, box[1] - base)

    def width(self, text, size):
        """Rough ink width of text at `size` (before writing it)."""
        return hand.text_width(text, max(9, int(size * self.scale)), self.font) * 1.02

    def write(self, text, x, base, size, align="left", max_w=None, max_h=None):
        """Write text on the page. `size` is a nominal digit size (scaled per font).
        align left: ink starts at x; right: ink ends at x; center: ink centred on x.
        With max_w / max_h the text is re-written smaller until it fits. Returns the ink bbox."""
        size = size * self.scale
        mask, off = self.render(text, size)
        for _ in range(6):
            if mask is None:
                break
            k = min(max_w / mask.width if max_w else 1, max_h / mask.height if max_h else 1)
            if k >= 1:
                break
            size *= max(0.4, k * 0.96)
            mask, off = self.render(text, size)
        if mask is None:
            return None
        x0 = {"left": x, "right": x - mask.width, "center": x - mask.width / 2}[align]
        x0, y0 = int(round(x0)), int(round(base + off[1]))
        self.page.paste(Image.new("RGB", mask.size, self.ink), (x0, y0), mask)
        return (x0, y0, x0 + mask.width, y0 + mask.height)


class _Bill:
    def __init__(self, spec, rng):
        self.spec, self.rng = spec, rng
        self.items = spec["items"]
        self.sup = spec["supplier"]
        self.kind = spec.get("supplier_kind", "veg")
        self.city = self.sup["address_lines"][-1].split(",")[0].strip() if self.sup["address_lines"] else "Ernakulam"
        self.header_box = None
        self.inv_box = self.date_box = None
        self.sign_drawn = False

    # ------------------------------------------------------------------ style
    def choose(self):
        rng, spec = self.rng, self.spec
        st = self.st = {}
        n = len(self.items)
        st["header"] = rng.choice(["boxed", "centered", "centered", "logo", "invoice"])
        # small landscape pads (Aadidev, inv10) only suit a few untaxed rows
        st["landscape"] = (n <= 4 and spec["tax_mode"] == "none" and st["header"] in ("centered", "logo")
                           and rng.random() < 0.35)
        self.W = rng.randint(1180, 1300) if st["landscape"] else rng.randint(1000, 1250)
        self.H_nom = int(self.W * rng.uniform(0.68, 0.76)) if st["landscape"] else int(self.W * rng.uniform(1.36, 1.5))
        self.s = s = self.W / 1100
        self.m = int(self.W * rng.uniform(0.035, 0.065))      # side margin
        self.x0, self.x1 = self.m, self.W - self.m
        self.cw = self.x1 - self.x0
        self.top = int(rng.uniform(65, 85) * s if st["landscape"] else rng.uniform(70, 130) * s)   # receivers scribble here
        self.paper = _pick(rng, PAPER_WEIGHTS)

        ink = rng.choice(list(PRINT_INKS))
        st["ink"] = PRINT_INKS[ink]
        st["ink2"] = PRINT_INKS[rng.choice(list(PRINT_INKS))] if rng.random() < 0.25 else st["ink"]
        st["red"] = rng.choice(SERIAL_REDS)
        st["name_font"] = rng.choice(["serif_bold", "serif_bold", "condensed", "sans", "typewriter_bold", "narrow"])
        st["body_font"] = rng.choice(["sans", "sans", "sans2", "narrow", "serif"])
        st["serial_font"] = rng.choice(["typewriter", "typewriter_bold", "serif", "sans", "mono"])
        st["rupee"] = st["body_font"] in RUPEE_FONTS and rng.random() < 0.5
        st["line_w"] = rng.choice([2, 2, 3])
        st["border_w"] = st["line_w"] + rng.choice([0, 1, 2])
        st["dot_step"] = rng.randint(7, 10)

        # the vendor's pen
        st["hand_font"] = _pick(rng, HAND_FONTS)
        st["hand_ink"] = _pick(rng, HAND_INKS)
        st["jitter"] = rng.uniform(0.8, 1.45)     # above ~1.5 digits start to ride over each other
        st["slant"] = rng.uniform(-6, 6)
        st["hand_frac"] = rng.uniform(0.72, 0.92)             # nominal hand size / row height (digits ~0.6 row)
        st["num_align"] = _pick(rng, {"right": 45, "left": 30, "center": 25})
        st["slash"] = rng.random() < 0.3                      # 2550/-
        st["decimals"] = rng.random() < 0.2                   # 2550.00
        st["comma"] = rng.random() < 0.15                     # 2,550
        st["rate_decimals"] = rng.random() < 0.15
        st["ticks"] = rng.random() < 0.2

        # table
        st["row_h"] = int(rng.uniform(50, 64) * s)
        st["ruled"] = rng.random() < 0.75
        st["head_fill"] = rng.random() < 0.3
        st["split_amount"] = rng.random() < 0.18             # Rs. | Ps. columns
        st["base_frac"] = rng.uniform(0.70, 0.80)
        cols = list(rng.choice(COLUMN_SETS))
        if spec["tax_mode"] != "none" and rng.random() < 0.35:
            cols.insert(cols.index("amount"), "gst")
        if n and all(it.get("mrp") for it in self.items) and rng.random() < 0.7:
            cols.insert(cols.index("amount"), "mrp")
        if "unit" not in cols and rng.random() < 0.12:
            cols.insert(cols.index("qty") + 1, "unit")
        st["cols"] = cols
        st["labels"] = {k: rng.choice(COL_LABELS[k]) for k in cols}
        if "unit" in cols and st["labels"]["qty"] == "Nos.":
            st["labels"]["qty"] = "Qty"
        st["sl_mode"] = rng.choice(["printed", "hand", "hand", "none"]) if "sl" in cols else None
        st["hsn_hand"] = rng.random() < 0.6
        st["desc_case"] = _pick(rng, {"upper": 35, "title": 40, "sentence": 25})    # how the vendor writes names
        st["print_case"] = rng.choice(["upper", "title"])                           # how the press set them
        st["sl_fmt"] = rng.choice(["{}", "{}", "{}."])        # how this vendor numbers the rows
        st["pct_sign"] = rng.choice(["%", ""])

        # some pads have the vendor's products pre-printed in the rows (eggs, mushrooms ...)
        pre_kinds = ("eggs", "mushroom", "cut_veg", "microgreens")
        own = {c[0] for c in CATALOG.get(self.kind, [])}
        st["preprint"] = (n <= 12 and all(it["description"] in own for it in self.items)
                          and rng.random() < (0.6 if self.kind in pre_kinds else 0.1))
        self.row_plan = [("item", i) for i in range(n)]
        if st["preprint"]:
            have = {it["description"] for it in self.items}
            extras = [c for c in CATALOG.get(self.kind, []) if c[0] not in have]
            rng.shuffle(extras)
            # a printed pad lists the vendor's whole range, or most of it, as far as the rows go
            k = len(extras) if rng.random() < 0.6 else rng.randint(0, len(extras))
            for c in extras[:max(0, min(k, (5 if st["landscape"] else 14) - n))]:
                self.row_plan.insert(rng.randint(0, len(self.row_plan)), ("blank", c[0], c[1]))
            if st["sl_mode"]:
                st["sl_mode"] = "printed"       # the press numbers the product rows

        # what goes below the table; a small landscape pad has room for little besides the grid
        small = st["landscape"]
        st["totals_style"] = rng.choice(["row", "boxes", "boxes"])
        st["words"] = spec.get("amount_in_words") and not spec["continued"] and rng.random() < 0.6
        st["words_label"] = rng.choice(["Rupees in words :", "Amount in words :", "Total in Words :", "In Words :",
                                        "Amount Chargeable (in words) :"])
        st["left_note"] = rng.choice(["eoe", "remarks", "blank"])
        st["for_box"] = small or rng.random() < 0.3          # "For SHOP / Proprietor" box beside the words
        st["receiver"] = rng.random() < 0.5
        st["bank"] = not small and rng.random() < 0.25
        st["terms"] = [] if small else rng.sample(TERMS, rng.choice([0, 0, 1, 1, 2]))
        st["tagline_box"] = not small and rng.random() < 0.25
        st["imprint"] = rng.choice(PRINTERS) if (not small and rng.random() < 0.35) else None
        st["perforation"] = rng.random() < 0.3
        st["copy_mark"] = rng.choice(["ORIGINAL", "DUPLICATE", "CUSTOMER COPY"]) if rng.random() < 0.2 else None
        self.sign_h = int((110 if small else 150) * s)
        st["signer"] = rng.choice(["Proprietor", "Authorised Signatory", "Partner", "Manager", "Signature"])
        st["sign"] = rng.random() < 0.75
        self.total_lines = self.plan_totals()

    def plan_totals(self):
        """[(label, value or None, is_grand)] for the totals block; None values stay blank."""
        rng, spec = self.rng, self.spec
        t, mode = spec["totals"], spec["tax_mode"]
        sub_l, grand_l = rng.choice([("Sub Total", "TOTAL"), ("Total", "Grand Total"), ("Gross Amount", "Net Amount"),
                                     ("Sub Total", "Net Total"), ("Sub Total", "TOTAL")])
        boxes = self.st["totals_style"] == "boxes"
        if spec["continued"] or t.get("grand_total") is None:
            labels = [sub_l, "CGST", "SGST", grand_l] if mode != "none" else [grand_l]
            return [(lab, None, lab == grand_l) for lab in labels]
        lines = []
        if mode != "none":
            pcts = {it["tax_percent"] for it in self.items}
            at = f" @ {max(pcts) / 2:g}%" if len(pcts) == 1 and max(pcts) and rng.random() < 0.6 else ""
            lines.append(("Taxable Value" if mode == "inclusive" else sub_l, t["subtotal"], False))
            lines.append(("CGST" + at, t["cgst"] or None, False))
            lines.append(("SGST" + at, t["sgst"] or None, False))
            if t.get("igst"):
                lines.append(("IGST", t["igst"], False))
            if t.get("cess"):
                lines.append(("Cess", t["cess"], False))
        elif t["round_off"] or (boxes and rng.random() < 0.35):
            # the subtotal line (equal to the total when there is no round-off)
            lines.append((sub_l, t["subtotal"] if (t["round_off"] or rng.random() < 0.5) else None, False))
            if not t["round_off"] and rng.random() < 0.6:
                lines += [("CGST", None, False), ("SGST", None, False)]     # pre-printed, left blank
        if t["round_off"]:
            lines.append((rng.choice(["Round Off", "R/Off", "Rounded Off", "Round Off (+/-)"]), t["round_off"], False))
        lines.append((grand_l, t["grand_total"], True))
        return lines

    # ------------------------------------------------------------------ drawing helpers
    def pfont(self, key, size, bold=False):
        name = self.st.get(key, key)
        if bold:
            name = BOLD_TWIN.get(name, name)
        return hand.font(name, max(8, int(size)), bold)

    def ptext(self, xy, text, size, key="body_font", bold=False, fill=None, anchor="ls", max_w=None):
        """Printed text. Shrinks to max_w if given. Returns its bbox."""
        f = self.pfont(key, size, bold)
        while max_w and f.getlength(text) > max_w and size > 9:
            size *= max(0.6, max_w / f.getlength(text) * 0.99)
            f = self.pfont(key, size, bold)
        self.d.text(xy, text, font=f, fill=fill or self.st["ink"], anchor=anchor)
        return self.d.textbbox(xy, text, font=f, anchor=anchor)

    def dots(self, x0, x1, y):
        step, r = self.st["dot_step"], 1.3 * self.s
        for x in range(int(x0), int(x1), step):
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=self.st["ink"])

    def hline(self, x0, x1, y, w=None):
        self.d.line((x0, y, x1, y), fill=self.st["ink"], width=w or self.st["line_w"])

    def vline(self, x, y0, y1, w=None):
        self.d.line((x, y0, x, y1), fill=self.st["ink"], width=w or self.st["line_w"])

    def add_header(self, box):
        self.header_box = _union(self.header_box, box)

    def money(self, v, rate=False):
        """Hand-written money the way this vendor writes it: 2550, 2550/-, 2550.00, 2,550, 1234.56."""
        st = self.st
        neg = v < 0
        cents = int(round(abs(v) * 100))
        rupees, paise = divmod(cents, 100)
        rs = _group_indian(rupees) if (st["comma"] and not rate) else str(rupees)
        if paise or (st["rate_decimals"] if rate else st["decimals"]):
            out = f"{rs}.{paise:02d}"
        else:
            out = rs + ("/-" if st["slash"] and not rate else "")
        return ("-" if neg else "") + out

    def serial(self, x, base, size, anchor="ls", max_w=None):
        """The red numbering-machine bill number, smaller when a long number has to fit its space."""
        bold = self.st["serial_font"] in ("sans", "mono")
        f = self.pfont("serial_font", size, bold=bold)
        text = self.spec["invoice_number_printed"]
        if max_w and f.getlength(text) > max_w:
            f = self.pfont("serial_font", size * max_w / f.getlength(text) * 0.96, bold=bold)
        self.d.text((x, base), text, font=f, fill=self.st["red"], anchor=anchor)
        return self.d.textbbox((x, base), text, font=f, anchor=anchor)

    def hand_size(self, frac=1.0):
        """Pen size for the date / customer lines above the table."""
        return min(self.st["row_h"] * self.st["hand_frac"], 40 * self.s) * frac

    # ------------------------------------------------------------------ logos
    def logo(self, cx, cy, r, ink=None):
        """A simple printed logo for the vendor's trade, inside a circle of radius r."""
        d, ink = self.d, ink or self.st["ink2"]
        w = max(2, int(r / 14))
        kind = self.kind
        style = self.rng.choice(["ring", "plain"]) if kind in ("eggs", "mushroom", "veg", "cut_veg", "microgreens",
                                                               "fruit") else "ring"    # a monogram needs its ring
        if style == "ring":
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=w + 1)
            d.ellipse((cx - r * 0.88, cy - r * 0.88, cx + r * 0.88, cy + r * 0.88), outline=ink, width=max(1, w // 2))
            r *= 0.8
        if kind == "eggs":
            for dx, dy, k in ((-0.38, 0.12, 0.42), (0.38, 0.12, 0.42), (0, -0.12, 0.48)):
                ex, ey, er = cx + dx * r, cy + dy * r, k * r
                d.ellipse((ex - er * 0.78, ey - er, ex + er * 0.78, ey + er), outline=ink, width=w,
                          fill=None if k < 0.45 else PAPERS[self.paper])
            d.arc((cx - r * 0.9, cy - r * 0.2, cx + r * 0.9, cy + r * 0.85), 0, 180, fill=ink, width=w + 1)
        elif kind == "mushroom":
            d.pieslice((cx - r * 0.8, cy - r * 0.7, cx + r * 0.8, cy + r * 0.5), 180, 360, fill=ink)
            d.rounded_rectangle((cx - r * 0.2, cy - r * 0.12, cx + r * 0.2, cy + r * 0.62), radius=r * 0.1, fill=ink)
            for k in (-0.45, 0, 0.42):
                d.ellipse((cx + k * r - r * 0.07, cy - r * 0.42, cx + k * r + r * 0.07, cy - r * 0.28),
                          fill=PAPERS[self.paper])
            d.line((cx - r * 0.7, cy + r * 0.64, cx + r * 0.7, cy + r * 0.64), fill=ink, width=w)
        elif kind in ("veg", "cut_veg", "microgreens", "fruit"):
            # one or two leaves on a stem
            leaves = [(-0.75, 0.55, 0.7, -0.6, 0.42)] if self.rng.random() < 0.5 else \
                [(-0.1, 0.7, 0.75, -0.45, 0.36), (-0.1, 0.7, -0.8, -0.35, 0.3)]
            for ax, ay, bx, by, wid in leaves:
                self.leaf(cx + ax * r, cy + ay * r, cx + bx * r, cy + by * r, wid * r, ink, w)
            # the stem continues the first leaf's midrib back from its base
            ax, ay, bx, by, _ = leaves[0]
            d.line((cx + ax * r, cy + ay * r, cx + (ax - (bx - ax) * 0.15) * r, cy + (ay - (by - ay) * 0.15) * r),
                   fill=ink, width=w + 1)
        else:
            initials = "".join(wd[0] for wd in self.sup["name"].replace(".", " ").split()[:3] if wd[0].isalpha())
            f = self.pfont("serif_bold", r * 0.8)
            d.text((cx, cy), initials or "S", font=f, fill=ink, anchor="mm")
        return (int(cx - r / (0.8 if style == "ring" else 1)), int(cy - r / (0.8 if style == "ring" else 1)),
                int(cx + r / (0.8 if style == "ring" else 1)) + 1, int(cy + r / (0.8 if style == "ring" else 1)) + 1)

    def leaf(self, ax, ay, bx, by, wid, ink, w):
        """A filled leaf from (ax, ay) to the tip (bx, by), with a paper-coloured vein."""
        dx, dy = bx - ax, by - ay
        ln = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / ln, dx / ln
        up, down = [], []
        for k in range(21):
            t = k / 20
            bulge = wid * (t ** 0.8) * (1 - t) * 2.6
            up.append((ax + dx * t + nx * bulge, ay + dy * t + ny * bulge))
            down.append((ax + dx * t - nx * bulge * 0.8, ay + dy * t - ny * bulge * 0.8))
        self.d.polygon(up + down[::-1], fill=ink)
        self.d.line((ax + dx * 0.1, ay + dy * 0.1, ax + dx * 0.85, ay + dy * 0.85), fill=PAPERS[self.paper],
                    width=max(1, w // 2))

    # ------------------------------------------------------------------ letterheads
    def contact_bits(self):
        """Printed contact lines (each a string) in the order a printer would set them."""
        rng, sup = self.rng, self.sup
        phone = sup["phone"]
        if rng.random() < 0.4:
            phone += ", " + rng.choice("9876") + "".join(rng.choice("0123456789") for _ in range(9))
        lab = rng.choice(["Ph : ", "Ph: ", "Mob : ", "Phone : ", "Cell : ", "Customer care: ", "For orders Call/Whatsapp: "])
        out = {"phone": lab + phone}
        if sup.get("email"):
            out["email"] = rng.choice(["E-mail : ", "email: ", "Email : "]) + sup["email"]
        if sup.get("gstin"):
            out["gstin"] = rng.choice(["GSTIN : ", "GSTIN: ", "GST No.: ", "GSTIN No. "]) + sup["gstin"]
        if sup.get("fssai"):
            out["fssai"] = rng.choice(["FSSAI No: ", "FSSAI Lic. No. : ", "FSSAI : "]) + sup["fssai"]
        return out

    def header_centered(self, y):
        """A.K.S. Traders / Eggs Daily / Aadidev: everything centred, title strip on top."""
        rng, s, st = self.rng, self.s, self.st
        cx = self.W / 2
        bits = self.contact_bits()
        small = rng.uniform(19, 22) * s
        title = rng.choice(TITLES)
        # top strip: GSTIN / FSSAI left, title or invocation centre, phone right
        base = y + small
        left_key = "gstin" if "gstin" in bits and rng.random() < 0.6 else ("fssai" if "fssai" in bits and rng.random() < 0.4 else None)
        if left_key:
            self.add_header(self.ptext((self.x0, base), bits.pop(left_key), small, bold=True, max_w=self.cw * 0.4))
        if rng.random() < 0.5 and self.pfont("body_font", small).getlength(bits["phone"]) <= self.cw * 0.36:
            self.add_header(self.ptext((self.x1, base), bits.pop("phone"), small, anchor="rs", max_w=self.cw * 0.36))
        mid = None
        if rng.random() < 0.45 or st["landscape"]:
            b = self.ptext((cx, base), title, small * 1.1, bold=True, anchor="ms")
            self.hline(b[0], b[2], b[3] + 3, 2)
            mid, title = b, None
        elif rng.random() < 0.3:
            mid = self.ptext((cx, base), rng.choice(INVOCATIONS), small * 0.85, anchor="ms")
        self.add_header(mid)
        y = base + 14 * s
        # name, with a logo beside it sometimes
        logo_r = int(rng.uniform(44, 60) * s) if (rng.random() < 0.4 and not st["landscape"]) else 0
        room = self.cw - (4 * logo_r + 40 * s if logo_r else 0)
        size = rng.uniform(50, 62) * s if st["landscape"] else rng.uniform(58, 80) * s
        f = self.pfont("name_font", size, bold=True)
        if f.getlength(self.sup["name"]) > room * 0.95:
            size *= room * 0.95 / f.getlength(self.sup["name"])
        base = y + size * 0.95
        nb = self.ptext((cx, base), self.sup["name"], size, "name_font", bold=True, fill=st["ink2"], anchor="ms")
        self.add_header(nb)
        if logo_r:
            self.add_header(self.logo(self.x0 + logo_r + 10 * s, (nb[1] + nb[3]) / 2, logo_r))
        y = max(nb[3], (nb[1] + nb[3]) / 2 + logo_r) + 10 * s
        # tagline, boxed like "NADAN EGGS SUPPLIERS" or plain
        if rng.random() < (0.0 if st["landscape"] else 0.65):
            tag = rng.choice(TAGLINES.get(self.kind, ["Wholesale & Retail"]))
            ts = rng.uniform(22, 28) * s
            base = y + ts
            b = self.ptext((cx, base), tag, ts, bold=rng.random() < 0.6, anchor="ms", max_w=self.cw * 0.8)
            if rng.random() < 0.5:
                self.d.rectangle((b[0] - 10 * s, b[1] - 7 * s, b[2] + 10 * s, b[3] + 7 * s), outline=st["ink"], width=2)
                b = (b[0] - 10 * s, b[1] - 7 * s, b[2] + 10 * s, b[3] + 7 * s)
            self.add_header(b)
            y = b[3] + 8 * s
        # address and contacts
        size = rng.uniform(19, 23) * s
        lines = [", ".join(self.sup["address_lines"])] if (rng.random() < 0.5 or st["landscape"]) else list(self.sup["address_lines"])
        if "phone" in bits and (rng.random() < 0.5 or st["landscape"]):
            lines[-1] += ". " + bits.pop("phone")
        lines += [bits.pop(k) for k in ("phone", "email") if k in bits]
        extra = [bits.pop(k) for k in ("gstin", "fssai") if k in bits]
        if extra:
            lines.append("   ".join(extra))
        for ln in lines:
            y += size * 1.3
            self.add_header(self.ptext((cx, y), ln, size, anchor="ms", max_w=self.cw * 0.96))
        y += 10 * s
        if title:
            ts = rng.uniform(24, 30) * s
            y += ts
            b = self.ptext((cx, y), title, ts, bold=True, anchor="ms")
            if rng.random() < 0.7:
                self.hline(b[0], b[2], b[3] + 4, 2)
            self.add_header(b)
            y = b[3] + 8 * s
        return self.meta(y + 6 * s)

    def header_logo(self, y):
        """Dr. Growmush: a round badge in the middle, phones top right."""
        rng, s = self.rng, self.s
        cx = self.W / 2
        bits = self.contact_bits()
        r = int(rng.uniform(46, 58) * s) if self.st["landscape"] else int(rng.uniform(70, 95) * s)
        lb = self.logo(cx, y + r + 6 * s, r)
        self.add_header(lb)
        size = rng.uniform(22, 27) * s
        side = cx - r - 24 * s - self.x0          # room beside the badge
        yy = y + size
        for ln in bits.pop("phone").split(", "):
            self.add_header(self.ptext((self.x1, yy), ln, size, bold=True, anchor="rs", max_w=side))
            yy += size * 1.25
        yy = y + size
        for k in ("gstin", "fssai"):
            if k in bits:
                self.add_header(self.ptext((self.x0, yy), bits.pop(k), size * 0.85, anchor="ls", max_w=side))
                yy += size * 1.2
        y = lb[3] + 8 * s
        size = rng.uniform(30, 42) * s
        y += size
        text = self.sup["name"] + ", " + self.city.upper() if rng.random() < 0.6 else self.sup["name"]
        self.add_header(self.ptext((cx, y), text, size, "name_font", bold=True, fill=self.st["ink2"], anchor="ms",
                                   max_w=self.cw * 0.9))
        size = rng.uniform(18, 21) * s
        for ln in [", ".join(self.sup["address_lines"])] + [bits.pop(k) for k in ("email",) if k in bits]:
            y += size * 1.35
            self.add_header(self.ptext((cx, y), ln, size, anchor="ms", max_w=self.cw * 0.96))
        return self.meta(y + 14 * s)

    def meta(self, y):
        """Bill No. (red) and Date on one line, then the customer line(s) on dots."""
        rng, s, st, pen = self.rng, self.s, self.st, self.pen
        size = rng.uniform(22, 26) * s
        base = y + 46 * s
        lab = self.ptext((self.x0, base), rng.choice(["Bill No.", "No.", "Bill No :", "Cash Bill No.", "Invoice No."]),
                         size, bold=rng.random() < 0.4)
        x = lab[2] + 12 * s
        if rng.random() < 0.1:      # book series printed before the red number, as on inv08 ("26-27 C 1250")
            pb = self.ptext((x, base), rng.choice(["26-27 C", "26-27  C"]), size, bold=True)
            x = pb[2] + 10 * s
        # date on the right
        dx = self.x0 + self.cw * rng.uniform(0.58, 0.66)
        self.inv_box = self.serial(x, base + 2 * s, rng.uniform(44, 58) * s, max_w=dx - x - 24 * s)
        db = self.ptext((dx, base), rng.choice(["Date :", "Date", "Date:", "Dated :"]), size)
        self.dots(db[2] + 6 * s, self.x1, base + 4 * s)
        self.date_box = pen.write(self.spec["date_printed"], db[2] + rng.uniform(14, 40) * s, base - 3 * s,
                                  self.hand_size(1.15), max_w=self.x1 - db[2] - 20 * s)
        y = max(base, self.inv_box[3]) + 10 * s
        return self.customer(y)

    def customer(self, y):
        rng, s = self.rng, self.s
        size = rng.uniform(22, 26) * s
        label = rng.choice(["To", "M/s.", "Customer :", "Name & Address", "To,", "Name :"])
        base = y + self.hand_size(1.15) * 0.95 + 14 * s
        lb = self.ptext((self.x0, base), label, size, bold=rng.random() < 0.3)
        self.dots(lb[2] + 8 * s, self.x1, base + 4 * s)
        x = lb[2] + rng.uniform(14, 40) * s
        self.pen.write(self.spec["buyer"]["display"], x, base - 3 * s, self.hand_size(1.15), max_w=self.x1 - x - 10 * s)
        if label == "Name & Address" or rng.random() < 0.25:
            base += self.hand_size(1.05) * 0.9 + 16 * s
            if rng.random() < 0.5:
                gl = self.ptext((self.x0, base), "GSTIN :", size)
                self.dots(gl[2] + 8 * s, self.x0 + self.cw * 0.7, base + 4 * s)
                if rng.random() < 0.6:
                    self.pen.write(self.spec["buyer"]["gstin"], gl[2] + 20 * s, base - 3 * s, self.hand_size(1.05),
                                   max_w=self.cw * 0.6)
            else:
                self.dots(self.x0, self.x1, base + 4 * s)
        return base + 22 * s

    def header_boxed(self, y):
        """Thalir Fresh: letterhead in a bordered box, No. / Date boxes on the right, M/s line below."""
        rng, s, st, pen = self.rng, self.s, self.st, self.pen
        bits = self.contact_bits()
        xd = self.x0 + self.cw * rng.uniform(0.58, 0.66)
        lw = xd - self.x0
        size = rng.uniform(40, 54) * s
        yy = y + 14 * s + size
        nb = self.ptext(((self.x0 + xd) / 2, yy), self.sup["name"], size, "name_font", bold=True, fill=st["ink2"],
                        anchor="ms", max_w=lw * 0.92)
        self.add_header(nb)
        size = rng.uniform(17, 20) * s
        lines = list(self.sup["address_lines"]) + [bits.pop("phone")]
        lines += [bits.pop(k) for k in ("gstin", "fssai", "email") if k in bits and (k == "gstin" or rng.random() < 0.8)]
        yy = nb[3] + 4 * s
        for ln in lines:
            yy += size * 1.3
            self.add_header(self.ptext(((self.x0 + xd) / 2, yy), ln, size, anchor="ms", bold=rng.random() < 0.2,
                                       max_w=lw * 0.94))
        y1 = yy + 14 * s
        self.d.rectangle((self.x0, y, self.x1, y1), outline=st["ink"], width=st["border_w"])
        self.vline(xd, y, y1)
        # right part: No. and Date
        ls = rng.uniform(22, 26) * s
        ym = (y + y1) / 2
        if rng.random() < 0.5:
            self.hline(xd, self.x1, ym)
        base = y + (ym - y) * 0.68
        nl = self.ptext((xd + 14 * s, base), rng.choice(["No.", "No. :", "Bill No."]), ls)
        self.inv_box = self.serial(nl[2] + 16 * s, base + 4 * s, rng.uniform(42, 54) * s,
                                  max_w=self.x1 - nl[2] - 30 * s)
        base = ym + (y1 - ym) * 0.66
        dl = self.ptext((xd + 14 * s, base), "Date :", ls)
        self.date_box = pen.write(self.spec["date_printed"], dl[2] + 20 * s, base, self.hand_size(1.15),
                                  max_w=self.x1 - dl[2] - 30 * s)
        return self.customer(y1)

    def header_invoice(self, y):
        """hyleaf: INVOICE top left, contact block top right, brand + info box (No / Bill to / Date)."""
        rng, s, st, pen = self.rng, self.s, self.st, self.pen
        bits = self.contact_bits()
        tb = self.ptext((self.x0, y + 46 * s), rng.choice(["INVOICE", "CASH BILL", "BILL"]), rng.uniform(36, 46) * s,
                        bold=True)
        self.add_header(tb)
        size = rng.uniform(27, 33) * s
        yy = y + size
        self.add_header(self.ptext((self.x1, yy), self.sup["name"], size, "name_font", bold=True, fill=st["ink2"],
                                   anchor="rs", max_w=self.cw * 0.6))
        size = rng.uniform(17, 20) * s
        lines = [bits.pop(k) for k in ("email", "phone", "gstin", "fssai") if k in bits]
        lines[1:1] = self.sup["address_lines"]
        for ln in lines:
            yy += size * 1.3
            self.add_header(self.ptext((self.x1, yy), ln, size, anchor="rs", bold=ln.startswith("For"),
                                       max_w=self.cw * 0.55))
        y = max(yy, tb[3]) + 22 * s
        # brand block left: logo and tagline
        r = int(rng.uniform(38, 50) * s)
        self.add_header(self.logo(self.x0 + r, y + r + 8 * s, r))
        ts, room = rng.uniform(24, 30) * s, self.cw * 0.45 - 2 * r - 20 * s
        tags = TAGLINES.get(self.kind, ["Wholesale & Retail"])
        f = self.pfont("body_font", ts, True)
        tag = rng.choice([t for t in tags if f.getlength(t) < room * 1.25] or [min(tags, key=len)])
        self.add_header(self.ptext((self.x0 + 2 * r + 14 * s, y + r + 20 * s), tag, ts, bold=True, fill=st["ink2"],
                                   max_w=room))
        # info box right
        bx0 = self.x0 + self.cw * rng.uniform(0.45, 0.52)
        rh = int(rng.uniform(44, 52) * s)
        lx = bx0 + (self.x1 - bx0) * 0.3
        ls = rng.uniform(18, 21) * s
        self.d.rectangle((bx0, y, self.x1, y + 3 * rh), outline=st["ink"], width=st["border_w"])
        self.vline(lx, y, y + 3 * rh)
        handwritten_no = rng.random() < 0.5
        for i, lab in enumerate(["Invoice No:", "Bill to:", "Date:"]):
            ry = y + i * rh
            if i:
                self.hline(bx0, self.x1, ry)
            base = ry + rh * 0.68
            self.ptext((lx - 10 * s, base), lab, ls, bold=True, anchor="rs")
            vx, vw = lx + 12 * s, self.x1 - lx - 22 * s
            if i == 0:
                self.inv_box = (pen.write(self.spec["invoice_number_printed"], vx, ry + rh * 0.8, self.hand_size(1.0),
                                          max_w=vw) if handwritten_no else
                                self.serial(vx, ry + rh * 0.78, rh * 0.75, max_w=vw))
            elif i == 1:
                pen.write(self.spec["buyer"]["display"], vx, ry + rh * 0.8, self.hand_size(0.95), max_w=vw)
            else:
                self.date_box = pen.write(self.spec["date_printed"], vx, ry + rh * 0.8, self.hand_size(1.0), max_w=vw)
        return y + 3 * rh + 22 * s

    # ------------------------------------------------------------------ table
    def plan_columns(self, hs):
        """Column x positions: each value column at least as wide as what gets written in it at the
        pen's normal size (minor columns like HSN / unit capped), the description column gets the rest.
        A pad that would be crowded leaves out its minor columns rather than squeeze the numbers."""
        rng, st, pen = self.rng, self.st, self.pen
        cw = self.cw
        pad = 0.35 * hs
        need = {k: 0.0 for k in st["cols"]}
        corr = self.spec["corrections"].get("quantity")
        for i, it in enumerate(self.items):
            vals = {"qty": qty_text(it["quantity"]), "rate": self.money(it["rate"], rate=True),
                    "amount": self.money(it["amount"]), "unit": it["unit"], "hsn": it["hsn"],
                    "mrp": self.money(it["mrp"], rate=True) if it.get("mrp") else "", "gst": f"{it['tax_percent']:g}%",
                    "sl": str(i + 1) + "."}
            if corr and corr["row"] == i:
                vals["qty"] = qty_text(corr["printed"]) + "  " + qty_text(corr["new"])
            for k in st["cols"]:
                if k in vals:
                    size = hs * (0.85 if k == "unit" else 0.9 if k == "hsn" else 1)
                    need[k] = max(need[k], pen.width(vals[k], size) + 2 * pad)
        for lab in self.total_lines:
            if lab[1] is not None:
                need["amount"] = max(need["amount"], pen.width(self.money(lab[1]), hs * 1.1) + 2 * pad)
        if st["split_amount"]:
            need["amount"] = need["amount"] / 0.72 + pad
        f = self.pfont("body_font", 23 * self.s, True)
        for k in st["cols"]:
            need[k] = max(need[k], max(f.getlength(t) for t in st["labels"][k].split("\n")) * 0.8 + 12)
        base = {k: COL_WEIGHT[k] * cw * rng.uniform(0.85, 1.1) for k in st["cols"]}

        def widths():
            w = {}
            for k in st["cols"]:
                if k != "desc":
                    w[k] = max(base[k], need[k])
                    if k in ("sl", "hsn", "unit", "gst"):
                        w[k] = min(w[k], base[k] * 1.8)
            return w

        w = widths()
        for k in ("unit", "gst", "mrp", "hsn", "sl"):
            if cw - sum(w.values()) >= 0.34 * cw:
                break
            if k in st["cols"] and not (k == "sl" and st["preprint"]):
                st["cols"].remove(k)
                w = widths()
        if "sl" not in st["cols"]:
            st["sl_mode"] = None
        if cw - sum(w.values()) < 0.3 * cw:     # still crowded: everything gives a little
            f = 0.7 * cw / sum(w.values())
            w = {k: v * f for k, v in w.items()}
        w["desc"] = cw - sum(w.values())
        cols = st["cols"]
        xs = [self.x0]
        for k in cols:
            xs.append(xs[-1] + w[k])
        xs[-1] = self.x1
        self.cx = {k: (int(xs[i]), int(xs[i + 1])) for i, k in enumerate(cols)}

    def table_header_height(self):
        st = self.st
        two = any("\n" in st["labels"][k] for k in st["cols"])
        th = int(st["row_h"] * (1.3 if two else 1.0) * self.rng.uniform(0.95, 1.12))
        if st["split_amount"]:
            th = max(th, int(st["row_h"] * 1.3))
        return th

    def draw_table(self, y, th, n_grid, row_h):
        st, s, d = self.st, self.s, self.d
        ink = st["ink"]
        x0, x1 = self.x0, self.x1
        by = y + th + n_grid * row_h
        if st["head_fill"]:
            tint = tuple(int(p * 0.84 + c * 0.16) for p, c in zip(PAPERS[self.paper], ink))
            d.rectangle((x0, y, x1, y + th), fill=tint)
        # header labels
        size = self.rng.uniform(21, 25) * s
        for k in st["cols"]:
            a, b = self.cx[k]
            lab = st["labels"][k]
            if st["split_amount"] and k == "amount":
                lines = lab.split("\n")[:1]
                cy = y + th * 0.36
            else:
                lines = lab.split("\n")
                cy = y + th / 2
            fsz = size
            f = self.pfont("body_font", fsz, True)
            widest = max(f.getlength(t) for t in lines)
            if widest > (b - a) - 8:
                fsz *= ((b - a) - 8) / widest
                f = self.pfont("body_font", fsz, True)
            lh = fsz * 1.15
            for j, t in enumerate(lines):
                d.text(((a + b) / 2, cy + (j - (len(lines) - 1) / 2) * lh), t, font=f, fill=ink, anchor="mm")
        if st["split_amount"]:
            a, b = self.cx["amount"]
            self.split_x = int(a + (b - a) * 0.72)
            ym = int(y + th * 0.66)
            self.hline(a, b, ym, 1)
            f = self.pfont("body_font", size * 0.75, True)
            d.text(((a + self.split_x) / 2, (ym + y + th) / 2), "Rs.", font=f, fill=ink, anchor="mm")
            d.text(((self.split_x + b) / 2, (ym + y + th) / 2), "Ps.", font=f, fill=ink, anchor="mm")
            self.vline(self.split_x, ym, by, 1)
        # grid
        for k in st["cols"][1:]:
            self.vline(self.cx[k][0], y, by)
        self.hline(x0, x1, y + th, st["line_w"] + (1 if self.rng.random() < 0.5 else 0))
        if st["ruled"]:
            for i in range(1, n_grid):
                self.hline(x0, x1, y + th + i * row_h, 1 if st["line_w"] < 3 else 2)
        d.rectangle((x0, y, x1, by), outline=ink, width=st["border_w"])
        return by

    def fill_rows(self, body_y, row_h, n_grid):
        """Pre-printed product names and serial numbers, then the vendor's handwriting."""
        rng, st, s, pen = self.rng, self.st, self.s, self.pen
        hs = self.hs
        corr = self.spec["corrections"].get("quantity")
        rows_layout = []
        psize = row_h * rng.uniform(0.44, 0.52)
        for r in range(n_grid):
            top = body_y + r * row_h
            plan = self.row_plan[r] if r < len(self.row_plan) else None
            if st["sl_mode"] == "printed" and (plan or not st["preprint"]):
                a, b = self.cx["sl"]
                self.ptext(((a + b) / 2, top + row_h * 0.66), f"{r + 1}.", psize, anchor="ms", max_w=b - a - 6)
            if plan and plan[0] == "blank":     # pre-printed product nobody ordered today
                self.preprinted_desc(recase(plan[1], st["print_case"]), top, row_h, psize)
                if "hsn" in self.cx:
                    a, b = self.cx["hsn"]
                    self.ptext(((a + b) / 2, top + row_h * 0.66), plan[2], psize, anchor="ms", max_w=b - a - 6)
        for r, plan in enumerate(self.row_plan):
            if plan[0] != "item":
                continue
            i = plan[1]
            it = self.items[i]
            top = body_y + r * row_h
            base = top + row_h * st["base_frac"] + rng.uniform(-0.05, 0.05) * row_h
            box = {"y0": top, "y1": top + row_h}
            # description
            if st["preprint"]:
                desc = self.preprinted_desc(recase(it["description"], st["print_case"]), top, row_h, psize)
                if "hsn" in self.cx:
                    a, b = self.cx["hsn"]
                    self.ptext(((a + b) / 2, top + row_h * 0.66), it["hsn"], psize, anchor="ms", max_w=b - a - 6)
            else:
                desc = self.hand_desc(recase(it["description"], st["desc_case"]), top, base, row_h)
                if "hsn" in self.cx and st["hsn_hand"]:
                    a, b = self.cx["hsn"]
                    pen.write(it["hsn"], (a + b) / 2, base + self.wob(), hs * 0.9, "center", max_w=b - a - 8)
            if st["ticks"] and rng.random() < 0.85:
                a = self.cx["desc"][0]
                hand.tick(self.page, (int(a + 6 * s), int(top + row_h * 0.55)), int(row_h * 0.32), rng,
                          ink=pen.ink)
            if st["sl_mode"] == "hand":
                a, b = self.cx["sl"]
                pen.write(st["sl_fmt"].format(i + 1), (a + b) / 2, base + self.wob(), hs,
                          "center", max_w=b - a - 6)
            # quantity, with the vendor's correction drawn in its cell
            a, b = self.cx["qty"]
            if corr and corr["row"] == i:
                qbox = self.correction(corr, a, b, base, row_h)
            else:
                qbox = self.num(qty_text(it["quantity"]), a, b, base)
            if "unit" in self.cx:
                a, b = self.cx["unit"]
                pen.write(it["unit"], a + 0.3 * hs, base + self.wob(), hs * 0.85, max_w=b - a - 0.6 * hs)
            a, b = self.cx["rate"]
            self.num(self.money(it["rate"], rate=True), a, b, base)
            if "mrp" in self.cx and it.get("mrp"):
                a, b = self.cx["mrp"]
                self.num(self.money(it["mrp"], rate=True), a, b, base)
            if "gst" in self.cx:
                a, b = self.cx["gst"]
                self.num(f"{it['tax_percent']:g}" + st["pct_sign"], a, b, base)
            abox = self.amount(it["amount"], base)
            box.update(desc_bbox=desc, qty_bbox=qbox, amount_bbox=abox)
            ink = _union(desc, qbox, abox)
            box["y0"], box["y1"] = int(min(box["y0"], ink[1])), int(max(box["y1"], ink[3]))
            rows_layout.append(box)
        return rows_layout

    def wob(self):
        return self.rng.uniform(-0.04, 0.04) * self.row_h

    def num(self, text, a, b, base, size=None, max_h=None):
        """A handwritten number in cell [a, b], aligned the way this vendor does it."""
        hs = size or self.hs
        pad = min(self.rng.uniform(0.15, 0.4) * hs, 0.1 * (b - a))    # narrow cells: write closer to the lines
        al = self.st["num_align"]
        x = {"right": b - pad, "left": a + pad, "center": (a + b) / 2}[al]
        return self.pen.write(text, x, base + self.wob(), hs, al, max_w=(b - a) - 2 * pad, max_h=max_h)

    def amount(self, value, base, size=None, max_h=None):
        """Line or total amount in the amount column (split into Rs. | Ps. on some pads)."""
        a, b = self.cx["amount"]
        if not self.st["split_amount"]:
            return self.num(self.money(value), a, b, base, size, max_h)
        hs = size or self.hs
        cents = int(round(abs(value) * 100))
        rupees, paise = divmod(cents, 100)
        rs = ("-" if value < 0 else "") + (_group_indian(rupees) if self.st["comma"] else str(rupees))
        sp = self.split_x
        rb = self.pen.write(rs, sp - 0.3 * hs, base + self.wob(), hs, "right", max_w=sp - a - 0.6 * hs, max_h=max_h)
        ps = f"{paise:02d}" if paise else self.st.setdefault("zero_ps", self.rng.choice(["-", "00", "-"]))
        pb = self.pen.write(ps, (sp + b) / 2, base + self.wob(), hs * 0.9, "center", max_w=b - sp - 8)
        return _union(rb, pb)

    def preprinted_desc(self, text, top, row_h, size):
        """A product name printed by the press, wrapped onto two lines if it is long."""
        a, b = self.cx["desc"]
        x = a + 10 * self.s + (row_h * 0.4 if self.st["ticks"] else 0)
        avail = b - x - 8
        f = self.pfont("body_font", size)
        if f.getlength(text) <= avail or " " not in text:
            return self.ptext((x, top + row_h * 0.66), text, size, max_w=avail)
        words = text.split()
        best = min(range(1, len(words)), key=lambda k: max(f.getlength(" ".join(words[:k])),
                                                           f.getlength(" ".join(words[k:]))))
        size2 = min(size, row_h * 0.4)
        b1 = self.ptext((x, top + row_h * 0.44), " ".join(words[:best]), size2, max_w=avail)
        b2 = self.ptext((x, top + row_h * 0.88), " ".join(words[best:]), size2, max_w=avail)
        return _union(b1, b2)

    def hand_desc(self, text, top, base, row_h):
        """The vendor writes the item name; long names shrink, very long ones go on two lines."""
        pen, hs = self.pen, self.hs
        a, b = self.cx["desc"]
        x = a + 0.3 * hs + self.rng.uniform(0, 0.3) * hs + (row_h * 0.4 if self.st["ticks"] else 0)
        avail = b - x - 0.3 * hs
        w = pen.width(text, hs * 1.05)
        if w * 0.56 <= avail or " " not in text:
            return pen.write(text, x, base + self.wob(), hs * 1.05, max_w=avail, max_h=row_h * 1.05)
        words = text.split()
        best = min(range(1, len(words)), key=lambda k: max(len(" ".join(words[:k])), len(" ".join(words[k:]))))
        size2 = min(hs, row_h * 0.5)
        indent = self.rng.uniform(0, 0.5) * size2
        b1 = pen.write(" ".join(words[:best]), x, top + row_h * 0.46, size2, max_w=avail, max_h=row_h * 0.5)
        b2 = pen.write(" ".join(words[best:]), x + indent, top + row_h * 0.93, size2, max_w=avail - indent,
                       max_h=row_h * 0.5)
        return _union(b1, b2)

    def correction(self, corr, a, b, base, row_h):
        """Like inv11: the first quantity struck out, the corrected one written beside it."""
        rng, pen, hs = self.rng, self.pen, self.hs
        old, new = qty_text(corr["printed"]), qty_text(corr["new"])
        # the margin left of the table when qty is the first column (exactly as on inv11)
        if self.st["cols"][0] == "qty" and self.x0 > pen.width(new, hs) + 20 and rng.random() < 0.6:
            ob = self.num(old, a, b, base)
            nb = pen.write(new, a - 8, base + self.wob(), hs, "right", max_w=a - 10)
        else:
            gap = 0.4 * hs
            pad = 0.25 * hs
            total = pen.width(old, hs) + pen.width(new, hs) + gap
            size = hs * min(1.0, (b - a - 2 * pad) / total)
            wo = pen.width(old, size)
            ob = pen.write(old, a + pad, base + self.wob(), size, max_w=(b - a) * 0.5 - pad)
            nb = pen.write(new, max(ob[2], a + pad + wo) + gap, base + self.wob(), size,
                           max_w=max(10, b - ob[2] - gap - 4))
        hand.strike_through(self.page, ob, rng, ink=pen.ink, double=rng.random() < 0.3)
        return _union(ob, nb)

    # ------------------------------------------------------------------ totals and footer
    def totals_layout(self, tot_h):
        """Where the label cells start and what fills the left part of the totals block."""
        st, s = self.st, self.s
        cols = st["cols"]
        amt_a = self.cx["amount"][0]
        f = self.pfont("body_font", tot_h * 0.5 * 1.1, True)
        widest = max(f.getlength(lab + (" ₹" if st["rupee"] else "")) for lab, _, _ in self.total_lines)
        k = cols.index("amount")
        lab_a = amt_a
        while k > 0 and (amt_a - lab_a) < widest + 30 * s:
            k -= 1
            lab_a = self.cx[cols[k]][0]
        if amt_a - lab_a < widest + 30 * s:
            lab_a = amt_a - widest - 30 * s
        self.lab_a = int(max(self.x0 + self.cw * 0.25, min(lab_a, amt_a - 60 * s)))
        # words inside the totals block (left part) when there is room, else in their own box
        n = len(self.total_lines)
        room = self.lab_a - self.x0 - 40 * s
        self.words_inside = (st["words"] and n >= 2 and room > self.cw * 0.42 and self.rng.random() < 0.6
                             and self.words_lines(room - 260 * s, room) <= int((n * tot_h - 18 * s) // (46 * s)))

    def draw_totals(self, y, tot_h):
        rng, st, s, pen = self.rng, self.st, self.s, self.pen
        a_amt, b_amt = self.cx["amount"]
        n = len(self.total_lines)
        y1 = y + n * tot_h
        self.d.rectangle((self.x0, y, self.x1, y1), outline=st["ink"], width=st["border_w"])
        self.vline(self.lab_a, y, y1)
        self.vline(a_amt, y, y1)
        if st["split_amount"]:
            self.vline(self.split_x, y, y1, 1)
        if st["totals_style"] == "boxes":
            for i in range(1, n):
                self.hline(self.lab_a, self.x1, y + i * tot_h)
        ls = tot_h * rng.uniform(0.42, 0.5)
        total_box = None
        for i, (lab, val, grand) in enumerate(self.total_lines):
            base = y + i * tot_h + tot_h * 0.66
            text = lab + (" ₹" if st["rupee"] else "")
            lb = self.ptext((a_amt - 12 * s, base), text, ls * (1.1 if grand else 1), bold=grand or rng.random() < 0.3,
                            anchor="rs", max_w=a_amt - self.lab_a - 16 * s)
            if val is None:
                continue
            # written a little bigger for the total, but not far over the ruled lines
            vb = self.amount(val, y + i * tot_h + tot_h * st["base_frac"], self.hs * (1.1 if grand else 1),
                             max_h=tot_h * 0.9)
            if grand:
                total_box = _union(lb, vb)
                if rng.random() < 0.3 and y + (i + 1) * tot_h - vb[3] > 13 * s:   # underlined twice
                    for k in (4, 10):
                        hand.pen_line(self.d, [(vb[0] - 4, vb[3] + k * s), (vb[2] + 6, vb[3] + k * s)], rng,
                                      pen.ink, width=2)
        # left part: words, E & OE, remarks or nothing; "continued..." when this is page 1
        left = (self.x0, y, self.lab_a, y1)
        if self.spec["continued"]:
            self.cont_box = self.cont_box or pen.write(rng.choice(["continued...", "Continued..."]),
                                                       self.x0 + 20 * s, y + tot_h * 0.72, self.hs)
        elif self.words_inside:
            self.words(left, inside=True)
        elif st["left_note"] == "eoe":
            eb = self.ptext((self.x0 + 14 * s, y1 - tot_h * 0.34), rng.choice(["E & OE", "E.&O.E.", "E. & O.E."]),
                            ls, bold=True)
            if rng.random() < 0.6:
                self.dots(eb[2] + 30 * s, self.lab_a - 40 * s, eb[3])
        elif st["left_note"] == "remarks" and n >= 2:
            rb = self.ptext((self.x0 + 14 * s, y + tot_h * 0.66), "Remarks", ls)
            self.dots(rb[2] + 6 * s, self.lab_a - 20 * s, rb[3])
        return y1, total_box

    def words(self, box, inside):
        """'Rupees in words' label and the handwritten amount in words on dotted lines in `box`."""
        rng, st, s, pen = self.rng, self.st, self.s, self.pen
        x0, y0, x1, y1 = box
        ls = rng.uniform(19, 23) * s
        pad = 12 * s
        lb = self.ptext((x0 + pad, y0 + 32 * s), st["words_label"], ls, bold=rng.random() < 0.4)
        n_lines = max(1 if inside else 2, int((y1 - y0 - 18 * s) // (46 * s)))
        gap = (y1 - y0 - 18 * s) / n_lines
        bases = [y0 + 32 * s + k * gap for k in range(n_lines)]
        starts = [lb[2] + 10 * s] + [x0 + pad] * (n_lines - 1)
        for b, xs in zip(bases, starts):
            self.dots(xs, x1 - pad, b + 4 * s)
        text = self.spec["amount_in_words"]
        hs = min(self.hs * 0.9, gap * 0.8)
        for _ in range(8):
            lines = self.wrap(text, [x1 - pad - xs - 10 * s for xs in starts], hs)
            if lines:
                break
            hs *= 0.88
        if not lines:   # still too long: put it all on the lines we have, shrinking each to fit
            words = text.split()
            k = -(-len(words) // n_lines)
            lines = [" ".join(words[i:i + k]) for i in range(0, len(words), k)]
        for ln, b, xs in zip(lines, bases, starts):
            pen.write(ln, xs + 6 * s, b - 2 * s, hs, max_w=x1 - pad - xs - 10 * s)

    def wrap(self, text, widths, size):
        """Greedy word wrap on the line widths given; None if it needs more lines."""
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if self.pen.width(trial, size) * 1.04 <= widths[min(len(lines), len(widths) - 1)]:
                cur = trial
            else:
                if not cur:
                    return None
                lines.append(cur)
                cur = w
                if len(lines) >= len(widths):
                    return None
        lines.append(cur)
        return lines if len(lines) <= len(widths) else None

    def words_lines(self, first_w, other_w):
        """Lines the amount in words takes at the usual pen size (first line shortened by the label)."""
        est = self.pen.width(self.spec.get("amount_in_words") or "", self.hs * 0.85) * 1.12
        return 1 + max(0, math.ceil((est - first_w) / max(1.0, other_w)))

    def words_band_height(self):
        """Height of the separate 'Rupees in words' box: two to four dotted lines, as the text needs."""
        if not self.st["words"] or self.words_inside:
            return 0
        s = self.s
        w = (self.cw * 0.64 if self.st["for_box"] else self.cw) - 40 * s
        lines = min(4, max(2, self.words_lines(w - 260 * s, w)))
        return int((30 + 48 * lines + self.rng.uniform(0, 12)) * s)

    def draw_words_band(self, y, h):
        """Thalir style: a bordered 'Rupees ...' box below the table, sometimes with a 'For SHOP' box."""
        st, s = self.st, self.s
        y += 12 * s
        x_split = self.x1 if not st["for_box"] else self.x0 + self.cw * 0.64
        self.d.rounded_rectangle((self.x0, y, self.x1, y + h - 12 * s), radius=10 * s, outline=st["ink"],
                                 width=st["line_w"])
        if st["for_box"]:
            self.d.rounded_rectangle((x_split + 6 * s, y + 6 * s, self.x1 - 6 * s, y + h - 18 * s), radius=8 * s,
                                     outline=st["ink"], width=st["line_w"])
            self.sign_block((x_split + 6 * s, y + 6 * s, self.x1 - 6 * s, y + h - 18 * s))
        self.words((self.x0, y, x_split, y + h - 12 * s), inside=False)
        return y + h

    def sign_block(self, box):
        """'For SHOP NAME', the vendor's scribble and 'Proprietor'."""
        rng, st, s = self.rng, self.st, self.s
        x0, y0, x1, y1 = box
        cx = (x0 + x1) / 2
        fs = rng.uniform(20, 25) * s
        fb = self.ptext((cx, y0 + fs * 1.3), rng.choice(["For ", "For, "]) + self.sup["name"], fs, bold=True,
                        anchor="ms", max_w=x1 - x0 - 12 * s)
        lb = self.ptext((cx, y1 - 10 * s), st["signer"], fs * 0.85, anchor="ms")
        if st["sign"]:
            room = lb[1] - fb[3] - 8 * s
            if rng.random() < 0.8:
                self.vendor_signature(cx, (fb[3] + lb[1]) / 2, min(x1 - x0 - 20 * s, 300 * s), room)
            else:
                # the scribble swings up to ~0.15 of its width, so keep it between the two printed lines
                w = min(min(x1 - x0, 300 * s) * rng.uniform(0.4, 0.6), room * 2.8)
                hand.signature(self.page, (int(cx - w / 2), int((fb[3] + lb[1]) / 2)), int(w), rng, ink=self.pen.ink)
        self.sign_drawn = True

    def vendor_signature(self, cx, cy, max_w, room):
        """A name or initials dashed off in a fast slanted hand, with an underline flourish."""
        rng, s = self.rng, self.s
        pen = Pen(self.page, rng, rng.choice(["Caveat.ttf", "ReenieBeanie.ttf", "Kalam-Light.ttf"]), self.pen.ink,
                  rng.uniform(1.4, 1.9), rng.uniform(-22, -10))
        h = max(16 * s, room * 0.75)
        size = h / 1.6
        b = pen.write(rng.choice(SIGN_NAMES), cx + rng.uniform(-0.15, 0.1) * max_w, cy + size * 0.35, size, "center",
                      max_w=max_w * rng.uniform(0.45, 0.75), max_h=h)
        if b and rng.random() < 0.8:
            y = b[3] - (b[3] - b[1]) * rng.uniform(0.0, 0.25)
            pts = [(b[0] + (b[2] - b[0]) * 0.1, y + 3 * s), ((b[0] + b[2]) / 2, y + rng.uniform(2, 7) * s),
                   (b[2] + rng.uniform(8, 25) * s, y - (b[3] - b[1]) * rng.uniform(0.2, 0.6))]
            hand.pen_line(self.d, pts, rng, pen.ink, width=max(2, int(2 * s)))
        if b and rng.random() < 0.3:
            r = 2.5 * s
            dx, dy = b[2] + rng.uniform(6, 14) * s, b[3] - (b[3] - b[1]) * 0.3
            self.d.ellipse((dx - r, dy - r, dx + r, dy + r), fill=pen.ink)

    def footer_height(self):
        st, s = self.st, self.s
        h = 0
        if not (st["words"] and not self.words_inside and st["for_box"]):
            h += int(self.sign_h)
        h += int(len(st["terms"]) * 26 * s)
        if st["tagline_box"]:
            h += int(62 * s)
        if st["imprint"]:
            h += int(26 * s)
        return h + int(16 * s)

    def draw_footer(self, y):
        rng, st, s = self.rng, self.st, self.s
        y += 16 * s
        if not self.sign_drawn:
            h = self.sign_h
            self.sign_block((self.x0 + self.cw * 0.6, y + 4 * s, self.x1, y + h))
            lx, ly = self.x0, y + 34 * s
            fs = rng.uniform(17, 20) * s
            if st["bank"]:
                bank, code = rng.choice(BANKS)
                acct = "".join(rng.choice("0123456789") for _ in range(rng.choice([11, 12, 14])))
                ifsc = code + "0" + "".join(rng.choice("0123456789") for _ in range(6))
                self.ptext((lx, ly), rng.choice(["PAYMENT INFORMATION", "Bank Details :"]), fs, bold=True)
                for ln in [f"Bank: {bank}, {self.city}", f"A/c No: {acct}", f"IFSC: {ifsc}"]:
                    ly += fs * 1.3
                    self.ptext((lx, ly), ln, fs)
            elif st["receiver"]:
                self.ptext((lx, y + h - 10 * s), rng.choice(["Receiver's Signature", "Customer's Signature",
                                                              "Received the goods in good condition"]), fs)
            y += h
        ts = rng.uniform(15, 18) * s
        for t in st["terms"]:
            y += 26 * s
            self.ptext((self.x0, y), t.format(city=self.city), ts, max_w=self.cw)
        if st["tagline_box"]:
            tag = rng.choice(TAGLINES.get(self.kind, ["Wholesale & Retail"]))
            b = self.ptext((self.W / 2, y + 44 * s), tag.upper(), rng.uniform(22, 26) * s, anchor="ms",
                           max_w=self.cw * 0.9)
            self.d.rounded_rectangle((self.x0, b[1] - 12 * s, self.x1, b[3] + 12 * s), radius=10 * s,
                                     outline=st["ink"], width=st["line_w"])
            y += 62 * s
        if st["imprint"]:
            y += 24 * s
            self.ptext((self.x0, y), st["imprint"].format(city=self.city), 14 * s)
        return y

    def notes_area(self):
        """A blank patch where a receiver would scribble 'Bill-641': checked against the actual pixels."""
        arr = np.asarray(self.page).astype(int)
        paper = np.array(PAPERS[self.paper])
        s = self.s

        def blank(b):
            x0, y0, x1, y1 = (int(v) for v in b)
            if x1 - x0 < 150 * s or y1 - y0 < 45 * s:
                return False
            return not (np.abs(arr[y0:y1, x0:x1] - paper).max(axis=2) > 20).any()

        cands = [(self.W * 0.5, 10, self.x1, self.top - 8)]
        hb = self.header_box
        if hb:
            cands.append((hb[2] + 20 * s, hb[1], self.x1, hb[1] + 90 * s))
            cands.append((self.W * 0.55, hb[1], self.x1, hb[1] + 70 * s))
        cands.append((self.x0 + 10, 10, self.W * 0.45, self.top - 8))
        for c in cands:
            if blank(c):
                return tuple(int(v) for v in c)
        return (int(self.W * 0.5), 6, int(self.x1), int(max(30, self.top - 6)))

    # ------------------------------------------------------------------ main
    def draw(self):
        rng, spec = self.rng, self.spec
        self.choose()
        st, s = self.st, self.s
        self.page = Image.new("RGB", (self.W, 9000), PAPERS[self.paper])
        self.d = ImageDraw.Draw(self.page)
        self.pen = Pen(self.page, rng, st["hand_font"], st["hand_ink"], st["jitter"], st["slant"])
        self.cont_box = None

        if st["copy_mark"]:
            f = self.pfont("body_font", 16 * s, True)
            self.d.text((self.x0, self.top * 0.55), st["copy_mark"], font=f, fill=st["ink"], anchor="lm")
        y = {"centered": self.header_centered, "logo": self.header_logo, "boxed": self.header_boxed,
             "invoice": self.header_invoice}[st["header"]](self.top)
        y = int(y + rng.uniform(8, 20) * s)

        # how many grid rows fit; shrink the rows, then grow the page, if the bill is long
        row_h = st["row_h"]
        th = self.table_header_height()
        tot_h = int(row_h * rng.uniform(0.95, 1.12))
        need = len(self.row_plan) + (1 if spec["continued"] else 0) + (0 if st["landscape"] else rng.choice([0, 0, 1, 2]))
        hs0 = row_h * st["hand_frac"]
        self.hs = hs0
        self.plan_columns(hs0)
        self.totals_layout(tot_h)
        self.words_h = self.words_band_height()
        below = len(self.total_lines) * tot_h + self.words_h + self.footer_height() + int(40 * s)
        avail = self.H_nom - y - th - below
        if need * row_h > avail:
            # long bills squeeze the rows (down to what a pen can still fill); short ones just get a longer page
            floor = int(42 * s) if need > 16 else int(row_h * 0.85)
            row_h = max(floor, int(avail / max(1, need)))
        n_grid = max(need, int(avail // row_h))
        H = max(self.H_nom, y + th + n_grid * row_h + below)
        self.row_h = row_h
        self.hs = min(hs0, row_h * st["hand_frac"])

        body_y = y + th
        by = self.draw_table(y, th, n_grid, row_h)
        rows = self.fill_rows(body_y, row_h, n_grid)
        if spec["continued"] and len(self.row_plan) < n_grid:
            r = len(self.row_plan)
            a, b = self.cx["desc"]
            self.cont_box = self.pen.write(rng.choice(["continued...", "Continued..."]), a + 0.6 * self.hs,
                                           body_y + r * row_h + row_h * st["base_frac"], self.hs, max_w=b - a - 20)
        ty1, total_box = self.draw_totals(by, tot_h)
        yb = ty1
        if self.words_h:
            yb = self.draw_words_band(ty1, self.words_h)
        y_end = self.draw_footer(yb)
        H = max(H, int(y_end + 24 * s))      # never crop the footer
        if st["perforation"]:
            px = int(self.m * 0.4)
            for yy in range(0, H, int(14 * s)):
                self.d.ellipse((px - 2, yy, px + 2, yy + 4), fill=tuple(int(c * 0.82) for c in PAPERS[self.paper]))

        page = self.page.crop((0, 0, self.W, H))
        self.page = page
        clamp = lambda b: None if b is None else (max(0, int(b[0])), max(0, int(b[1])), min(self.W, int(b[2])),
                                                   min(H, int(b[3])))
        for r in rows:
            for k in ("desc_bbox", "qty_bbox", "amount_bbox"):
                r[k] = clamp(r[k])
            r["y0"], r["y1"] = max(0, int(r["y0"])), min(H, int(r["y1"]))
        layout = {
            "table_bbox": clamp((self.x0, y, self.x1 + 1, by + 1)),
            "header_bbox": clamp(self.header_box),
            "invoice_number_bbox": clamp(self.inv_box),
            "date_bbox": clamp(self.date_box),
            "rows": rows,
            "total_bbox": clamp(total_box) if not spec["continued"] else None,
            "notes_area": self.notes_area(),
            "paper": self.paper,
        }
        return page, layout


def render(spec, rng):
    """Draw spec as a hand-filled bill-book page. Returns (page, layout)."""
    return _Bill(spec, rng).draw()
