"""Prompts, schemas and parsing for the vision-model passes.

The bill is read in separate focused requests rather than one big one:
  - header + totals as a small JSON schema
  - line items as compact pipe-separated rows (about 4x fewer tokens than JSON,
    and a model stuck repeating a row is easy to detect and cut off)
  - a standalone yes/no check for a struck-through invoice number
See docs/DECISIONS.md for why each split exists.
"""
import json
import re
from datetime import date

from . import config
from .validate import close

_num = {"type": ["number", "null"]}
_txt = {"type": ["string", "null"]}

HEADER_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": _txt, "supplier_gstin": _txt, "supplier_address": _txt, "supplier_phone": _txt,
        "buyer_name": _txt, "invoice_number": _txt,
        "invoice_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "items_handwritten": {"type": "boolean", "description": "true only if the product rows are written by hand in pen"},
        "subtotal": _num, "cgst": _num, "sgst": _num, "igst": _num, "cess": _num, "round_off": _num,
        "grand_total": _num,
        "amount_in_words": {"type": ["string", "null"], "description": "the total written in words, copied verbatim"},
        "header_corrected": {"type": "boolean", "description": "true if the invoice number, date or total was crossed out / overwritten by hand"},
        "continued_on_next_page": {"type": "boolean"},
        # maxItems: without it the model sometimes repeats one note until the token limit
        "handwritten_notes": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "grand_total",
                 "continued_on_next_page", "items_handwritten"],
}


def header_prompt():
    return f"""This is a photographed Indian purchase bill (GST tax invoice, cash bill or handwritten bill).
Extract the header and totals into the JSON schema:
- supplier = the business that ISSUED the bill (letterhead at the top). The buyer is our company {config.COMPANY_NAME}
  (GSTIN {config.COMPANY_GSTIN}, also written {config.COMPANY_ALIASES}); supplier_gstin is never {config.COMPANY_GSTIN}.
- invoice_date as YYYY-MM-DD. Dates are day-first (29/08/26 = 2026-08-29). If only day/month is written, the year is {date.today().year}.
- Amounts as plain numbers, no commas or currency symbols. grand_total = final payable of THIS invoice, not previous/closing balance.
- continued_on_next_page = true if the page says "continued"/"contd" or the item table has no totals on this page.
- If a printed invoice number, date or total is crossed out and a new value is handwritten, use the handwritten value and set header_corrected = true.
- amount_in_words: copy the "amount in words" line exactly as written, if present.
- Ignore rubber stamps (GOODS RECEIVED, store name, received/checked by).
- Pen marks added by the receiver (bill refs like "Bill-641", remarks like "quality issue return", "not received") go in handwritten_notes, each distinct remark once.
- items_handwritten = true only when the product rows themselves are pen-written (a handwritten cash bill), not for pen marks on a printed bill.
- null for anything not present. Do not guess."""


def read_header(img, llm):
    try:
        return json.loads(llm.chat(header_prompt(), img, schema=HEADER_SCHEMA, max_tokens=1500, step="header"))
    except json.JSONDecodeError:
        return {}


ITEMS_PROMPT = """List EVERY product row of the item table in this bill, top to bottom, one row per line, in this exact format:
description | hsn | qty | unit | rate | tax% | amount
Rules: numbers without commas or currency symbols; leave a field empty if the column does not exist;
rate = the unit price the buyer pays (Rate/Price column), NOT the MRP column;
amount = the row's line total as printed; multi-line descriptions joined into one line;
read through rubber stamps and pen marks; if a value is crossed out and rewritten by hand, use the rewritten value;
skip pre-printed product rows that have no quantity and no amount filled in;
do not include totals, tax rows or headers.
After the last product row write END."""


def parse_num(s):
    s = re.sub(r"[^\d.\-]", "", s or "")
    try:
        return float(s) if s not in ("", ".", "-") else None
    except ValueError:
        return None


