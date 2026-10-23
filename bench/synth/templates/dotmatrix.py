"""Dot-matrix bill on continuous stationery, like Green Leaf (inv01) and Nutri Leaves (inv02).

Billing software of this kind prints fixed-pitch text lines on an impact printer, so the
bill is composed on a character grid: a list of lines, each holding text at character
columns (rules are rows of '-' or '=', boxes are '+' and '|', or graphic dot lines). The
lines are then printed as ribbon dots: every glyph is a small dot bitmap (the classic 5x7
draft font, or Courier rendered 1-bit for the 24-pin NLQ look) and every set bit becomes a
soft round dot, with uneven ribbon darkness, a weak pin now and then, bidirectional
misregister and a little line-feed drift.

About a third of the bills get a pre-printed letterhead, table frame and signature block in
a coloured offset ink, with the dot-matrix data on top slightly out of register.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from bench.synth import hand

# Classic 5x7 draft font of a 9-pin printer. Rows top to bottom, '#' fires a pin.
# 7 rows sit above the baseline; glyphs with 9 rows use the two descender rows.
DRAFT_FONT = {
    " ": "..... ..... ..... ..... ..... ..... .....",
    "!": "..#.. ..#.. ..#.. ..#.. ..#.. ..... ..#..",
    '"': ".#.#. .#.#. .#.#. ..... ..... ..... .....",
    "#": ".#.#. .#.#. ##### .#.#. ##### .#.#. .#.#.",
    "$": "..#.. .#### #.#.. .###. ..#.# ####. ..#..",
    "%": "##... ##..# ...#. ..#.. .#... #..## ...##",
    "&": ".##.. #..#. #.#.. .#... #.#.# #..#. .##.#",
    "'": "..#.. ..#.. .#... ..... ..... ..... .....",
    "(": "...#. ..#.. .#... .#... .#... ..#.. ...#.",
    ")": ".#... ..#.. ...#. ...#. ...#. ..#.. .#...",
    "*": "..... ..#.. #.#.# .###. #.#.# ..#.. .....",
    "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
    ",": "..... ..... ..... ..... ..... .##.. .##.. ..#.. .#...",
    "-": "..... ..... ..... ##### ..... ..... .....",
    ".": "..... ..... ..... ..... ..... .##.. .##..",
    "/": "..... ....# ...#. ..#.. .#... #.... .....",
    "0": ".###. #...# #...# #...# #...# #...# .###.",
    "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####",
    "3": "##### ...#. ..#.. ...#. ....# #...# .###.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.",
    "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.",
    "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.",
    "9": ".###. #...# #...# .#### ....# ...#. .##..",
    ":": "..... .##.. .##.. ..... .##.. .##.. .....",
    ";": "..... .##.. .##.. ..... .##.. .##.. ..#.. .#...",
    "<": "...#. ..#.. .#... #.... .#... ..#.. ...#.",
    "=": "..... ..... ##### ..... ##### ..... .....",
    ">": ".#... ..#.. ...#. ....# ...#. ..#.. .#...",
    "?": ".###. #...# ....# ...#. ..#.. ..... ..#..",
    "@": ".###. #...# ....# .##.# #.#.# #.#.# .###.",
    "A": ".###. #...# #...# #...# ##### #...# #...#",
    "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.",
    "D": "###.. #..#. #...# #...# #...# #..#. ###..",
    "E": "##### #.... #.... ####. #.... #.... #####",
    "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .####",
    "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.",
    "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#",
    "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#",
    "N": "#...# #...# ##..# #.#.# #..## #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.",
    "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#",
    "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.",
    "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.",
    "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# #.#.# .#.#.",
    "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# #...# .#.#. ..#.. ..#.. ..#..",
    "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "[": ".###. .#... .#... .#... .#... .#... .###.",
    "\\": "..... #.... .#... ..#.. ...#. ....# .....",
    "]": ".###. ...#. ...#. ...#. ...#. ...#. .###.",
    "^": "..#.. .#.#. #...# ..... ..... ..... .....",
    "_": "..... ..... ..... ..... ..... ..... ..... ..... #####",
    "`": ".#... ..#.. ...#. ..... ..... ..... .....",
    "a": "..... ..... .###. ....# .#### #...# .####",
    "b": "#.... #.... #.##. ##..# #...# #...# ####.",
    "c": "..... ..... .###. #.... #.... #...# .###.",
    "d": "....# ....# .##.# #..## #...# #...# .####",
    "e": "..... ..... .###. #...# ##### #.... .###.",
    "f": "..##. .#..# .#... ###.. .#... .#... .#...",
    "g": "..... ..... .#### #...# #...# .#### ....# ....# .###.",
    "h": "#.... #.... #.##. ##..# #...# #...# #...#",
    "i": "..#.. ..... .##.. ..#.. ..#.. ..#.. .###.",
    "j": "...#. ..... ..##. ...#. ...#. ...#. ...#. #..#. .##..",
    "k": "#.... #.... #..#. #.#.. ##... #.#.. #..#.",
    "l": ".##.. ..#.. ..#.. ..#.. ..#.. ..#.. .###.",
    "m": "..... ..... ##.#. #.#.# #.#.# #.#.# #.#.#",
    "n": "..... ..... #.##. ##..# #...# #...# #...#",
    "o": "..... ..... .###. #...# #...# #...# .###.",
    "p": "..... ..... ####. #...# #...# ####. #.... #.... #....",
    "q": "..... ..... .#### #...# #...# .#### ....# ....# ....#",
    "r": "..... ..... #.##. ##..# #.... #.... #....",
    "s": "..... ..... .###. #.... .###. ....# ####.",
    "t": ".#... .#... ###.. .#... .#... .#..# ..##.",
    "u": "..... ..... #...# #...# #...# #..## .##.#",
    "v": "..... ..... #...# #...# #...# .#.#. ..#..",
    "w": "..... ..... #...# #...# #.#.# #.#.# .#.#.",
    "x": "..... ..... #...# .#.#. ..#.. .#.#. #...#",
    "y": "..... ..... #...# #...# #...# .#### ....# ....# .###.",
    "z": "..... ..... ##### ...#. ..#.. .#... #####",
    "{": "...#. ..#.. ..#.. .#... ..#.. ..#.. ...#.",
    "|": "..#.. ..#.. ..#.. ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "}": ".#... ..#.. ..#.. ...#. ..#.. ..#.. .#...",
    "~": "..... ..... .#... #.#.# ...#. ..... .....",
}
SLASHED_ZERO = ".###. #...# #..## #.#.# ##..# #...# .###."

PAPER_RGB = {"white": (247, 247, 243), "cream": (246, 240, 223), "pink": (250, 228, 232),
             "yellow": (250, 244, 207), "green": (228, 242, 229)}
RIBBONS = [(28, 28, 34), (62, 62, 70), (78, 42, 112), (32, 40, 88)]
CARBON_INKS = [(62, 58, 150), (45, 62, 160), (88, 58, 150)]
FORM_INKS = [(28, 58, 135), (135, 30, 45), (25, 105, 62), (35, 35, 40), (120, 62, 28)]

DESC_HEADS = {"greenleaf": ["Name of Product", "Item Name", "Product Name"],
              "nutri": ["Description of Goods", "Particulars"],
              "hsn": ["Particulars", "Description", "Item Description"],
              "tax": ["Item Description", "Description of Goods", "Particulars"],
              "simple": ["Item", "Particulars", "Item Name"]}
TAGLINES = {"veg": ["Wholesale Dealers in Vegetables", "Vegetable Commission Agents & Suppliers",
                    "Wholesale & Retail Vegetable Merchants", "Suppliers of Fresh Vegetables to Hotels & Supermarkets"],
            "exotic": ["Exotic Vegetables & Herbs", "Growers & Suppliers of Exotic Vegetables",
                       "Hill Station Vegetables - Direct from Farm"]}
USERS = ["ADMIN", "GADMIN", "SALES1", "BILLING", "OFFICE", "USER2", "MANAGER", "SUPERVISOR"]
DRIVERS = ["", "", "RAJU", "SHAJI", "ANIL", "BIJU", "MURUGAN", "SANTHOSH", "VINOD K", "SAJAN"]
BANKS = [("STATE BANK OF INDIA", "SBIN"), ("FEDERAL BANK", "FDRL"), ("SOUTH INDIAN BANK", "SIBL"),
         ("ICICI BANK", "ICIC"), ("HDFC BANK", "HDFC"), ("CANARA BANK", "CNRB"), ("UNION BANK OF INDIA", "UBIN"),
         ("DHANLAXMI BANK", "DLXB"), ("CSB BANK", "CSBK"), ("KERALA GRAMIN BANK", "KLGB")]
TERMS = ["Goods once sold will not be taken back or exchanged.",
         "Interest @ 18% p.a. will be charged on bills unpaid after 15 days.",
         "Our responsibility ceases once the goods leave our premises.",
         "Payment by A/c Payee Cheque / NEFT only.",
         "Shortage / damage must be reported at the time of delivery.",
         "Certified that the particulars given above are true and correct."]
DECLARATION = ("We declare that this invoice shows the actual price of the goods described "
               "and that all particulars are true and correct.")
SOFTWARE = ["Softland Systems", "Smart Billing", "Infotech Solutions", "Kerala Soft", "Sify Billing", "TechnoSoft"]


# ---------------------------------------------------------------- glyphs and dots

class Face:
    """Glyph bitmaps on a fixed cell: `rows` pin rows (`base` of them above the baseline),
    `cell` dots wide, capitals `cap` rows tall. No font name = the 5x7 draft font."""

    def __init__(self, font_name=None, size=None, slashed_zero=False):
        self.font = hand.font(font_name, size) if font_name else None
        self.slashed_zero = slashed_zero
        self._cache = {}
        if self.font is None:
            self.cell, self.rows, self.base, self.cap = 6, 9, 7, 7
        else:
            f = self.font
            self.cell = max(5, round(f.getlength("0")))
            top = min(f.getbbox(c, anchor="ls")[1] for c in "H|(bdl")
            bottom = max(f.getbbox(c, anchor="ls")[3] for c in "gjpqy|(,")
            self.base = -top
            self.rows = self.base + bottom
            self.cap = -f.getbbox("H", anchor="ls")[1]

    def glyph(self, ch):
        if ch not in self._cache:
            self._cache[ch] = self._draft(ch) if self.font is None else self._ttf(ch)
        return self._cache[ch]

    def _draft(self, ch):
        rows = SLASHED_ZERO if (ch == "0" and self.slashed_zero) else DRAFT_FONT.get(ch, DRAFT_FONT["?"])
        g = np.zeros((self.rows, self.cell), bool)
        for r, row in enumerate(rows.split()):
            g[r, :5] = [c == "#" for c in row]
        return g

    def _ttf(self, ch):
        im = Image.new("L", (self.cell, self.rows), 0)
        d = ImageDraw.Draw(im)
        d.fontmode = "1"
        d.text(((self.cell - self.font.getlength(ch)) / 2, self.base), ch, font=self.font, fill=255, anchor="ls")
        return np.array(im) > 127

    def bits(self, text):
        return np.hstack([self.glyph(c) for c in text])


class DotPrinter:
    """Collects the ribbon dots of a whole page, then inks them in one pass.

    px / py are the horizontal / vertical dot pitch in page pixels. Darkness varies with a
    slow wave down the page (the ribbon loop), an optional worn band across it, per line
    and per dot; the bottom pins can print light (ribbon riding high) and one pin can be weak.
    condensed (15 / 17 cpi): the printer cannot emphasize condensed text, so bold is a
    double strike a fraction of a dot lower instead of a second pass half a dot to the right.
    """

    def __init__(self, size, face, px, py, rng, darkness, condensed=False):
        self.size = size
        self.face, self.px, self.py = face, px, py
        self.rng = rng
        self.noise = np.random.default_rng(rng.randrange(1 << 30))
        # the ribbon spreads each pin strike a little wider than the pin pitch, so vertical
        # strokes read as continuous lines with a beaded edge rather than separate dots
        self.r = max(1.25, 0.5 * py * rng.uniform(1.05, 1.3))
        self.bold = (0.0, 0.35 * py) if condensed else (max(1.0, px * 0.5), 0.0)
        self.darkness = darkness
        self.bidir = rng.choice([0, 0, 1, -1, 1.5, -1.5])   # right-to-left passes land a little off
        self.wave = (rng.uniform(0.0, 0.25), rng.uniform(250, 900), rng.uniform(0, 2 * math.pi))
        self.band = (rng.uniform(0.1, 0.25) if rng.random() < 0.4 else 0.0, rng.uniform(0, size[0]),
                     rng.uniform(150, 500))
        self.weak_pin = rng.randrange(1, face.rows - 1) if rng.random() < 0.15 else None
        self.low_fade = rng.uniform(0.6, 0.8) if rng.random() < 0.2 else 1.0
        self.drift = 0.0
        self.lines = {}
        self.parts = []

    def _line(self, n):
        """Per printed line: x offset (bidirectional printing), y feed drift, ribbon factor."""
        if n not in self.lines:
            self.drift = max(-2.0, min(2.0, self.drift + self.rng.uniform(-0.4, 0.4)))
            dx = (self.bidir if n % 2 else 0) + self.rng.uniform(-0.4, 0.4)
            dy = self.drift + self.rng.uniform(-0.5, 0.5)
            ink = self.rng.uniform(0.9, 1.0) * (0.78 if self.rng.random() < 0.03 else 1.0)
            self.lines[n] = (dx, dy, ink)
        return self.lines[n]

    def _ink(self, X, Y, rows=None):
        amp, period, phase = self.wave
        v = self.darkness * (1 - amp * (0.5 + 0.5 * np.sin(2 * np.pi * Y / period + phase)))
        bamp, bx, bw = self.band
        if bamp:
            v = v * (1 - bamp * np.exp(-((X - bx) / bw) ** 2))
        v = v * self.noise.uniform(0.84, 1.0, X.shape)
        if rows is not None:
            if self.weak_pin is not None:
                v = np.where(rows == self.weak_pin, v * 0.5, v)
            v = np.where(rows >= self.face.base - 1, v * self.low_fade, v)
        return v

    def text(self, x, base_y, s, flags="", line=0):
        """Print `s` with its first cell at x and its baseline at base_y. flags: b bold
        (emphasized: every dot twice, half a dot apart), w double width, u underline.
        Returns the tight bbox of the dots, or None for blank text."""
        bits = self.face.bits(s)
        if "w" in flags:
            bits = np.repeat(bits, 2, axis=1)
        rows, cols = np.nonzero(bits)
        if rows.size == 0:
            return None
        dx, dy, ink = self._line(line)
        X = x + dx + cols * self.px
        Y = base_y + dy - (self.face.base - rows - 0.5) * self.py
        V = self._ink(X, Y, rows) * ink
        self.parts.append((X, Y, V))
        x1, y1 = X.max(), Y.max()
        if "b" in flags:
            bdx, bdy = self.bold
            self.parts.append((X + bdx, Y + bdy, V))
            x1, y1 = x1 + bdx, y1 + bdy
        if "u" in flags:
            ux = np.arange(X.min(), x1 + 0.1, self.px)
            uy = np.full(ux.shape, base_y + dy + 1.3 * self.py)
            self.parts.append((ux, uy, self._ink(ux, uy) * ink))
            y1 = max(y1, uy[0])
        r = self.r
        return [X.min() - r, Y.min() - r, x1 + r, y1 + r]

    def rule(self, x0, x1, y, line=0, step=None):
        """A graphic horizontal rule: one row of dots."""
        dx, dy, ink = self._line(line)
        X = np.arange(x0, x1, step or self.px) + dx
        Y = np.full(X.shape, y + dy)
        self.parts.append((X, Y, self._ink(X, Y) * ink))
        return [x0 - self.r, y + dy - self.r, x1 + self.r, y + dy + self.r]

    def vrule(self, x, y0, y1):
        Y = np.arange(y0, y1, self.py)
        X = np.full(Y.shape, float(x))
        self.parts.append((X, Y, self._ink(X, Y)))

    def coverage(self):
        """Ink coverage 0..1 of the page: every dot centre stamped with a soft round dot."""
        W, H = self.size
        k = int(math.ceil(self.r + 0.5))
        C = np.zeros((H + 2 * k, W + 2 * k), np.float32)
        if self.parts:
            X = np.concatenate([p[0] for p in self.parts])
            Y = np.concatenate([p[1] for p in self.parts])
            V = np.concatenate([p[2] for p in self.parts]).astype(np.float32)
            xi, yi = np.rint(X).astype(int), np.rint(Y).astype(int)
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            np.maximum.at(C, (yi[ok] + k, xi[ok] + k), V[ok])
        out = np.zeros((H, W), np.float32)
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                d = math.hypot(dx, dy)
                w = min(1.0, self.r + 0.5 - d) * (1 - 0.3 * (d / (self.r + 0.5)) ** 2)
                if w > 0:
                    np.maximum(out, C[k - dy:k - dy + H, k - dx:k - dx + W] * w, out=out)
        return out

    def ink_onto(self, page, color, blur=0.0):
        cov = np.clip(self.coverage(), 0, 1)
        if blur:
            im = Image.fromarray((cov * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur))
            cov = np.asarray(im, np.float32) / 255
        arr = np.asarray(page, np.float32)
        absorb = 1 - np.array(color, np.float32) / 255
        arr = arr * (1 - cov[..., None] * absorb)
        return Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- number formatting

def _indian(digits):
    """'1234567' -> '12,34,567'."""
    if len(digits) <= 3:
        return digits
    head, groups = digits[:-3], [digits[-3:]]
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + groups)


def _money(v, style, whole=False):
    """1609.2 -> '1,609.20' (indian / western grouping) or '1609.20' (plain); whole drops '.00'."""
    ip, fp = f"{abs(v):.2f}".split(".")
    if style == "indian":
        ip = _indian(ip)
    elif style == "western":
        ip = f"{int(ip):,}"
    s = ip if (whole and fp == "00") else f"{ip}.{fp}"
    return "-" + s if v < 0 else s


def _qty(q, style):
    """Quantity as the software prints it, never dropping a significant digit.
    d3: 5.000, d2: 5.00, w5: a 5-character field like 10.00 / 5.000 / 140.0, plain: 5 / 2.5."""
    exact = f"{q:.3f}".rstrip("0").rstrip(".") if isinstance(q, float) else str(q)
    need = len(exact.split(".")[1]) if "." in exact else 0
    if style == "plain":
        return exact
    d = {"d3": 3, "d2": 2}.get(style, max(0, 4 - len(str(int(q)))))
    return f"{q:.{max(d, need)}f}"


def _whole(values):
    return all(abs(v - round(v)) < 1e-9 for v in values)


def _wrap(text, width):
    """Greedy word wrap; a word longer than the width is split."""
    if len(text) <= width:
        return [text]
    lines, cur = [], ""
    for w in text.split():
        while len(w) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(w[:width])
            w = w[width:]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- appearance

def _style(spec, rng):
    """Every random appearance choice for one bill."""
    s = {}
    s["dpi"] = dpi = rng.uniform(180, 200)
    fmt = rng.choices(["fanfold", "torn", "a4"], [45, 30, 25])[0]
    if fmt == "a4":
        w_in, h_in = 8.27, 11.69
    elif fmt == "fanfold":
        w_in, h_in = rng.choice([10, 10, 9.5]), rng.choice([12, 12, 11])
    else:   # tractor strips torn off
        w_in, h_in = rng.choice([9, 9, 8.5]), rng.choice([12, 12, 11])
    s["size"] = (int(w_in * dpi), int(h_in * dpi))
    s["strips"] = int(0.5 * dpi) if fmt == "fanfold" else 0
    s["paper"] = rng.choices(list(PAPER_RGB), [70, 18, 4, 4, 4])[0]
    s["carbon"] = s["paper"] in ("pink", "yellow", "green") and rng.random() < 0.6
    s["greenbar"] = fmt == "fanfold" and s["paper"] == "white" and rng.random() < 0.18
    # Courier Prime Bold fills its counters when rendered 1-bit (3 reads as 9), so NLQ uses the regular cut
    s["face"] = rng.choices(["draft", "typewriter"], [65, 35])[0]
    s["face_size"] = rng.choice([14, 15])
    s["body_bold"] = rng.random() < 0.3       # emphasized mode for everything, as many shops set it
    s["slashed_zero"] = rng.random() < 0.5
    s["cap_px"] = rng.uniform(17, 21)
    pref = rng.choice([10, 10, 12])
    s["cpis"] = [pref] + [c for c in (12, 15, 17) if c > pref]
    s["extra_cols"] = rng.randint(0, 24)
    s["frame"] = rng.choices(["dash", "ascii", "grid", "form"], [30, 18, 20, 32])[0]
    s["greenbar"] = s["greenbar"] and s["frame"] != "form"   # pre-printed stationery is plain paper
    if s["carbon"]:   # carbonless duplicate: blue-violet, a little fuzzy
        s["ink"], s["darkness"], s["blur"] = rng.choice(CARBON_INKS), rng.uniform(0.88, 1.0), rng.uniform(0.3, 0.55)
    else:
        s["ink"] = rng.choices(RIBBONS, [45, 15, 25, 15])[0]
        s["darkness"], s["blur"] = rng.uniform(0.85, 1.0), (rng.uniform(0.3, 0.5) if rng.random() < 0.3 else 0.0)

    tm = spec["tax_mode"]
    if tm == "inclusive":
        s["variant"] = rng.choice(["greenleaf", "tax"])
    elif tm == "exclusive":
        s["variant"] = rng.choice(["greenleaf", "tax", "tax", "hsn", "nutri", "simple"])
    else:
        s["variant"] = rng.choices(["greenleaf", "nutri", "hsn", "tax", "simple"], [30, 25, 15, 10, 20])[0]
    s["money"] = rng.choice(["indian", "indian", "western", "plain", "plain"])
    s["qty"] = rng.choice(["d3", "d2", "w5", "plain"])
    s["sno_fmt"] = rng.choice(["{}", "{}", "{}.", "{:02d}"])
    s["amt_whole"] = rng.random() < 0.12
    s["net_whole"] = rng.random() < 0.7
    s["rate_whole"] = rng.random() < 0.2
    s["po_number"] = rng.random() < 0.4

    # letterhead / party block
    s["head_align"] = rng.choice(["center", "center", "center", "left"])
    s["name_wide"] = rng.random() < 0.75
    s["addr_join"] = rng.random() < 0.5
    s["tagline"] = rng.choice(TAGLINES.get(spec["supplier_kind"], ["Wholesale Suppliers"])) if rng.random() < 0.4 else None
    s["state_line"] = rng.random() < 0.3
    s["top_info"] = s["frame"] != "form" and rng.random() < 0.2   # inv02: invoice no / date above the letterhead
    sup = spec["supplier"]
    if tm != "none":
        titles = ["TAX INVOICE", "TAX INVOICE", "SALES INVOICE", "INVOICE"]
    elif sup["gstin"]:
        titles = ["SALES INVOICE", "TAX INVOICE", "BILL OF SUPPLY", "INVOICE", "CREDIT BILL"]
    else:
        titles = ["SALES BILL", "CREDIT BILL", "CASH / CREDIT BILL", "INVOICE", "BILL"]
    s["title"] = rng.choice(titles)
    s["title_flags"] = rng.choice(["b", "bw", "bu", "u", ""])
    s["copy"] = (rng.choice(["DUPLICATE", "TRIPLICATE", "OFFICE COPY", "DUPLICATE FOR TRANSPORTER"])
                 if s["paper"] in ("pink", "yellow", "green") else
                 rng.choice([None, None, "ORIGINAL", "ORIGINAL FOR RECIPIENT"]))
    s["inv_lbl"] = rng.choice(["Bill No", "Invoice No", "Inv. No.", "Bill No.", "Voucher No"])
    s["date_lbl"] = rng.choice(["Bill Date", "Date", "Dated", "Inv. Date"])
    s["time"] = (f"{rng.randint(1, 12):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d} {rng.choice(['AM', 'PM'])}"
                 if rng.random() < 0.45 else None)
    disp = spec["buyer"]["display"]
    s["name_lbl"] = rng.choice(["Name", "To", "Party", "Customer"] + ([] if disp.startswith("M/s") else ["M/s."]))
    s["buyer_addr"] = rng.choice(["none", "city", "full"])
    s["buyer_gst_lbl"] = rng.choice(["GST NO.", "GSTIN", "Party GSTIN", None])
    extras = []
    if rng.random() < 0.5:
        extras.append(("User", rng.choice(USERS)))
    if rng.random() < 0.4:
        extras.append(("Driver", rng.choice(DRIVERS)))
    if rng.random() < 0.25:
        st = "TN" if sup["state"] == "Tamil Nadu" else "KA" if sup["state"] == "Karnataka" else "KL"
        extras.append(("Vehicle No", f"{st}-{rng.randint(1, 65):02d}-{rng.choice('ABCDEFGHJK')}"
                                     f"{rng.choice('ABCDEFGHJK')}-{rng.randint(1000, 9999)}"))
    if rng.random() < 0.15:
        extras.append(("Route", rng.choice(["KAKKANAD", "EKM CITY", "ROUTE 3", "ALUVA-KKD", "INFOPARK"])))
    if spec["continued"] or rng.random() < 0.15:
        extras.append(("Page", "1 of 2" if spec["continued"] else "1 of 1"))
    s["extras"] = extras

    # footer
    s["items_count"] = rng.random() < 0.5
    s["grand_lbl"] = rng.choice(["GRAND TOTAL", "NET AMOUNT", "Net Amount", "Bill Amount", "TOTAL AMOUNT", "Net Payable"])
    s["sub_lbl"] = rng.choice(["Sub Total", "Gross Amount", "Total", "Total Value"])
    s["taxable_lbl"] = rng.choice(["Taxable Amount", "Sub Total", "Taxable Value", "Gross Amount"])
    s["top_rule"] = rng.choice(["-", "-", "="])
    s["ro_lbl"] = rng.choice(["Round Off", "Rounded Off", "R/Off", "Round off"])
    s["show_sub"] = rng.random() < 0.6
    s["zero_round"] = rng.random() < 0.25
    s["grand_rules"] = rng.random() < 0.6
    s["rs_prefix"] = rng.random() < 0.2
    s["words_above"] = rng.random() < 0.4
    s["words_lbl"] = rng.choice(["In Words : ", "Amount in words : ", "Rs. in words : "])
    s["eoe"] = rng.random() < 0.6 and s["frame"] != "form"   # forms carry it pre-printed
    s["prev_bal"] = round(rng.uniform(3000, 150000), 2) if rng.random() < 0.3 else None
    s["trays"] = rng.random() < 0.35
    if rng.random() < 0.4:
        bank, code = rng.choice(BANKS)
        s["bank"] = (bank, "".join(rng.choice("0123456789") for _ in range(rng.choice([11, 12, 14]))),
                     f"{code}0{rng.randint(0, 99999):06d}"[:11])
    else:
        s["bank"] = None
    s["declaration"] = rng.random() < 0.3
    s["terms"] = rng.sample(TERMS, rng.randint(2, 3)) if rng.random() < 0.4 else []
    s["sign"] = rng.choice(["for", "for", "inv02"])
    s["computer"] = rng.choice([None, None, "This is a Computer Generated Invoice", "** Thank You, Visit Again **"])
    s["software"] = (f"Software by {rng.choice(SOFTWARE)}, Ph: {rng.choice('98')}{rng.randint(100000000, 999999999)}"
                     if rng.random() < 0.2 else None)
    s["spring"] = s["frame"] == "form" or rng.random() < 0.4
    s["continued_txt"] = rng.choice(["Continued...", "Continued on next page...", "*** Continued ***",
                                     "contd.. on Page 2", "-- Continued --"])

    # pre-printed form
    if s["frame"] == "form":
        s["form_ink"] = rng.choice(FORM_INKS)
        s["form_name_font"] = rng.choice(["serif_bold", "condensed", "sans", "typewriter_bold", "serif_bold"])
        s["form_font"] = rng.choice(["sans", "serif", "narrow", "sans2"])
        s["logo"] = rng.choice(["circle", "ring", "leaf", "box", None])
        s["head_layout"] = rng.choice(["stacked", "corners"])
        s["form_head_h"] = int(rng.uniform(1.35, 1.75) * dpi)
        s["form_foot_h"] = int(rng.uniform(0.75, 0.95) * dpi)
        s["register"] = (rng.uniform(-6, 6), rng.uniform(-4, 7))
        s["form_terms"] = rng.random() < 0.6
    s["top"] = int(rng.uniform(0.45, 0.85) * dpi)
    # a continued page ends where the software skipped over the perforation (about an inch)
    s["bottom"] = int(rng.uniform(*((0.75, 1.1) if spec["continued"] else (0.3, 0.5))) * dpi)
    s["x_shift"] = rng.uniform(-0.12, 0.12) * dpi
    return s


# ---------------------------------------------------------------- table columns

def _cols(spec, s, rng):
    items, v, m = spec["items"], s["variant"], s["money"]
    tm = spec["tax_mode"]

    def col(key, head, values, align="r", group=None):
        head = head if isinstance(head, list) else [head]
        return {"key": key, "head": head, "values": values, "align": align, "group": group,
                "w0": max([len(h) for h in head] + [len(x) for x in values])}

    rate_whole = s["rate_whole"] and _whole([it["rate"] for it in items])
    amt_whole = s["amt_whole"] and _whole([it["amount"] for it in items])
    net_whole = s["net_whole"] and _whole([it["taxable"] for it in items])
    sno = col("sno", ["Sl.", "No."] if v == "nutri" else rng.choice(["SNo", "Sl.", "S.No", "Sl.No", "No."]),
              [s["sno_fmt"].format(i + 1) for i in range(len(items))])
    desc = col("desc", rng.choice(DESC_HEADS[v]), [it["description"] for it in items], "l")
    qtys = [_qty(it["quantity"], s["qty"]) for it in items]
    units = [it["unit"] for it in items]
    rate = col("rate", "Rate", [_money(it["rate"], m, rate_whole) for it in items])
    amounts = [_money(it["amount"], m, amt_whole) for it in items]
    pct = rng.choice(["{:g}", "{:.2f}"])
    gst = col("gst", rng.choice(["GST%", "Tax %", "GST"]), [pct.format(it["tax_percent"]) for it in items])
    taxable = [_money(it["taxable"], m, net_whole) for it in items]
    hsn = col("hsn", rng.choice(["HSN", "HSN Code", "HSN/SAC"]), [it["hsn"] for it in items], "l")
    unit_head = rng.choice(["UOM", "Unit"])
    # a column headed "Total" after GST% must include the tax, so pre-tax (exclusive) line
    # amounts get a plain "Amount"-style head
    if v == "greenleaf":
        cols = [sno, desc, col("qty", "Qty", qtys), col("unit", unit_head, units, "l"), rate]
        if tm == "exclusive":
            cols += [gst, col("amount", rng.choice(["Net Amount", "Taxable Amt", "Amount"]), amounts)]
        else:
            cols.append(col("net", rng.choice(["Net Amount", "Net Amt", "Value"]), taxable))
            if tm == "inclusive":
                cols.append(gst)
            cols.append(col("amount", "Total", amounts))
    elif v == "nutri":
        cols = [sno, desc, col("qty_ship", "Shipped", qtys, group="Quantity"),
                col("qty", "Billed", qtys, group="Quantity"), rate, col("unit", "Per", units, "l"),
                col("amount", "Amount", amounts)]
    elif v == "hsn":
        cols = [sno, desc, hsn, col("qty", rng.choice(["Qty", "Quantity"]), qtys), col("unit", unit_head, units, "l"),
                rate, col("amount", rng.choice(["Amount", "Amount Rs."]), amounts)]
    elif v == "tax":
        cols = [sno, desc, hsn, col("qty", "Qty", qtys), col("unit", unit_head, units, "l"), rate]
        if tm == "inclusive":
            cols.append(col("net", "Taxable", taxable))
        cols += [gst, col("amount", rng.choice(["Amount", "Value"] if tm == "exclusive" else ["Amount", "Total"]),
                          amounts)]
    else:
        disc = rng.choice(["0.00", "-", "0"])
        cols = [sno, desc, col("unit", unit_head, units, "l"), col("qty", "Qty", qtys), rate,
                col("disc", "Disc", [disc] * len(items)), col("amount", rng.choice(["Amount", "Value"]), amounts)]
    return cols


def _place(cols, s, desc_w):
    """Give every column its start and width on the character grid. Boxed frames get a
    border column at both ends and a separator column between columns; returns
    (total width, separator columns)."""
    boxed = s["frame"] != "dash"
    pad, gap = (1, 1) if boxed else (0, 2)
    x = 1 if boxed else 0
    seps = [0] if boxed else []
    for i, c in enumerate(cols):
        c["w"] = desc_w if c["key"] == "desc" else c["w0"]
        c["x"] = x + pad
        x += c["w"] + 2 * pad
        if i < len(cols) - 1:
            if boxed:
                seps.append(x)
            x += gap
    if boxed:
        seps.append(x)
        x += 1
    return x, seps


def _inner_seps(cols, seps):
    """Separators between two columns of one group ("Quantity: Shipped | Billed"); they stop
    below the group label."""
    return {seps[i + 1] for i in range(len(cols) - 1) if cols[i]["group"] and cols[i]["group"] == cols[i + 1]["group"]}


def _pitch(cols, s):
    """Pick the character pitch (the widest that fits the table, down to 17 cpi condensed) and
    the description width; the description column takes the slack of the printed line.
    Returns (character width in pixels, description width in characters)."""
    dpi, (Wp, _) = s["dpi"], s["size"]
    desc = next(c for c in cols if c["key"] == "desc")
    n_min = _place(cols, s, desc["w0"])[0]
    avail = Wp - 2 * s["strips"] - 0.8 * dpi   # the printer cannot reach the paper edge
    for cpi in s["cpis"]:
        maxcols = int(avail // (dpi / cpi))
        if n_min <= maxcols:
            break
    desc_w = desc["w0"]
    if n_min > maxcols:   # even 17 cpi is too narrow: wrap the descriptions
        desc_w = max(max(len(h) for h in desc["head"]), 12, desc_w - (n_min - maxcols))
        n_min = _place(cols, s, desc_w)[0]
    target = min(maxcols, max(n_min + s["extra_cols"], 64))
    desc_w += max(0, target - n_min)
    return dpi / cpi, desc_w


# ---------------------------------------------------------------- composing the lines

def _compose(spec, s, cols, seps, W):
    """The bill as a list of lines on a W-column grid. A line is a dict with zone
    (head / thead / row / foot), kind and segs: (column, text, tag, flags) tuples; tags name
    what the layout needs bboxes of. Kinds: text, grule (graphic rule), band (pre-printed
    table header), gap (half-line space), spring (takes the leftover height), fend (bottom
    of the pre-printed table frame)."""
    L = []
    sup, frame = spec["supplier"], s["frame"]
    boxed = frame != "dash"

    def line(zone, *segs, kind="text", item=None, **kw):
        L.append(dict(zone=zone, kind=kind, segs=[g for g in segs if g], item=item, **kw))

    def seg(col, text, tag=None, flags=""):
        return (max(0, int(col)), text, tag, flags) if text else None

    def placed(text, flags="", align=None):
        n = len(text) * (2 if "w" in flags else 1)
        align = align or s["head_align"]
        return 0 if align == "left" else (W - n) // 2 if align == "center" else W - n

    def rule(zone, ch, tag):
        if frame == "grid":
            line(zone, kind="grule")
        elif frame == "ascii":
            line(zone, seg(0, "".join("+" if i in seps else ch for i in range(W)), tag))
        else:
            line(zone, seg(0, ch * W, tag))

    inv, date = spec["invoice_number_printed"], spec["date_printed"]
    if s["top_info"]:
        a, b = s["inv_lbl"] + "  ", s["date_lbl"] + "  "
        line("head", seg(0, a), seg(len(a), inv, "inv_no"), seg(W - len(b) - len(date), b),
             seg(W - len(date), date, "date"))
        line("head")

    # letterhead (pre-printed forms carry it on the paper instead)
    if frame != "form":
        name = sup["name"]
        flags = "bw" if s["name_wide"] and 2 * len(name) <= W else "b"
        line("head", seg(placed(name, flags), name, "head", flags))
        if s["tagline"]:
            line("head", seg(placed(s["tagline"]), s["tagline"], "head"))
        addr = ", ".join(sup["address_lines"])
        for a in ([addr] if s["addr_join"] and len(addr) <= W else sup["address_lines"]):
            for part in _wrap(a, W):
                line("head", seg(placed(part), part, "head"))
        contact = f"Ph : {sup['phone']}" + (f"   E-mail : {sup['email']}" if sup["email"] else "")
        ids = "   ".join(x for x in (f"GSTIN : {sup['gstin']}" if sup["gstin"] else "",
                                     f"FSSAI No : {sup['fssai']}" if sup["fssai"] else "") if x)
        for text in (contact, ids):
            for part in (_wrap(text, W) if text else []):
                line("head", seg(placed(part), part, "head"))
        if s["state_line"]:
            t = f"State : {sup['state']}   State Code : {sup['state_code']}"
            line("head", seg(placed(t), t, "head"))
        line("head", seg(0, ("=" if frame == "dash" else "-") * W, "rule"))
        t, tf = s["title"], s["title_flags"]
        tl = len(t) * (2 if "w" in tf else 1)
        segs = [seg(placed(t, tf, "center"), t, "title", tf)]
        if s["copy"]:
            if (W + tl) // 2 + 2 + len(s["copy"]) <= W:
                segs.append(seg(W - len(s["copy"]), s["copy"]))
            else:
                line("head", seg(W - len(s["copy"]), s["copy"]))
        line("head", *segs)
        line("head", seg(0, "-" * W, "rule"))
    elif s["copy"]:
        line("head", seg(W - len(s["copy"]), s["copy"]))

    # party block: buyer on the left, bill number / date / extras on the right
    disp = spec["buyer"]["display"]
    lw = max(9, len(s["name_lbl"]) + 2)   # address lines line up under the name
    left = [(f"{s['name_lbl']:<{lw - 2}}: ", disp, None)]
    baddr = spec["buyer"]["address_lines"]
    if s["buyer_addr"] == "city":
        left.append((" " * lw, "KAKKANAD", None))
    elif s["buyer_addr"] == "full":
        left += [(" " * lw, a, None) for a in baddr]
    if s["buyer_gst_lbl"]:
        left.append((f"{s['buyer_gst_lbl']:<{lw - 2}}: " if len(s["buyer_gst_lbl"]) < lw - 1
                     else s["buyer_gst_lbl"] + ": ", spec["buyer"]["gstin"], None))
    right = []
    if not s["top_info"]:
        right += [(f"{s['inv_lbl']:<10}: ", inv, "inv_no"), (f"{s['date_lbl']:<10}: ", date, "date")]
    right += [(f"{k:<10}: ", val, None) for k, val in s["extras"]]
    rw = max([len(a) + len(b) + (len(s["time"]) + 1 if tag == "date" and s["time"] else 0)
              for a, b, tag in right] + [0])
    lwid = max(len(a) + len(b) for a, b, _ in left)
    rcol = W - rw
    stacked = lwid + 3 > rcol
    pairs = ([(e, None) for e in left] + [(None, e) for e in right]) if stacked else \
        [(left[i] if i < len(left) else None, right[i] if i < len(right) else None)
         for i in range(max(len(left), len(right)))]
    for le, re in pairs:
        segs = []
        if le:
            segs += [seg(0, le[0]), seg(len(le[0]), le[1], le[2])]
        if re:
            c = 0 if stacked else rcol
            segs += [seg(c, re[0]), seg(c + len(re[0]), re[1], re[2])]
            if re[2] == "date" and s["time"]:
                segs.append(seg(c + len(re[0]) + len(re[1]) + 1, s["time"]))
        line("head", *segs)

    # table header
    nh = max(len(c["head"]) + (1 if c["group"] else 0) for c in cols)
    desc = next(c for c in cols if c["key"] == "desc")
    inner = _inner_seps(cols, seps) if boxed else set()
    if frame == "form":
        line("thead", kind="gap")
        line("thead", kind="band", nh=nh)
        line("thead", kind="gap")
    else:
        rule("thead", s["top_rule"], "thead")
        for k in range(nh):
            segs = []
            for c in cols:
                head = [""] * (nh - len(c["head"])) + c["head"]
                if c["group"] and k == 0:
                    continue
                h = head[k]
                x = c["x"] + (c["w"] - len(h) if c["align"] == "r" else 0)
                segs.append(seg(x, h, "thead"))
            groups = {}
            for c in cols:
                if c["group"]:
                    groups.setdefault(c["group"], []).append(c)
            if k == 0:
                for g, gc in groups.items():
                    x0, x1 = gc[0]["x"], gc[-1]["x"] + gc[-1]["w"]
                    segs.append(seg((x0 + x1 - len(g)) // 2, g, "thead"))
            if k == nh - 1 and s["po_number"] and s["variant"] == "greenleaf" and \
                    len(desc["head"][0]) + 14 <= desc["w"]:
                segs.append(seg(desc["x"] + len(desc["head"][0]) + 3, "PO NUMBER:", "thead", "u"))
            if frame == "ascii":
                segs += [seg(x, "|", "thead") for x in seps if not (k == 0 and x in inner)]
            line("thead", *segs)
        rule("thead", "-", "thead")

    # item rows
    for i, it in enumerate(spec["items"]):
        for k, part in enumerate(_wrap(it["description"], desc["w"])):
            segs = [seg(desc["x"], part, ("desc", i))]
            if k == 0:
                for c in cols:
                    if c["key"] == "desc":
                        continue
                    val = c["values"][i]
                    x = c["x"] + (c["w"] - len(val) if c["align"] == "r" else 0)
                    tag = (c["key"], i) if c["key"] in ("qty", "amount") else ("cell", i)
                    segs.append(seg(x, val, tag))
            if frame == "ascii":
                segs += [seg(x, "|", "rule") for x in seps]
            line("row", *segs, item=i)

    amt = next(c for c in cols if c["key"] == "amount")
    vr = amt["x"] + amt["w"]
    if frame == "form":
        if s["spring"]:
            line("row", kind="spring")
        line("row", kind="fend")
    else:
        rule("foot", "-", "tbottom")

    if spec["continued"]:
        t = s["continued_txt"]
        line("foot", seg(W - len(t) - 1, t, "contd"))
        if frame == "form":
            line("foot", kind="gap")
        return L

    # totals, right-aligned under the amount column
    T, tm = spec["totals"], spec["tax_mode"]
    m = s["money"]
    entries = []
    if tm == "none":
        if T["round_off"] or s["show_sub"]:
            entries.append((s["sub_lbl"], T["subtotal"]))
    else:
        entries.append(("Taxable Value" if tm == "inclusive" else s["taxable_lbl"], T["subtotal"]))
        entries += [("CGST", T["cgst"]), ("SGST", T["sgst"])]
    for k in ("igst", "cess"):
        if T[k]:
            entries.append((k.upper(), T[k]))
    if T["round_off"] or s["zero_round"]:
        entries.append((s["ro_lbl"], T["round_off"]))
    left_info = f"No. of Items : {len(spec['items'])}" if s["items_count"] else None
    for n, (lab, val) in enumerate(entries):
        txt = _money(val, m)
        if lab == s["ro_lbl"] and val > 0 and m != "plain":
            txt = "+" + txt
        lab = f"{lab} :"
        lc = amt["x"] - 2 - len(lab) if amt["x"] - 2 - len(lab) > 0 else 0
        segs = [seg(lc, lab, "tlabel"), seg(vr - len(txt), txt, "tvalue")]
        if n == 0 and left_info and len(left_info) + 2 < lc:
            segs.append(seg(0, left_info))
            left_info = None
        line("foot", *segs)
    if left_info:
        line("foot", seg(0, left_info))
    gtxt = ("Rs. " if s["rs_prefix"] else "") + _money(T["grand_total"], m)
    glab = f"{s['grand_lbl']} :"
    gx = vr - len(gtxt)
    if s["grand_rules"]:
        line("foot", seg(min(gx, amt["x"]), "-" * (vr - min(gx, amt["x"])), "rule"))
    line("foot", seg(max(0, min(gx, amt["x"]) - 2 - len(glab)), glab, "grand", "b"), seg(gx, gtxt, "grand", "b"))
    if s["grand_rules"]:
        line("foot", seg(min(gx, amt["x"]), "=" * (vr - min(gx, amt["x"])), "rule"))

    # amount in words and the rest of the footer
    words = spec["amount_in_words"]
    eoe = "E.& O.E." if s["eoe"] else None
    if s["words_above"]:
        line("foot", seg(0, "Amount Chargeable (in words)"), seg(W - len(eoe), eoe) if eoe else None)
        for part in _wrap(words, W):
            line("foot", seg(0, part, "words"))
    else:
        lab = s["words_lbl"]
        parts = _wrap(words, W - len(lab))
        for k, part in enumerate(parts):
            line("foot", seg(0, lab) if k == 0 else None, seg(len(lab), part, "words"))
        if eoe:
            line("foot", seg(W - len(eoe), eoe))
    if s["declaration"]:
        for k, part in enumerate(_wrap("Declaration : " + DECLARATION, W)):
            line("foot", seg(0, part))
    if s["bank"]:
        bank, acno, ifsc = s["bank"]
        branch = sup["address_lines"][-1].split(",")[0]
        a, b = f"Bank Details : {bank}, Branch: {branch}", f"A/c No.: {acno}  IFSC : {ifsc}"
        if len(a) + 2 + len(b) <= W:
            line("foot", seg(0, f"{a}  {b}"))
        else:   # the software breaks between fields, not inside "IFSC : ..."
            line("foot", seg(0, a))
            line("foot", seg(15, b))
    if s["prev_bal"] is not None:
        line("foot")
        pb = _money(s["prev_bal"], m)
        line("foot", seg(0, "Previous Balance : "), seg(19, pb))
        tot = _money(round(s["prev_bal"] + T["grand_total"], 2), m)
        line("foot", seg(0, "Total Outstanding: "), seg(19, tot))
    if s["trays"]:
        line("foot", seg(0, "Trays Out : ______     Trays In : ______"))
    if s["terms"]:
        line("foot", seg(0, "Terms & Conditions :", None, "u"))
        for k, t in enumerate(s["terms"]):
            for j, part in enumerate(_wrap(f"{k + 1}. {t}", W)):
                line("foot", seg(0 if j == 0 else 3, part))
    if s["spring"] and frame != "form":
        line("foot", kind="spring")
    if frame != "form":
        line("foot")
        line("foot")
        if s["sign"] == "inv02":
            a, b, c = "Customer's Seal and Signature", "Prepared by", "Verified by"
            line("foot", seg(0, a), seg(len(a) + max(3, (W - len(a) - 25) // 2), b), seg(W - len(c), c))
        else:
            f = f"For {sup['name']}"
            line("foot", seg(0, "Receiver's Signature"), seg(W - len(f), f, None, "b"))
            line("foot")
            line("foot", seg(W - 20, "Authorised Signatory"))
    if s["computer"]:
        line("foot", seg((W - len(s["computer"])) // 2, s["computer"]))
    if s["software"]:
        line("foot", seg(W - len(s["software"]), s["software"]))
    if frame == "form":   # keep clear of the pre-printed signature block
        line("foot", kind="gap")
    return L


# ---------------------------------------------------------------- fitting the page

def _height(ln, lh, lh_tab):
    """Vertical space a line takes at line pitch lh (item rows: lh_tab). Springs take the leftover."""
    kind = ln["kind"]
    if kind == "text":
        return lh_tab if ln["zone"] == "row" else lh
    return {"grule": 0.5 * lh, "band": (ln.get("nh", 1) * 1.1 + 0.5) * lh, "fend": 0.3 * lh,
            "gap": 0.4 * lh}.get(kind, 0.0)


def _fixed(s):
    return s["top"] + s["bottom"] + s.get("form_head_h", 0) + s.get("form_foot_h", 0)


def _fit(lines, s, face, page_full=False):
    """Choose the dot pitch and line spacings so everything fits on the sheet; a bill that
    does not fit even at 9 lpi gets a longer sheet. page_full: page 1 of a continued bill,
    where the software broke the page because it was full, so the sheet ends just below the
    last row. Returns (py, lh, lh_tab, page height)."""
    dpi, Hp = s["dpi"], s["size"][1]
    n_rows = sum(1 for ln in lines if ln["kind"] == "text" and ln["zone"] == "row")
    fixed = _fixed(s)
    py0 = s["cap_px"] / face.cap
    for scale in (1.0, 0.92, 0.84, 0.76):
        py = py0 * scale
        lh_min = face.rows * py + 1
        for lpi in (6, 6.5, 7, 7.5, 8, 9):
            lh = dpi / lpi
            if lh < lh_min:
                break
            other = sum(_height(ln, lh, 0) for ln in lines)
            if fixed + other + n_rows * lh_min <= Hp:
                lh_tab = max(lh_min, min(lh, (Hp - fixed - other) / max(1, n_rows)))
                if page_full:
                    Hp = min(Hp, int(math.ceil(fixed + other + n_rows * lh_tab)) + 2)
                return py, lh, lh_tab, Hp
    other = sum(_height(ln, lh_min, 0) for ln in lines)
    return py, lh_min, lh_min, int(math.ceil(fixed + other + n_rows * lh_min)) + 2


# ---------------------------------------------------------------- paper and pre-printed form

def _paper(s, rng, size):
    Wp, Hp = size
    dpi, sw = s["dpi"], s["strips"]
    base = tuple(max(0, min(255, c + rng.randint(-3, 3))) for c in PAPER_RGB[s["paper"]])
    page = Image.new("RGB", size, base)
    d = ImageDraw.Draw(page)
    if s["greenbar"]:
        band = dpi / 2
        y = s["top"] - rng.uniform(0, band) - 2 * band
        while y < Hp:
            d.rectangle([sw, int(y), Wp - sw, int(y + band)], fill=(220, 237, 221))
            y += 2 * band
    if sw:
        perf = tuple(int(c * 0.86) for c in base)
        for x in (sw, Wp - sw):
            for y in range(rng.randint(0, 8), Hp, 9):
                d.line([(x, y), (x, y + 5)], fill=perf)
        r, pitch = 0.078 * dpi, dpi / 2
        y = rng.uniform(0.15, 0.35) * dpi
        hole = (150, 150, 146)
        while y < Hp + r:
            for cx in (sw / 2, Wp - sw / 2):
                d.ellipse([cx - r, y - r, cx + r, y + r], fill=hole)
                d.arc([cx - r, y - r, cx + r, y + r], 200, 340, fill=(110, 110, 108), width=3)
            y += pitch
    return page


def _initials(name):
    words = [w for w in name.replace(".", " ").split() if w not in ("ST", "&", "THE")]
    return "".join(w[0] for w in words[:2]) or name[:2]


def _logo(d, kind, box, name, ink, paper, rng):
    x0, y0, x1, y1 = box
    L = x1 - x0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ini = _initials(name)
    f = hand.font("serif_bold", max(12, int(L * 0.42)))
    if kind == "circle":
        d.ellipse(box, fill=ink)
        d.text((cx, cy), ini, font=f, fill=paper, anchor="mm")
    elif kind == "ring":
        d.ellipse(box, outline=ink, width=max(3, L // 28))
        d.ellipse([x0 + L * 0.09, y0 + L * 0.09, x1 - L * 0.09, y1 - L * 0.09], outline=ink, width=2)
        d.text((cx, cy), ini, font=f, fill=ink, anchor="mm")
    elif kind == "box":
        d.rounded_rectangle(box, radius=L // 6, outline=ink, width=max(3, L // 26))
        d.text((cx, cy), ini, font=f, fill=ink, anchor="mm")
    else:   # leaf: two arcs meeting at the tips, a vein and a stem
        ang = math.radians(rng.uniform(25, 55))
        pts = []
        for t in np.linspace(0, math.pi, 24):
            pts.append((math.cos(t) * L * 0.45, math.sin(t) * L * 0.22))
        pts += [(-px, -py) for px, py in pts]
        rot = [(cx + px * math.cos(ang) - py * math.sin(ang), cy - px * math.sin(ang) - py * math.cos(ang))
               for px, py in pts]
        d.polygon(rot, fill=ink)
        tip = (cx + L * 0.45 * math.cos(ang), cy - L * 0.45 * math.sin(ang))
        tail = (cx - L * 0.45 * math.cos(ang), cy + L * 0.45 * math.sin(ang))
        d.line([tail, tip], fill=paper, width=max(2, L // 40))
        d.line([tail, (tail[0] - L * 0.08, tail[1] + L * 0.1)], fill=ink, width=max(3, L // 30))
    return [x0, y0, x1, y1]


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _fit_size(name, size, text, max_w, bold=False):
    while size > 10 and hand.font(name, size, bold).getlength(text) > max_w:
        size -= 1
    return size


def _fit_font(name, size, text, max_w, bold=False):
    return hand.font(name, _fit_size(name, size, text, max_w, bold), bold)


def _letterhead(page, s, spec, box, paper, rng):
    """Offset-printed letterhead: logo, name, address, contacts, GSTIN and the title strip.
    Returns the bbox of the seller block (title strip excluded)."""
    d = ImageDraw.Draw(page)
    ink, dpi = s["form_ink"], s["dpi"]
    sup = spec["supplier"]
    x0, y0, x1, y1 = (int(v) for v in box)
    h = y1 - y0
    title_h = int(h * 0.2)
    body1 = y1 - title_h
    drawn = []
    ff = s["form_font"]
    if s["head_layout"] == "corners":
        # GSTIN top-left and phone top-right in small print, like many Kerala letterheads;
        # the logo and name go below this strip
        small = hand.font(ff, int(0.12 * dpi), True)
        if sup["gstin"]:
            drawn.append(list(d.textbbox((x0, y0), f"GSTIN : {sup['gstin']}", font=small)))
            d.text((x0, y0), f"GSTIN : {sup['gstin']}", font=small, fill=ink)
        ph = f"Ph : {sup['phone']}"
        drawn.append(list(d.textbbox((x1, y0), ph, font=small, anchor="ra")))
        d.text((x1, y0), ph, font=small, fill=ink, anchor="ra")
        y0 = max(b[3] for b in drawn) + int(0.04 * dpi)
    tx0 = x0
    if s["logo"]:
        L = int(min((body1 - y0) * 0.9, (x1 - x0) * 0.15))
        lx, ly = x0 + int(0.05 * dpi), y0 + ((body1 - y0) - L) // 2
        drawn.append(_logo(d, s["logo"], (lx, ly, lx + L, ly + L), sup["name"], ink, paper, rng))
        tx0 = lx + L + int(0.05 * dpi)
    cx = (tx0 + x1) / 2 if s["logo"] else (x0 + x1) / 2
    maxw = (x1 - tx0) - 0.1 * dpi
    rows = []   # (text, font name, size, bold)

    def row(text, name, size, bold=False):
        rows.append((text, name, _fit_size(name, int(size), text, maxw, bold), bold))

    row(sup["name"], s["form_name_font"], 0.3 * dpi, True)
    if s["tagline"]:
        row(s["tagline"], "serif", 0.12 * dpi)
    addr = ", ".join(sup["address_lines"])
    if hand.font(ff, int(0.125 * dpi)).getlength(addr) <= maxw:
        row(addr, ff, 0.125 * dpi)
    else:
        for a in sup["address_lines"]:
            row(a, ff, 0.125 * dpi)
    contact = []
    if s["head_layout"] != "corners":
        contact.append(f"Ph : {sup['phone']}")
    if sup["email"]:
        contact.append(f"E-mail : {sup['email']}")
    if sup["fssai"]:
        contact.append(f"FSSAI No. {sup['fssai']}")
    if contact:
        row("   ".join(contact), ff, 0.115 * dpi)
    if sup["gstin"] and s["head_layout"] != "corners":
        row(f"GSTIN : {sup['gstin']}" + (f"     State : {sup['state']} ({sup['state_code']})" if s["state_line"] else ""),
            ff, 0.13 * dpi, True)
    total = sum(size * 1.25 for _, _, size, _ in rows)
    scale = min(1.0, (body1 - y0) / total)
    y = y0 + max(0, ((body1 - y0) - total * scale) / 2)
    for text, name, size, bold in rows:
        f = hand.font(name, max(10, int(size * scale)), bold)
        bb = d.textbbox((cx, y), text, font=f, anchor="ma")
        d.text((cx, y), text, font=f, fill=ink, anchor="ma")
        drawn.append(list(bb))
        y += size * scale * 1.25
    # title strip
    ty = body1 + title_h * 0.15
    d.line([(x0, body1), (x1, body1)], fill=ink, width=3)
    tf = hand.font(ff, int(title_h * 0.5), True)
    tw = tf.getlength(s["title"])
    tb = [(x0 + x1) / 2 - tw / 2 - 18, ty, (x0 + x1) / 2 + tw / 2 + 18, ty + title_h * 0.7]
    d.rounded_rectangle(tb, radius=8, outline=ink, width=2)
    d.text(((x0 + x1) / 2, (tb[1] + tb[3]) / 2), s["title"], font=tf, fill=ink, anchor="mm")
    return _union(drawn)


def _form_table(page, s, cols, seps, nh, band, bottom, x0, cw):
    """Pre-printed table frame: header band with labels, column rules down to `bottom`."""
    d = ImageDraw.Draw(page)
    ink = s["form_ink"]
    by0, by1 = band
    X = lambda col: x0 + (col + 0.5) * cw
    lw = 2
    d.rectangle([X(seps[0]), by0, X(seps[-1]), bottom], outline=ink, width=3)
    d.line([(X(seps[0]), by1), (X(seps[-1]), by1)], fill=ink, width=lw)
    size = int(min((by1 - by0) / (nh + 0.6), cw * 1.5))
    gtop = {}
    for i, c in enumerate(cols):
        cx0, cx1 = X(seps[i]), X(seps[i + 1])
        if c["group"]:
            gtop.setdefault(c["group"], []).append((cx0, cx1))
        head = c["head"]
        y_first = by1 - (len(head) + 0.25) * size * 1.05
        for k, h in enumerate(head):
            f = _fit_font(s["form_font"], size, h, cx1 - cx0 - 6, True)
            d.text(((cx0 + cx1) / 2, y_first + k * size * 1.05), h, font=f, fill=ink, anchor="ma")
        top = by0 + (by1 - by0) / 2 if c["group"] and i > 0 and cols[i - 1]["group"] == c["group"] else by0
        if 0 < i:
            d.line([(cx0, top), (cx0, bottom)], fill=ink, width=lw)
    for g, spans in gtop.items():
        gx0, gx1 = spans[0][0], spans[-1][1]
        ym = by0 + (by1 - by0) / 2
        d.line([(gx0, ym), (gx1, ym)], fill=ink, width=lw)
        f = _fit_font(s["form_font"], size, g, gx1 - gx0 - 6, True)
        d.text(((gx0 + gx1) / 2, (by0 + ym) / 2), g, font=f, fill=ink, anchor="mm")
    return [X(seps[0]) - 2, by0 - 2, X(seps[-1]) + 2, bottom + 2]


def _form_foot(page, s, spec, box):
    """Pre-printed signature block at the bottom of the sheet."""
    d = ImageDraw.Draw(page)
    ink, dpi = s["form_ink"], s["dpi"]
    x0, y0, x1, y1 = box
    f = hand.font(s["form_font"], int(0.115 * dpi))
    fb = hand.font(s["form_font"], int(0.12 * dpi), True)
    d.line([(x0, y0), (x1, y0)], fill=ink, width=2)
    d.text((x0 + 6, y0 + 10), "E.& O.E.", font=f, fill=ink)
    name = f"For {spec['supplier']['name']}"
    d.text((x1 - 6, y0 + 10), name, font=_fit_font(s["form_font"], fb.size, name, (x1 - x0) * 0.45, True),
           fill=ink, anchor="ra")
    d.text((x1 - 6, y1 - 8), "Authorised Signatory", font=f, fill=ink, anchor="rd")
    d.text((x0 + 6, y1 - 8), "Receiver's Signature with Seal", font=f, fill=ink, anchor="ld")
    if s["form_terms"]:
        small = hand.font(s["form_font"], int(0.085 * dpi))
        city = spec["supplier"]["address_lines"][-1].split(",")[0]
        lines = ["Goods once sold will not be taken back.", f"Subject to {city} Jurisdiction."]
        for k, t in enumerate(lines):
            d.text(((x0 + x1) / 2, y0 + 12 + k * small.size * 1.3), t, font=small, fill=ink, anchor="ma")


# ---------------------------------------------------------------- render

def render(spec, rng):
    """Render `spec` as a clean dot-matrix page; see bench.synth.templates for the contract."""
    s = _style(spec, rng)
    cols = _cols(spec, s, rng)
    cw, desc_w = _pitch(cols, s)
    W, seps = _place(cols, s, desc_w)
    face = Face(s["face"], s["face_size"]) if s["face"] != "draft" else Face(slashed_zero=s["slashed_zero"])
    lines = _compose(spec, s, cols, seps, W)
    py, lh, lh_tab, Hp = _fit(lines, s, face, spec["continued"])
    Wp = s["size"][0]
    dpi, sw = s["dpi"], s["strips"]
    size = (Wp, Hp)
    paper = PAPER_RGB[s["paper"]]
    page = _paper(s, rng, size)
    condensed = dpi / cw > 14   # 15 / 17 cpi
    printer = DotPrinter(size, face, cw / face.cell, py, rng, s["darkness"], condensed)

    # horizontal placement of the grid, roughly centred between the tractor strips
    x0 = (Wp - W * cw) / 2 + s["x_shift"]
    x0 = max(sw + 0.12 * dpi, min(Wp - sw - 0.12 * dpi - W * cw, x0))
    form = s["frame"] == "form"
    rdx, rdy = s["register"] if form else (0.0, 0.0)
    boxes = {}
    ink = []   # every printed or pre-printed thing, tagged or not: keeps notes_area blank

    def keep(tag, bb):
        if bb:
            ink.append(bb)
            if tag:
                boxes.setdefault(tag, []).append(bb)

    y = s["top"]
    header_bbox = None
    if form:
        header_bbox = _letterhead(page, s, spec, (x0, y, x0 + W * cw, y + s["form_head_h"]), paper, rng)
        y += s["form_head_h"]
    spring = max(0.0, Hp - _fixed(s) - sum(_height(ln, lh, lh_tab) for ln in lines))
    desc_h = (face.rows - face.base) * py
    grules, thead_ys, band, frame_bottom, n = [], [], None, None, 0
    for ln in lines:
        kind, h = ln["kind"], _height(ln, lh, lh_tab)
        if kind == "spring":
            y += spring
        elif kind == "band":
            band = (y, y + h)
        elif kind == "fend":
            frame_bottom = y + 0.5 * h
        elif kind == "grule":
            yr = y + h * 0.5
            grules.append(yr + rdy)
            keep("grule", printer.rule(x0 + rdx + 0.5 * cw, x0 + rdx + (W - 0.5) * cw, yr + rdy, line=n,
                                       step=cw / face.cell))
            n += 1
        else:
            base = y + h - desc_h * 0.85
            if ln["zone"] == "thead":
                thead_ys.append(y + rdy)
            for col, text, tag, flags in ln["segs"]:
                flags += "b" if s["body_bold"] and not condensed else ""
                keep(tag, printer.text(x0 + rdx + col * cw, base + rdy, text, flags, line=n))
            n += 1
        y += h

    if s["frame"] == "grid" and len(grules) >= 2:
        inner = _inner_seps(cols, seps)
        for sp in seps:
            top = thead_ys[1] if sp in inner and len(thead_ys) > 1 else grules[0]
            printer.vrule(x0 + rdx + (sp + 0.5) * cw, top, grules[-1] + 0.5)
    table_frame = None
    if form:
        bottom = frame_bottom if frame_bottom is not None else y
        nh = next(ln["nh"] for ln in lines if ln["kind"] == "band")
        table_frame = _form_table(page, s, cols, seps, nh, band, bottom, x0, cw)
        fy1 = Hp - s["bottom"]
        foot = (x0, fy1 - s["form_foot_h"], x0 + W * cw, fy1)
        _form_foot(page, s, spec, foot)
        ink += [header_bbox, table_frame, foot]

    page = printer.ink_onto(page, s["ink"], s["blur"])
    return page, _layout(spec, s, boxes, ink, header_bbox, table_frame, (x0, W, cw), size, rng)


def _notes_area(s, ink, size, rng):
    """A blank stretch of the sheet for the receiver's pen notes: the top margin, the gap the
    footer leaves above the signatures, or the empty bottom. No printed line may cross it."""
    Wp, Hp = size
    sw = s["strips"]
    nx0, nx1 = int(sw + 0.15 * s["dpi"]), int(Wp - sw - 0.15 * s["dpi"])
    gaps, y = [], 0.0
    for a, b in sorted((bb[1], bb[3]) for bb in ink if bb):
        if a > y:
            gaps.append((y, a))
        y = max(y, b)
    gaps.append((y, Hp))
    cands, best = [], None
    for g0, g1 in gaps:
        top = g0 == 0
        y0, y1 = (12 if top else g0 + 20), g1 - 15
        if best is None or y1 - y0 > best[3] - best[1]:
            best = (nx0, int(y0), nx1, int(y1))
        if y1 - y0 >= (70 if top else 120):
            cands.append((nx0, int(y0), nx1, int(y1)))
    return rng.choice(cands) if cands else best


def _layout(spec, s, boxes, ink, header_bbox, table_frame, grid, size, rng):
    """The layout dict from the tagged bboxes collected while printing."""
    Wp, Hp = size
    x0, W, cw = grid
    pad = 3

    def clamp(b, p=pad):
        if not b:
            return None
        return (int(max(0, math.floor(b[0] - p))), int(max(0, math.floor(b[1] - p))),
                int(min(Wp - 1, math.ceil(b[2] + p))), int(min(Hp - 1, math.ceil(b[3] + p))))

    get = lambda tag: _union(boxes.get(tag, []))
    rows, cells = [], []
    for i in range(len(spec["items"])):
        c = _union([get(("desc", i)), get(("qty", i)), get(("amount", i)), get(("cell", i))])
        cells.append(c)
        rows.append({"y0": clamp(c)[1], "y1": clamp(c)[3], "desc_bbox": clamp(get(("desc", i))),
                     "qty_bbox": clamp(get(("qty", i))), "amount_bbox": clamp(get(("amount", i)))})
    if table_frame:
        table = table_frame
    else:   # header rules and labels, every row, the closing rule
        table = _union([get("thead"), get("grule"), get("tbottom")] + cells)
        table = [min(table[0], x0), table[1], max(table[2], x0 + W * cw), table[3]]
    header = header_bbox or get("head")
    total = None if spec["continued"] else get("grand")
    notes = _notes_area(s, ink, size, rng)
    return {
        "table_bbox": clamp(table, 0),
        "header_bbox": clamp(header, 6),
        "invoice_number_bbox": clamp(get("inv_no")),
        "date_bbox": clamp(get("date")),
        "rows": rows,
        "total_bbox": clamp(total, 4),
        "notes_area": tuple(int(v) for v in notes),
        "paper": s["paper"],
    }
