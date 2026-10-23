"""Prompts, schemas and parsing for the vision-model passes.

The bill is read in separate focused requests rather than one big one:
  - header + totals as a small JSON schema (full page)
  - line items as compact pipe-separated rows (about 4x fewer tokens than JSON,
    and a model stuck repeating a row is easy to detect and cut off)
  - a header check on a zoomed crop of the top of the page: a second, independent
    read of the invoice number, date and GSTINs, plus the strike-through question
See docs/DECISIONS.md for why each split exists.
"""
import difflib
import json
import re
from datetime import date

from PIL import Image

from . import config
from .validate import row_ok, sum_check

_num = {"type": ["number", "null"]}
_txt = {"type": ["string", "null"]}

HEADER_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": _txt, "supplier_gstin": _txt, "supplier_address": _txt, "supplier_phone": _txt,
        "buyer_name": _txt, "invoice_number": _txt,
        "invoice_date_as_printed": {"type": ["string", "null"], "description": "the invoice date copied exactly as printed"},
        "invoice_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "receiver_bill_ref": {"type": ["string", "null"], "description": "the receiver's handwritten 'Bill-6xx' note, if any"},
        "items_handwritten": {"type": "boolean",
                              "description": "true if the quantities, rates or amounts are written in pen"},
        "subtotal": _num, "cgst": _num, "sgst": _num, "igst": _num, "cess": _num, "round_off": _num,
        "grand_total": _num,
        "amount_in_words": {"type": ["string", "null"], "description": "the total written in words, copied verbatim"},
        "header_corrected": {"type": "boolean", "description": "true if the invoice number, date or total was crossed out / overwritten by hand"},
        "continued_on_next_page": {"type": "boolean"},
        # maxItems: without it the model sometimes repeats one note until the token limit
        "handwritten_notes": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["supplier_name", "supplier_gstin", "invoice_number", "invoice_date_as_printed", "invoice_date",
                 "receiver_bill_ref", "subtotal", "cgst", "sgst", "igst", "round_off", "grand_total",
                 "continued_on_next_page", "items_handwritten"],
}


def header_prompt():
    return f"""This is a photographed Indian purchase bill (GST tax invoice, cash bill or handwritten bill).
Extract the header and totals into the JSON schema:
- supplier = the business that ISSUED the bill (its letterhead). Ignore any other paper visible behind or beside the bill.
  The buyer is our company {config.COMPANY_NAME} (GSTIN {config.COMPANY_GSTIN}, also written {config.COMPANY_ALIASES});
  supplier_gstin is never {config.COMPANY_GSTIN}.
- invoice_number = the number PRINTED (or pre-printed in red on bill books) next to "Invoice No." / "Bill No." / "No.",
  copied exactly, keeping letters, slashes and dashes. It is never the receiver's handwritten reference note at the top
  (like "Bill-6xx" / "BIL 6xx" in pen) - put that note in receiver_bill_ref.
- invoice_date_as_printed: the invoice date copied exactly as written. invoice_date: the same date as YYYY-MM-DD.
  Dates are day-first (29/08/26 = 2026-08-29). If only day/month is written, the year is {date.today().year}.
- Amounts as plain numbers, no commas or currency symbols.
  subtotal = total before GST (Taxable Value / Sub Total / Total Value / Gross Amount);
  cgst, sgst, igst = the SUM of all lines of that tax (e.g. CGST@2.5% + CGST@9%); cess; round_off with its sign;
  grand_total = the final payable amount of THIS invoice after round off - not a previous, current or closing balance.
- continued_on_next_page = true if the page says "continued"/"contd" or the item table has no totals on this page
  (then grand_total is null).
- If a printed invoice number, date or total is crossed out and a new value is handwritten, use the handwritten value
  and set header_corrected = true.
- amount_in_words: copy the "amount in words" line exactly as written, if present.
- Ignore the GOODS RECEIVED rubber stamp and everything written inside it (store, name, date, checked by, signature).
- handwritten_notes: other pen remarks the receiver added, each distinct remark once.
- items_handwritten = true if the quantities, rates or amounts in the item table are written in pen, even when the
  product names are pre-printed; ticks, notes and stamps do not count.
- null for anything not present. Do not guess."""


