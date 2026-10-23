"""Deterministic checks that decide auto_ok vs needs_review.

The model's output is never trusted on its own. Every bill is checked for exact
arithmetic (rounding-aware, no percentage slack), totals, GSTIN checksum, the
invoice number and date (two independent reads plus OCR must agree), serial
numbers and handwriting. Any problem puts the bill in the review queue with a
human-readable reason. See docs/DECISIONS.md for why each rule exists.
"""
import difflib
import re
from datetime import date, timedelta

from . import config

# ---------- amount in words ----------

_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_WORDS.update({w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)})
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
           "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000}
_VOCAB = list(_WORDS) + list(_SCALES)
# label words that appear on amount-in-words lines and are never numbers
_LABELS = {"rupees", "rupee", "rupess", "ruppees", "only", "and", "indian", "inr", "rs", "ps", "paise", "total",
           "amount", "in", "words", "chargeable", "value", "invoice", "net", "grand", "of", "the", "sum", "payable",
           "bill", "fourty"}


def _number_word(tok):
    """Map a token to a number word, None for label words, or '?' for a garbled number word."""
    if tok == "fourty":
        return "forty"
    if tok in _WORDS or tok in _SCALES:
        return tok
    if tok in _LABELS:
        return None
    close = difflib.get_close_matches(tok, _VOCAB, n=1, cutoff=0.6)
    if close and len(tok) >= 4 and difflib.SequenceMatcher(None, tok, close[0]).ratio() >= 0.8:
        return close[0]   # eightteen -> eighteen, ninty -> ninety
    return "?" if close else None


def words_to_number(text):
    """'Twenty Six Thousand Seven Hundred Sixty Six Only' -> 26766 (Indian lakh/crore aware; paise ignored).

    Returns None when there is nothing numeric, or when a number word is garbled ('Nine Hundred Twe'):
    a partly unreadable line must not contradict a total."""
    if not text:
        return None
    text = text.lower()
    if "paise" in text:   # drop "... and twenty paise": cut at the last 'rupees'/'and' before it
        head = text[:text.index("paise")]
        text = head[:max(head.rfind(" and "), head.rfind("rupees"), 0)]
    total = cur = 0
    seen = False
    for tok in re.findall(r"[a-z]+", text.replace("-", " ")):
        w = _number_word(tok)
        if w is None:
            continue
        if w == "?":
            return None
        if w in _WORDS:
            cur += _WORDS[w]
            seen = True
        elif w == "hundred":
            cur = max(cur, 1) * 100
        else:
            total += max(cur, 1) * _SCALES[w]
            cur = 0
            seen = True
    return total + cur if seen else None


# ---------- arithmetic ----------

HALF_RATES = {1.5: 3, 2.5: 5, 6: 12, 9: 18, 14: 28}   # CGST/SGST half-rates -> full GST rate


def gst_rate(t):
    """A row's printed tax% as the full GST rate (a printed CGST half-rate 2.5 means 5%)."""
    if t is None:
        return None
    return HALF_RATES.get(t, t) if t not in config.GST_RATES else t


def row_ok(q, r, a, t=None):
    """qty x rate (x GST factor) == amount, allowing only printing-level rounding.

    Tolerance = rate rounded to 2 dp (0.005 per unit) + qty rounded to 3 dp + 1 paisa, scaled by the GST
    factor. A whole-rupee amount may also be rounded to the nearest rupee (cash bills). The GST factor
    may only be 1, the row's own rate, or all slabs when the row prints no rate."""
    if None in (q, r, a) or q <= 0 or r <= 0 or a <= 0:
        return False
    t = gst_rate(t)
    rates = {0, t} if t in config.GST_RATES else set(config.GST_RATES)
    for tt in rates:
        f = 1 + tt / 100
        tol = (0.011 + 0.005 * q + 0.0005 * r) * f
        diff = abs(q * r * f - a)
        if diff <= tol or (a == int(a) and diff <= 0.5 + tol):
            return True
    return False


