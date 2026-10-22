"""Deterministic checks that decide auto_ok vs needs_review.

The model's output is never trusted on its own: every bill is checked for
arithmetic, totals, GSTIN checksum, date sanity and handwriting. Any problem
puts the bill in the review queue with a human-readable reason.
"""
import re
from datetime import date

from . import config

_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_WORDS.update({w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)})
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
           "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000}


def words_to_number(text):
    """'Twenty Six Thousand Seven Hundred Sixty Six Only' -> 26766 (Indian lakh/crore aware; paise ignored)."""
    if not text:
        return None
    text = text.lower()
    if "paise" in text:   # drop "... and twenty paise": cut at the last 'rupees'/'and' before it
        head = text[:text.index("paise")]
        text = head[:max(head.rfind(" and "), head.rfind("rupees"), 0)]
    total = cur = 0
    seen = False
    for w in re.findall(r"[a-z]+", text.replace("-", " ")):
        if w in _WORDS:
            cur += _WORDS[w]
            seen = True
        elif w == "hundred":
            cur *= 100
        elif w in _SCALES:
            total += max(cur, 1) * _SCALES[w]
            cur = 0
            seen = True
    return total + cur if seen else None


def close(a, b, tol_abs=1.0, tol_rel=0.01):
    """Equal within max(1 rupee, 1%) - absorbs rounding on printed bills."""
    return a is not None and b is not None and abs(a - b) <= max(tol_abs, tol_rel * abs(b))


def validate(d):
    """Return a list of human-readable issues for an extracted bill (empty = auto_ok)."""
    issues = []
    items = d["line_items"]
    if not items:
        issues.append("no line items extracted")
    for i, it in enumerate(items, 1):
        q, r, a = it["quantity"], it["rate"], it["amount"]
        name = it["description"][:30]
        if q is None or r is None or a is None:
            issues.append(f"line {i} ({name}): missing qty/rate/amount")
            continue
        # line amounts may be pre-tax or tax-inclusive at any standard GST rate
        rates = {it.get("tax_percent") or 0, *config.GST_RATES}
        if not any(close(q * r * (1 + t / 100), a) for t in rates):
            hint = f"; if amount is right, rate = {a / q:.2f}" if q else ""
            issues.append(f"line {i} ({name}): {q:g} x {r:g} = {q * r:.2f} but amount is {a:g}{hint}")
    line_sum = sum(it["amount"] or 0 for it in items)
    t = d["totals"]
    tax = sum(t.get(k) or 0 for k in ("cgst", "sgst", "igst", "cess"))
    sub, total, ro = t.get("subtotal"), t.get("grand_total"), t.get("round_off") or 0
    if d["continued_on_next_page"] or (total is None and items):
        issues.append("invoice continues on another page - attach remaining pages")
    elif total is None:
        issues.append("grand total missing")
    elif not any(close(line_sum + x, total) for x in (0, tax, tax + ro, ro)):
        issues.append(f"line items sum to {line_sum:.2f}, grand total is {total:g}")
    in_words = words_to_number(d.get("amount_in_words"))
    if in_words and total is not None and not close(in_words, total, tol_abs=1, tol_rel=0):
        issues.append(f"total {total:g} disagrees with amount in words ({in_words:g}) - check the total")
    if d.get("header_corrected"):
        issues.append("invoice number/date/total corrected by hand on the bill - confirm")
    if sub is not None and total is not None and tax and not close(sub + tax + ro, total):
        issues.append(f"subtotal {sub:g} + tax {tax:.2f} != total {total:g}")
    g = d["supplier"]["gstin"]
    if not g:
        issues.append("supplier GSTIN not found")
    elif not d["supplier"]["gstin_verified"]:
        issues.append(f"supplier GSTIN '{g}' fails checksum - likely misread")
    if not d["invoice_number"]:
        issues.append("invoice number missing")
    try:
        dt = date.fromisoformat(d["invoice_date"] or "")
        if not (2020 <= dt.year <= date.today().year + 1):
            issues.append(f"implausible date {dt}")
    except ValueError:
        issues.append(f"invoice date unreadable: {d['invoice_date']}")
    if d["is_handwritten"]:
        issues.append("handwritten bill - confirm values")
    return issues