def read_header(img, llm):
    try:
        return json.loads(llm.chat(header_prompt(), img, schema=HEADER_SCHEMA, max_tokens=1500, step="header"))
    except json.JSONDecodeError:
        return {}


ITEMS_PROMPT = """Read the item table of this bill. Output exactly these lines and nothing else:
INK: pen   or   INK: printed     (how the quantity / rate / amount figures in the table are written)
then EVERY product row, top to bottom, one per line, in this exact format:
sl | description | hsn | qty | unit | rate | tax% | amount
and finally a line: END
Rules:
- Always output the 8 fields in exactly this order, whatever the bill's own column order is.
- Copy every number exactly as printed. Never calculate, round or correct a value. Write ? for a digit you cannot read.
- sl = the row's printed serial number (empty if none). Numbers without commas or currency symbols.
  Leave a field empty if the bill has no such column.
- qty = the billed quantity number only (the unit goes in unit).
- rate = the unit price the buyer pays (Rate / Price column), NOT the MRP. If both a rate and a GST-inclusive rate are
  printed, use the rate before GST.
- tax% = the row's total GST rate (CGST% + SGST%, or IGST%); empty if the bill shows no GST per row.
- amount = the row's line total as printed. If the bill has separate Rs and Ps columns, join them (1,006 | 20 -> 1006.20).
- Multi-line descriptions joined into one line. Read through rubber stamps and pen marks. If a value is crossed out and
  rewritten by hand, use the rewritten value.
- Skip pre-printed product rows that have no quantity and no amount filled in. No totals, tax lines or headings.
- No markdown, bullets, numbering or commentary."""


def parse_num(s):
    """'1,609.20' -> 1609.2; '4 Boxes' -> 4.0; '1892/-' -> 1892.0 (Indian 'rupees only' mark);
    '' / '-' -> None. A '?' (unreadable digit) -> None."""
    if s is None or "?" in s:
        return None
    s = re.sub(r"^\s*(rs\.?|inr|₹)\s*", "", s.strip(), flags=re.I)        # currency prefix (its dot is no decimal)
    s = re.sub(r"(?<=\d)\s*(/-|/=|=|-+)\s*$", "", s)
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s) if s not in ("", ".", "-") else None
    except ValueError:
        return None


def decimal_qty(qty, rate, amount, tax=None):
    """Parse a quantity, reading '9,000' as 9.000 when only that reading makes qty x rate = amount
    (bills print kg quantities with 3 decimals, and readers turn the point into a thousands comma)."""
    q = parse_num(qty)
    if q is not None and re.fullmatch(r"\s*\d{1,3},\d{3}\s*", qty or ""):
        r, a, t = parse_num(rate), parse_num(amount), parse_num(tax)
        alt = float(qty.strip().replace(",", "."))
        if not row_ok(q, r, a, t) and row_ok(alt, r, a, t):
            return alt
    return q


_SEPARATOR = re.compile(r"^[\s|:\-=+]+$")


def final_block(text):
    """The answer part of a reply. Despite reasoning being switched off, the model sometimes thinks aloud
    first and writes draft tables before its answer; parsing those too would duplicate rows. The answer
    starts at the last 'INK:' line, or else at the last unbroken run of table rows."""
    lines = (text or "").splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip().strip("*`").upper().startswith("INK:")]
    if starts:
        return "\n".join(lines[starts[-1]:])
    runs, cur = [], []
    for l in lines:
        if "|" in l:
            cur.append(l)
        elif cur and l.strip():
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return "\n".join(runs[-1]) if runs else ""