def parse_items(text):
    """Parse 'description | hsn | qty | unit | rate | tax% | amount' rows into dicts."""
    items, seen = [], {}
    for line in text.splitlines():
        line = line.strip().strip("`")
        if line.upper().startswith("END"):
            break
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7 or not parts[0] or parts[0].lower().startswith("description"):
            continue
        desc = re.sub(r"^\d+[.)]?\s+", "", parts[0])   # drop leading serial numbers
        key = "|".join(parts)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:   # model is looping on the same row
            break
        if parse_num(parts[2]) is None and parse_num(parts[6]) is None:
            continue   # blank pre-printed template row
        items.append({"description": desc, "hsn": parts[1] or None, "quantity": parse_num(parts[2]),
                      "unit": parts[3] or None, "rate": parse_num(parts[4]),
                      "tax_percent": parse_num(parts[5]), "amount": parse_num(parts[6])})
    return items


def item_problems(items, header):
    """Arithmetic problems in the item table, phrased as feedback for the model."""
    probs = []
    for i, it in enumerate(items, 1):
        q, r, a = it["quantity"], it["rate"], it["amount"]
        if None in (q, r, a):
            probs.append(f"row {i} '{it['description']}' is missing qty, rate or amount")
        elif not any(close(q * r * (1 + t / 100), a) for t in {it.get("tax_percent") or 0, *config.GST_RATES}):
            probs.append(f"row {i} '{it['description']}': {q:g} x {r:g} does not equal amount {a:g}")
    total = header.get("grand_total")
    tax = sum(header.get(k) or 0 for k in ("cgst", "sgst", "igst", "cess"))
    s = sum(it["amount"] or 0 for it in items)
    if total and not header.get("continued_on_next_page") and \
            not any(close(s + x, total) for x in (0, tax, tax + (header.get("round_off") or 0))):
        probs.append(f"the {len(items)} rows sum to {s:g} but the bill total is {total:g} - "
                     "a row may be missing, duplicated or misread")
    return probs


def read_items(img, llm, header):
    """Read the item table, then one self-correction round: if the arithmetic doesn't
    work out, show the model its own errors and ask for a re-read; keep whichever
    version has fewer problems. Returns (items, rechecked)."""
    items = parse_items(llm.chat(ITEMS_PROMPT, img, max_tokens=4096, step="items"))
    probs = item_problems(items, header)
    if not probs:
        return items, False
    feedback = ("\n\nA previous reading of this bill had these problems:\n- " + "\n- ".join(probs[:10]) +
                "\nLook at the image again carefully, especially those rows, digits hidden under stamps, "
                "and rows that look alike. Output the full corrected table.")
    again = parse_items(llm.chat(ITEMS_PROMPT + feedback, img, max_tokens=4096, step="items_recheck"))
    if again and len(item_problems(again, header)) < len(probs):
        return again, True
    return items, False


STRIKE_PROMPT = """Look very closely at the printed INVOICE / BILL NUMBER field of this bill.
Has that printed number itself been struck through with a pen line, with a replacement number handwritten next to or below it?
Ignore the receiver's reference notes like "Bill-641" / "BIL 632" scribbled elsewhere on the page - those are not corrections.
Reply as JSON: {"struck_through": true/false, "printed_number": "...", "replacement_number": "..." or null}"""
# Only struck_through is used. Asking for both numbers makes the model actually
# look at the field; with a bare yes/no it answered "no" every time.
STRIKE_SCHEMA = {"type": "object", "properties": {
    "struck_through": {"type": "boolean"}, "printed_number": {"type": ["string", "null"]},
    "replacement_number": {"type": ["string", "null"]}},
    "required": ["struck_through", "printed_number", "replacement_number"]}


def invoice_no_struck(img, llm):
    """Asked inside the big header schema the model misses strike-throughs; asked on its own it catches them."""
    try:
        out = llm.chat(STRIKE_PROMPT, img, schema=STRIKE_SCHEMA, max_tokens=200, step="strike_check")
        return bool(json.loads(out).get("struck_through"))
    except (json.JSONDecodeError, AttributeError):
        return False