def sum_check(items, totals, words=None):
    """Do the rows add up to the bill? Returns (ok, message), or (None, None) when there is no total.

    Exact path: rows (+ printed tax, or + tax implied by each row's GST rate) (+ printed round off)
    == grand total within 5 paise + 0.5 paise per row. Rounding path, for bills that round to the rupee
    without printing it: a whole-rupee total within Rs 1 of the rows - and then, if a subtotal is printed,
    the rows must match it exactly, so a paise-level misread can't hide inside the rounding.
    Misread tax lines: rows equal to the printed subtotal to the paisa, with the total confirmed by the
    amount in words (`words`), also pass - two independent printed numbers agree with the rows."""
    T = totals.get("grand_total")
    if T is None or not items:
        return None, None
    if any(it["amount"] is None for it in items):
        return False, "some rows have no amount"
    n = len(items)
    S = sum(it["amount"] for it in items)
    tax_fields = [totals.get(k) for k in ("cgst", "sgst", "igst", "cess")]
    tax = sum(x or 0 for x in tax_fields) if any(x is not None for x in tax_fields) else None
    rates = [gst_rate(it.get("tax_percent")) or 0 for it in items]
    implied = sum(it["amount"] * t / 100 for it, t in zip(items, rates))              # pre-tax rows
    implied_incl = sum(it["amount"] * t / (100 + t) for it, t in zip(items, rates))   # tax-inclusive rows
    candidates = {S, S + implied} | ({S + tax} if tax is not None else set())
    ro = totals.get("round_off") or 0
    exact = 0.05 + 0.005 * n
    if any(abs(x + ro - T) <= exact or abs(x - ro - T) <= exact or abs(x - T) <= exact for x in candidates):
        return True, None   # (x - ro: the round off was read with the wrong sign)
    sub = totals.get("subtotal")
    in_words = words_to_number(words)
    if sub is not None and abs(S - sub) <= 0.02 + 0.005 * n and in_words is not None and abs(in_words - int(T)) <= 1 \
            and sub < T <= sub * 1.3:
        return True, None
    if totals.get("round_off") is None and T == int(T) and any(abs(x - T) <= 1.0 + 0.01 * n for x in candidates):
        tight = 0.02 + 0.005 * n
        if sub is None or abs(S - sub) <= tight or abs(S - (sub + implied_incl)) <= tight or (
                tax is not None and abs(S - (sub + tax)) <= tight):
            return True, None
        return False, f"line items sum to {S:.2f}, but the subtotal printed is {sub:g}"
    return False, f"line items sum to {S:.2f}, grand total is {T:g}"


def serial_problem(items):
    """Printed row serial numbers must run 1, 2, 3... without gaps or repeats (catches skipped,
    duplicated and invented rows that keep the arithmetic consistent)."""
    sls = [it.get("sl") for it in items]
    if len(items) < 2 or any(s is None for s in sls):
        return None
    for prev, cur in zip(sls, sls[1:]):
        if cur != prev + 1:
            return f"row numbers jump from {prev} to {cur} - a row may be missing, repeated or invented"
    return None


# ---------- invoice number ----------

def norm_id(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


_FOLD = str.maketrans("OIlLSBZ", "0111582")


def fold_id(s):
    """norm_id with look-alike characters folded, to compare two reads of the same printed number."""
    return norm_id(s).translate(_FOLD)


RECEIVER_REF = re.compile(r"^B\W*[I1L]\W*L*\W*[-:/ ]?\W*\d{2,4}$", re.I)
BOOK_SERIES = re.compile(r"^(\d{2}\s*-\s*\d{2}\s*[A-Z])\s*(\d+)$", re.I)


def split_series(number):
    """'26-27 C 5207' (pre-printed bill-book series + serial) -> ('5207', '26-27 C'); else (number, None)."""
    m = BOOK_SERIES.match((number or "").strip())
    return (m.group(2), m.group(1)) if m else (number, None)


def is_receiver_ref(number, notes=()):
    """The receiver's pen note ('Bill-641', 'BIL 604') read as the invoice number."""
    if not number:
        return False
    if RECEIVER_REF.match(number.strip()):
        return True
    digits = re.sub(r"\D", "", number)
    return bool(digits) and any(re.sub(r"\D", "", n) == digits for n in notes if re.search(r"(?i)b\W*[i1l]", n or ""))


def in_ocr_tokens(number, ocr_text):
    """The number appears in the OCR text as a whole token (or 2-3 adjacent tokens joined, for numbers
    OCR splits at slashes or spaces) - never as part of a longer number like a phone number."""
    target = norm_id(number)
    if not target:
        return False
    toks = [norm_id(t) for t in re.split(r"\s+", ocr_text or "")]
    toks = [t for t in toks if t]
    for i in range(len(toks)):
        joined = ""
        for t in toks[i:i + 3]:
            joined += t
            if joined == target:
                return True
            if len(joined) >= len(target):
                break
    return False


def edit_distance(a, b):
    """Levenshtein distance between two strings."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def decide_invoice_number(header_read, second_read, ocr_text, notes=()):
    """Two model reads (full page and zoomed header) plus OCR must agree.

    Returns (number, series, issue). Agreement of both reads, or OCR printing exactly one of them,
    confirms the number; otherwise the bill goes to review with both readings shown."""
    a, series = split_series(header_read)
    b, series_b = split_series(second_read)
    series = series or series_b
    in_ocr = lambda x: in_ocr_tokens(x, ocr_text)
    if not a and not b:
        return None, series, "invoice number missing"
    for x in (a, b):
        if x and is_receiver_ref(x, notes):
            other = b if x == a else a
            if other and not is_receiver_ref(other, notes):
                a = b = other
            else:
                return x, series, f"invoice number '{x}' looks like the receiver's pen note, not the printed number"
    if a and b:
        fa, fb = fold_id(a), fold_id(b)
        if fa == fb:
            return (b if in_ocr(b) and not in_ocr(a) else a), series, None
        unclear = f"invoice number unclear: read as '{a}' and '{b}'"
        if fa in fb or fb in fa:
            # one read lost characters (a dropped digit, or the half of a number that wraps onto a second
            # line): OCR may confirm the longer one, but never the shorter
            longer = a if len(fa) > len(fb) else b
            return (longer, series, None) if in_ocr(longer) else (longer, series, unclear)
        if edit_distance(fa, fb) <= 2 and in_ocr(a) != in_ocr(b):
            return (a if in_ocr(a) else b), series, None   # a digit misread: OCR shows which
        # reads that differ by more than a slip (e.g. a handwritten replacement vs the struck printed
        # number, which only OCR can see) are for a person to decide. The zoomed read is shown: on the
        # held-out benchmark it was the right one in 14 of 18 such cases (the full-page read tends to
        # grab a nearby field - "B2B", a phone number, the receiver's "BIL-6xx")
        return b, series, unclear
    x = a or b
    if in_ocr(x):
        return x, series, None
    return x, series, f"invoice number '{x}' not confirmed (read once, not found by OCR)"


# ---------- dates ----------

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], 1)}
_SEP = r"\s*[/\-.|\\]\s*"
_D_NUM = re.compile(rf"(?<!\d)(\d{{1,2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{4}}|\d{{2}})(?!\d)")
_D_MON = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*([A-Za-z]{3,9})[\s\-/.,']*(\d{4}|\d{2})?(?!\d)")
_D_ISO = re.compile(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
_D_NOYEAR = re.compile(rf"^\s*(\d{{1,2}}){_SEP}(\d{{1,2}})\s*$")


def _mk(y, m, d):
    try:
        y = int(y)
        y = 2000 + y if y < 100 else y
        return date(y, int(m), int(d))
    except (ValueError, TypeError):
        return None


def parse_date_dayfirst(text, today=None):
    """Parse a date as printed on an Indian bill (day first): '29/08/26', '29-Aug-2026', '29.08.2026',
    '31|8' (no year: this year, or last year if that would be in the future). ISO 'YYYY-MM-DD' also works."""
    if not text:
        return None
    today = today or date.today()
    s = str(text).strip()
    m = _D_ISO.search(s)
    if m:
        return _mk(*m.groups())
    m = _D_NUM.search(s)
    if m:
        return _mk(m.group(3), m.group(2), m.group(1))
    m = _D_MON.search(s)
    if m and m.group(2)[:3].lower() in MONTHS:
        return _mk(m.group(3) or today.year, MONTHS[m.group(2)[:3].lower()], m.group(1))
    m = _D_NOYEAR.match(s)
    if m:
        d = _mk(today.year, m.group(2), m.group(1))
        return d.replace(year=d.year - 1) if d and d > today + timedelta(days=1) else d
    return None


def dates_in_text(text, today=None):
    """Every plausible date in OCR text (years from last year to next year)."""
    today = today or date.today()
    found = set()
    for rx, order in ((_D_NUM, (3, 2, 1)), (_D_ISO, (1, 2, 3))):
        for m in rx.finditer(text or ""):
            d = _mk(*(m.group(i) for i in order))
            if d:
                found.add(d)
    for m in _D_MON.finditer(text or ""):
        if m.group(3) and m.group(2)[:3].lower() in MONTHS:
            d = _mk(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1))
            if d:
                found.add(d)
    return {d for d in found if today.year - 1 <= d.year <= today.year + 1}


def fy_range(invoice_number):
    """'26-27/1064' -> the Indian financial year 2026-04-01..2027-03-31, else None."""
    for a, b in re.findall(r"(?<!\d)(\d{2})\s*-\s*(\d{2})(?!\d)", invoice_number or ""):
        if int(b) == (int(a) + 1) % 100:
            y = 2000 + int(a)
            return date(y, 4, 1), date(y + 1, 3, 31)
    return None


def decide_date(header_iso, header_printed, second_printed, ocr_text, invoice_number=None, today=None):
    """Returns (iso date or None, issue). The printed text is parsed day-first in code (the model's own
    ISO conversion swaps day/month and invents years); two reads must agree, OCR breaks ties."""
    today = today or date.today()
    a = parse_date_dayfirst(header_printed, today) or parse_date_dayfirst(header_iso, today)
    b = parse_date_dayfirst(second_printed, today)
    plausible = lambda x: today - timedelta(days=365) <= x <= today + timedelta(days=1)
    ocr_dates = {x for x in dates_in_text(ocr_text, today) if plausible(x)}   # OCR misreads make odd dates
    if a and b and a != b:
        if (a in ocr_dates) != (b in ocr_dates):
            a = a if a in ocr_dates else b
        elif plausible(a) != plausible(b):
            a = a if plausible(a) else b   # e.g. 30/08/2028 vs 30/08/2026: a year misread
        else:
            return a.isoformat(), f"invoice date unclear: read as {a:%d/%m/%Y} and {b:%d/%m/%Y}"
    d = a or b
    if not d:
        return None, f"invoice date unreadable: {header_printed or header_iso}"
    if not b and not (a in ocr_dates):
        return d.isoformat(), f"invoice date {d:%d/%m/%Y} not confirmed (read once, not found by OCR)"
    if ocr_dates and d not in ocr_dates and not (a and b and a == b):
        return d.isoformat(), f"invoice date {d:%d/%m/%Y} not found on the page (OCR saw " + \
            ", ".join(f"{x:%d/%m/%Y}" for x in sorted(ocr_dates)[:3]) + ")"
    if d > today + timedelta(days=1) or d < today - timedelta(days=365):
        return d.isoformat(), f"implausible invoice date {d:%d/%m/%Y}"
    fy = fy_range(invoice_number)
    if fy and not fy[0] <= d <= fy[1]:
        return d.isoformat(), f"invoice date {d:%d/%m/%Y} is outside financial year of invoice no. {invoice_number}"
    return d.isoformat(), None


# ---------- the whole bill ----------

def validate(d, checks=()):
    """Return a list of human-readable issues for an extracted bill (empty = auto_ok).

    `checks` are header consensus issues (invoice number, date, GSTIN confirmation) decided in the
    pipeline, where both model reads and the OCR text are available."""
    issues = list(checks)
    items = d["line_items"]
    if not items:
        issues.append("no line items extracted")
    for i, it in enumerate(items, 1):
        q, r, a = it["quantity"], it["rate"], it["amount"]
        name = it["description"][:30]
        if it.get("unreadable"):
            issues.append(f"line {i} ({name}): a digit was unreadable")
        if q is None or r is None or a is None:
            issues.append(f"line {i} ({name}): missing qty/rate/amount")
        elif not row_ok(q, r, a, it.get("tax_percent")):
            hint = f"; if amount is right, rate = {a / q:.2f}" if q else ""
            issues.append(f"line {i} ({name}): {q:g} x {r:g} = {q * r:.2f} but amount is {a:g}{hint}")
    sp = serial_problem(items)
    if sp and not d["is_handwritten"]:   # bill books legitimately skip unfilled pre-printed rows
        issues.append(sp)
    t = d["totals"]
    total = t.get("grand_total")
    ok, msg = sum_check(items, t, d.get("amount_in_words"))
    if d["continued_on_next_page"] or (total is None and items):
        issues.append("invoice continues on another page - attach remaining pages")
    elif total is None:
        issues.append("grand total missing")
    elif ok is False:
        issues.append(msg)
        # the words only arbitrate when the arithmetic cannot confirm the total
        in_words = words_to_number(d.get("amount_in_words"))
        if in_words and abs(in_words - int(total)) > 1:
            issues.append(f"total {total:g} disagrees with amount in words ({in_words:g}) - check the total")
    if d.get("header_corrected"):
        issues.append("invoice number/date/total corrected by hand on the bill - confirm")
    g = d["supplier"]["gstin"]
    if not g:
        issues.append("supplier GSTIN not found")
    elif not d["supplier"]["gstin_verified"] and not any("GSTIN" in i for i in issues):
        issues.append(f"supplier GSTIN '{g}' not confirmed - likely misread")
    if not d["invoice_number"] and not any(i.startswith("invoice number") for i in issues):
        issues.append("invoice number missing")
    if not d["invoice_date"] and not any(i.startswith("invoice date") for i in issues):
        issues.append("invoice date missing")
    if d["is_handwritten"]:
        issues.append("handwritten bill - confirm values")
    return issues