def drop_repeated_block(items):
    """A model stuck in a loop sometimes outputs the whole table (or its tail) twice: keep one copy."""
    keys = [(it["description"].lower(), it["quantity"], it["rate"], it["amount"]) for it in items]
    n = len(keys)
    for p in range(1, n // 2 + 1):
        if n - p >= 2 and all(keys[i] == keys[i + p] for i in range(n - p)):
            return items[:p], True
    return items, False


def parse_items(text):
    """Parse the items reply. Returns (items, info).

    Rows are 'sl | description | hsn | qty | unit | rate | tax% | amount' (8 fields) or, if the model
    leaves out the serial, 7 fields. Tolerates markdown pipes, separator rows and 'Row N:' prefixes."""
    items, info, seen = [], {"ink": None, "columns": None, "malformed": 0, "looped": False}, {}
    for line in final_block(text).splitlines():
        line = line.strip().strip("`").strip()
        up = line.upper()
        if up.startswith("END"):
            break
        if up.startswith("INK:"):
            info["ink"] = "pen" if "PEN" in up else "printed" if "PRINT" in up else None
            continue
        if up.startswith("COLUMNS:"):
            info["columns"] = line.split(":", 1)[1].strip()
            continue
        if not line or _SEPARATOR.match(line) or "|" not in line:
            continue
        line = re.sub(r"^(row\s*\d+\s*:)", "", line, flags=re.I).strip()
        if line.startswith("|"):   # markdown-style row: | a | b | - drop only the outer pipes
            line = line[1:-1] if line.endswith("|") else line[1:]
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 7:
            parts = [""] + parts
        if len(parts) != 8:
            info["malformed"] += 1
            continue
        sl, desc, hsn, qty, unit, rate, tax, amount = parts
        if desc.lower().startswith("description") or qty.lower() in ("qty", "quantity"):
            continue   # a heading row
        key = re.sub(r"\s+", " ", "|".join(parts[1:]).lower())
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:   # model is looping on the same row
            info["looped"] = True
            break
        if parse_num(qty) is None and parse_num(amount) is None and "?" not in qty + amount:
            continue   # blank pre-printed template row
        sl_num = parse_num(sl)
        item = {"sl": int(sl_num) if sl_num is not None and sl_num == int(sl_num) and sl_num > 0 else None,
                "description": re.sub(r"^\d+[.)]\s+", "", desc), "hsn": hsn or None,
                "quantity": decimal_qty(qty, rate, amount, tax), "unit": unit or None, "rate": parse_num(rate),
                "tax_percent": parse_num(tax), "amount": parse_num(amount)}
        if "?" in qty + rate + amount:
            item["unreadable"] = True
        items.append(item)
    items, repeated = drop_repeated_block(items)
    info["looped"] = info["looped"] or repeated
    return items, info


def _row_passes(it):
    return not it.get("unreadable") and row_ok(it["quantity"], it["rate"], it["amount"], it.get("tax_percent"))


def _same_row(a, b):
    """Two reads of one row agree on qty, amount and rate (or on the line value when one read took the
    GST-inclusive rate)."""
    if any(a[k] is None or b[k] is None for k in ("quantity", "rate", "amount")):
        return False
    return abs(a["quantity"] - b["quantity"]) < 0.0005 and abs(a["amount"] - b["amount"]) < 0.005 and (
        abs(a["rate"] - b["rate"]) < 0.005 or abs(a["quantity"] * a["rate"] - b["quantity"] * b["rate"]) < 0.02)


def needs_second_read(items, info, header):
    """The second, verbatim-table read is paid for only when the first read gives a reason to doubt it."""
    ok, _ = sum_check(items, header, header.get("amount_in_words"))
    return (not items or info["truncated"] or info["looped"] or info["malformed"] or len(items) > 12
            or any(not _row_passes(it) for it in items) or ok is False)


def merge_reads(a_rows, b_rows, confirmed=()):
    """Merge two reads of the item table (fixed-format read a, verbatim-table read b).

    The fixed-format read is the primary, unless fewer than half its rows pass qty x rate = amount and the
    table read does better (the first read is garbage, e.g. columns scrambled). Row by row: a primary row that
    passes is kept; if the other read's row also passes but has different numbers, both cannot be right,
    so the row is reported as a conflict (-> review). A primary row that fails takes the other read's
    row when that one passes. Rows in `confirmed` (two earlier reads agreed on them) are not overruled by a
    single dissenting read. Returns (rows, conflicts, fixed, agreed, swapped) with 1-based row numbers."""
    a_pass, b_pass = sum(map(_row_passes, a_rows)), sum(map(_row_passes, b_rows))
    swapped = a_pass < len(a_rows) / 2 and b_pass > a_pass or (not a_rows and b_rows)
    if swapped:
        a_rows, b_rows = b_rows, a_rows
    pairs = pair_reads(a_rows, b_rows)
    rows, conflicts, fixed, agreed = [], [], [], []
    for j, a in enumerate(a_rows):
        b = b_rows[pairs[j]] if j in pairs else None
        if _row_passes(a):
            if b is not None and _row_passes(b):
                if _same_row(a, b):
                    agreed.append(j + 1)
                elif swapped or (j + 1) not in confirmed:
                    conflicts.append(j + 1)
            rows.append(a)
        elif b is not None and _row_passes(b):
            rows.append({**b, "description": a["description"] or b["description"], "sl": a.get("sl", b.get("sl"))})
            fixed.append(j + 1)
        else:
            rows.append(a)
    return rows, conflicts, fixed, agreed, swapped


def read_items(img, llm, header):
    """Read the item table in the fixed 8-field format; when that read gives reason to doubt it, read the
    table a second, independent way (verbatim, columns mapped in code) and merge the two row by row.
    The second read is never told what the first read or the bill total said, so it cannot be steered
    into numbers that merely add up. Returns (items, info)."""
    reply = llm.chat(ITEMS_PROMPT, img, max_tokens=4096, step="items")
    items, info = parse_items(reply)
    info["raw"] = {"items": reply}
    info["truncated"] = bool(llm.usage and llm.usage[-1].get("finish_reason") == "length")
    info.update(second_read=False, conflicts=[], rows_fixed=[])
    if not needs_second_read(items, info, header):
        return zoom_if_needed(img, llm, items, info)
    reply = llm.chat(TABLE_PROMPT, img, max_tokens=5000, step="items_table")
    info["raw"]["items_table"] = reply
    b_items, b_info = parse_table(reply)
    # a reply cut off at the token limit, or one that drifted into prose reasoning, is not a clean second read
    clean = llm.usage[-1].get("finish_reason") != "length" and re.match(r"\s*(INK|COLUMNS)\s*:|\s*[^\n]*\|", reply)
    info.update(second_read=True, columns=b_info["columns"], second_rows=len(b_items), second_read_clean=bool(clean))
    if not b_items or not clean:
        return zoom_if_needed(img, llm, items, info)
    if info["truncated"] or info["looped"]:
        # the first read ran out of room (it thought aloud) or looped: the clean table read leads
        merged, info["conflicts"], info["rows_fixed"], info["agreed"], swapped = merge_reads(b_items, items)
        swapped = not swapped
    else:
        merged, info["conflicts"], info["rows_fixed"], info["agreed"], swapped = merge_reads(items, b_items)
    info["primary"] = "table" if swapped else "rows"
    info["ink"] = info["ink"] or b_info["ink"]
    return zoom_if_needed(img, llm, merged, info)


def zoom_if_needed(img, llm, items, info):
    """Long tables (small print) and tables still failing rows after two reads get a third, zoomed read,
    stitched by serial number and merged the same way. Needs printed serial numbers to stitch."""
    bad = [it for it in items if not _row_passes(it)]
    if not items or not all(it.get("sl") is not None for it in items) or not (len(items) > 15 or bad):
        return items, info
    z = read_items_zoomed(img, llm, len(items))
    info["zoom_rows"] = len(z)
    if not z:
        return items, info
    merged, conflicts, fixed, _, swapped = merge_reads(items, z, confirmed=set(info.get("agreed", [])))
    info["conflicts"] = sorted(set(info["conflicts"]) | set(conflicts))
    info["rows_fixed"] = sorted(set(info["rows_fixed"]) | set(fixed))
    if swapped:
        info["primary"] = "zoom"
    return merged, info


STRIP_PROMPT = ITEMS_PROMPT.replace(
    "Read the item table of this bill.",
    "This is a zoomed horizontal strip of a bill. Read only the item-table rows that are fully visible in it.").replace(
    "then EVERY product row, top to bottom,", "then every fully visible product row, top to bottom,")


def strips(img, n, top=0.12, overlap=0.18, scale=2, max_side=2600):
    """n overlapping horizontal strips covering the page below the letterhead, upscaled for small print."""
    h0 = img.height * top
    step = (img.height - h0) / n
    for k in range(n):
        y0 = max(0, int(h0 + k * step - step * overlap))
        y1 = min(img.height, int(h0 + (k + 1) * step + step * overlap))
        c = img.crop((0, y0, img.width, y1))
        f = min(scale, max_side / max(c.size))
        yield c.resize((int(c.width * f), int(c.height * f)), Image.LANCZOS)


def read_items_zoomed(img, llm, n_rows):
    """Read a long table again strip by strip at 2x and stitch the rows by printed serial number.
    Returns rows (only those with a serial number; a serial seen in two strips keeps the read that passes
    qty x rate = amount)."""
    by_sl = {}
    for c in strips(img, max(2, -(-n_rows // 15))):
        rows, _ = parse_items(llm.chat(STRIP_PROMPT, c, max_tokens=2500, step="items_zoom"))
        for r in rows:
            if r["sl"] is None:
                continue
            old = by_sl.get(r["sl"])
            if old is None or (not _row_passes(old) and _row_passes(r)):
                by_sl[r["sl"]] = r
    return [by_sl[k] for k in sorted(by_sl)]


VERIFY_PROMPT = """This is the top part of a photographed purchase bill. Look very closely at the printed INVOICE / BILL
NUMBER field. Has that printed number itself been struck through with a pen line, with a replacement number handwritten
next to or below it? Ignore the receiver's reference notes like "Bill-641" / "BIL 632" scribbled elsewhere on the page -
those are not corrections and not the invoice number.
Also copy the invoice date exactly as printed, and every GSTIN printed (15 characters each), exactly as printed.
Reply as JSON: {"struck_through": true/false, "printed_number": "...", "replacement_number": "..." or null,
"invoice_date_as_printed": "..." or null, "gstins": ["...", ...]}"""
# Asking for both numbers (not a bare yes/no) is what makes the model actually look at the field;
# with a bare yes/no it answered "no" every time. The numbers double as a second, zoomed read.
VERIFY_SCHEMA = {"type": "object", "properties": {
    "struck_through": {"type": "boolean"}, "printed_number": {"type": ["string", "null"]},
    "replacement_number": {"type": ["string", "null"]}, "invoice_date_as_printed": {"type": ["string", "null"]},
    "gstins": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
    "required": ["struck_through", "printed_number", "replacement_number", "invoice_date_as_printed", "gstins"]}


def header_crop(img, frac=0.45, scale=2):
    c = img.crop((0, 0, img.width, int(img.height * frac)))
    return c.resize((c.width * scale, c.height * scale), Image.LANCZOS)


def verify_header(img, llm):
    """Second, independent read of the header on a 2x crop of the top of the page (falls back to the
    full page when the invoice number isn't in the crop). Returns the reply dict ({} on failure)."""
    for im, step in ((header_crop(img), "header_verify"), (img, "header_verify_full")):
        try:
            v = json.loads(llm.chat(VERIFY_PROMPT, im, schema=VERIFY_SCHEMA, max_tokens=300, step=step))
        except (json.JSONDecodeError, AttributeError):
            v = {}
        if v.get("printed_number"):
            return v
    return v


# ---------- second read: the table transcribed verbatim, columns mapped in code ----------
# A differently-shaped prompt makes this read fairly independent of the first: in an A/B on 24 hard
# bills, merging the two raised exactly-right rows from 77.6% to 81.1% and exposed 10 wrong rows that
# were arithmetically self-consistent (see docs/DECISIONS.md).

TABLE_PROMPT = """Transcribe the item table of this bill exactly as printed. Output exactly these lines and nothing else:
INK: pen   or   INK: printed     (how the quantity / rate / amount figures in the table are written)
COLUMNS: every column heading of the item table, left to right, separated by |
then EVERY product row, top to bottom, one per line: its cell values in the same column order, separated by |
(leave a cell empty between the pipes if it is blank), and finally a line: END
Rules:
- Copy every number exactly as printed. Never calculate, round or correct a value. Write ? for a digit you cannot read.
- One line per product: join multi-line descriptions. Read through rubber stamps and pen marks; if a value is crossed out
  and rewritten by hand, use the rewritten value.
- Skip pre-printed product rows that have no quantity and no amount filled in. No totals, tax summary or heading rows.
- Start your reply with the INK line. Do not analyse, explain or think aloud - just the lines.
- No markdown, bullets or commentary."""


def _heading(s):
    return re.sub(r"[^a-z0-9%]+", " ", (s or "").lower()).strip()


def heading_role(h):
    """What a printed column heading holds: sl, desc, hsn, qty, unit, rate, rate_incl, mrp, tax_rate, amount,
    or None for columns we don't use (tax amounts, taxable value, discount...)."""
    if (h or "").strip() in ("#", "No.", "No"):
        return "sl"
    h = _heading(h)
    if re.search(r"hsn|sac", h):
        return "hsn"
    taxy = re.search(r"\b(c|s|i)?gst\b|\btax\b|\bkfc\b|\bcess\b", h)
    if taxy and re.search(r"%|rate", h) and "amount" not in h and "amt" not in h:
        return "tax_rate"
    if h in ("%", "gst", "tax"):
        return "tax_rate"
    if taxy or "taxable" in h or "disc" in h or "less" in h:
        return None
    if "mrp" in h:
        return "mrp"
    if re.fullmatch(r"(sl|s|si|sr|serial)?\s*(no|n|nr)?|#|sl|sno|s no|sl no|sr no|si no", h) and h:
        return "sl"
    if re.search(r"desc|item|particular|product|goods|commodity|name", h):
        return "desc"
    if re.search(r"hsn|sac", h):
        return "hsn"
    if "incl" in h and re.search(r"rate|price", h):
        return "rate_incl"
    if re.search(r"rate|price", h):
        return "rate"
    if re.search(r"qty|quantity|billed|shipped|\bpcs\b|\bnos\b|count", h):
        return "qty"
    if re.search(r"uom|unit|\bper\b", h):
        return "unit"
    if re.search(r"\bps\b|paise", h) or h == "p":
        return "paise"
    if re.search(r"amount|total|value|\bnet\b|\bamt\b|\brs\b", h):
        return "amount"
    return None


def map_columns(headings):
    """Column index for each field, from the printed headings. Returns None if qty, rate or amount is missing."""
    roles = [heading_role(h) for h in headings]
    pick = lambda role, last=False: ([i for i, r in enumerate(roles) if r == role][-1 if last else 0]
                                     if role in roles else None)
    cols = {"sl": pick("sl"), "desc": pick("desc"), "hsn": pick("hsn"), "unit": pick("unit"),
            "rate": pick("rate"), "rate_incl": pick("rate_incl"), "amount": pick("amount", last=True),
            "paise": pick("paise"), "tax_rate": [i for i, r in enumerate(roles) if r == "tax_rate"]}
    qtys = [i for i, r in enumerate(roles) if r == "qty"]
    billed = [i for i in qtys if "billed" in _heading(headings[i])]
    cols["qty"] = (billed or qtys or [None])[0]
    if cols["rate"] is None:
        cols["rate"] = cols["rate_incl"]
    if None in (cols["qty"], cols["rate"], cols["amount"]):
        return None
    return cols


def parse_rate_cell(s):
    """A GST rate cell: '5%', '2.5', '5.00' or '365.00 (5%)' (amount with the rate in brackets) -> 5.0."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s or "")
    if m:
        return float(m.group(1))
    n = parse_num(s)
    return n if n is not None and n <= 28 else None


def parse_table(text):
    """Parse the verbatim-table reply into the same (items, info) shape as parse_items."""
    info = {"ink": None, "columns": None, "malformed": 0, "looped": False, "unmapped": False}
    items, seen, cols, headings = [], {}, None, None
    for line in final_block(text).splitlines():
        line = line.strip().strip("`").strip()
        up = line.upper()
        if up.startswith("END"):
            break
        if up.startswith("INK:"):
            pen, printed = "PEN" in up, "PRINT" in up
            info["ink"] = "pen" if pen and not printed else "printed" if printed and not pen else None
            continue
        if not line or _SEPARATOR.match(line) or "|" not in line:
            continue   # prose, separators
        if up.startswith("COLUMNS:"):
            line = line.split(":", 1)[1].strip()
        if line.startswith("|"):
            line = line[1:-1] if line.endswith("|") else line[1:]
        cells = [c.strip() for c in line.split("|")]
        if cols is None:
            # the first pipe line with mostly non-numeric cells is the heading row (with or without "COLUMNS:")
            if sum(parse_num(c) is None for c in cells) >= max(2, len(cells) * 0.6):
                headings, info["columns"] = cells, " | ".join(cells)
                cols = map_columns(headings)
                info["unmapped"] = cols is None
                if cols is None:
                    return [], info
            continue
        if len(cells) != len(headings):
            # a merged or split heading: amount columns sit at the right, so map from the right end
            if len(cells) > len(headings) and cols["amount"] == len(headings) - 1:
                cells = cells[:cols["qty"]] + cells[len(cells) - (len(headings) - cols["qty"]):]
            if len(cells) != len(headings):
                info["malformed"] += 1
                continue
        if [_heading(c) for c in cells] == [_heading(h) for h in headings]:
            continue   # the heading row repeated
        key = re.sub(r"\s+", " ", "|".join(cells).lower())
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:
            info["looped"] = True
            break
        cell = lambda k: cells[cols[k]] if cols.get(k) is not None else ""
        qty, rate, amount = cell("qty"), cell("rate"), cell("amount")
        if cols["paise"] is not None and cells[cols["paise"]].strip().isdigit():
            amount = f"{re.sub(r'[^0-9]', '', amount)}.{cells[cols['paise']].strip():0>2}"
        if parse_num(qty) is None and parse_num(amount) is None and "?" not in qty + amount:
            continue   # blank pre-printed template row
        tax = None
        if cols["tax_rate"]:
            rates = [parse_rate_cell(cells[i]) for i in cols["tax_rate"]]
            if any(r is not None for r in rates):
                tax = sum(r or 0 for r in rates)
        sl_num = parse_num(cell("sl"))
        item = {"sl": int(sl_num) if sl_num is not None and sl_num == int(sl_num) and sl_num > 0 else None,
                "description": cell("desc"), "hsn": cell("hsn") or None,
                "quantity": decimal_qty(qty, rate, amount, str(tax) if tax is not None else None), "unit": cell("unit") or None, "rate": parse_num(rate),
                "tax_percent": tax, "amount": parse_num(amount)}
        if "?" in qty + rate + amount:
            item["unreadable"] = True
        items.append(item)
    items, repeated = drop_repeated_block(items)
    info["looped"] = info["looped"] or repeated
    return items, info


def _desc_key(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def pair_reads(a_rows, b_rows, min_sim=0.5):
    """Pair the rows of two reads of the same table: {index in a: index in b}.

    By printed serial number when every row of both reads has one; otherwise order-preserving
    (like sequence alignment) on description similarity, pairing only rows at least min_sim alike."""
    if a_rows and b_rows and all(r.get("sl") is not None for r in a_rows + b_rows):
        by_sl = {r["sl"]: k for k, r in enumerate(b_rows)}
        return {j: by_sl[r["sl"]] for j, r in enumerate(a_rows) if r["sl"] in by_sl}
    n, m = len(a_rows), len(b_rows)
    sim = [[difflib.SequenceMatcher(None, _desc_key(a["description"]), _desc_key(b["description"])).ratio()
            for b in b_rows] for a in a_rows]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1],
                             best[i + 1][j + 1] + sim[i][j] - min_sim if sim[i][j] >= min_sim else -1)
    pairs, i, j = {}, 0, 0
    while i < n and j < m:
        if sim[i][j] >= min_sim and best[i][j] == best[i + 1][j + 1] + sim[i][j] - min_sim:
            pairs[i] = j
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs
