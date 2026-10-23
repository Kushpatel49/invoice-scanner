"""The end-to-end scan of one bill photo. See docs/ARCHITECTURE.md."""
import json
import re
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import config
from .extract import read_header, read_items, verify_header
from .gstin import find_supplier_gstin, gstin_ok
from .llm import LLM
from .ocr import deskew, orientation, page_text
from .validate import decide_date, decide_invoice_number, fold_id, validate


def scan_bill(path, llm=None, save_dir=None):
    """Scan one bill photo and return the extracted, validated result as a dict.

    result["_meta"]["status"] is "auto_ok" (every check passed) or "needs_review"
    (result["_meta"]["issues"] lists why). See docs/OUTPUT_FORMAT.md.

    llm:      an LLM instance (defaults to LLM() configured from the environment).
              Its usage list is reset for each bill.
    save_dir: if given, writes <stem>.json and <stem>_upright.jpg there.
    """
    llm = llm or LLM()
    llm.usage.clear()
    t0 = time.time()

    img = ImageOps.exif_transpose(Image.open(path))
    img.thumbnail((config.MAX_SIDE, config.MAX_SIDE))
    deg = orientation(img)
    if deg:
        img = img.rotate(-deg, expand=True)
    img, skew = deskew(img)   # level the text lines: skewed rows get matched to the wrong numbers
    ocr_text = page_text(img)

    h = read_header(img, llm)
    v = verify_header(img, llm)
    items, items_info = read_items(img, llm, h)

    checks = []
    notes = list(dict.fromkeys([n for n in [h.get("receiver_bill_ref"), *(h.get("handwritten_notes") or [])] if n]))
    struck = bool(v.get("struck_through")) or bool(
        v.get("replacement_number") and v.get("printed_number")
        and fold_id(v["replacement_number"]) != fold_id(v["printed_number"]))
    second_no = (v.get("replacement_number") if struck else None) or v.get("printed_number")
    inv_no, series, issue = decide_invoice_number(h.get("invoice_number"), second_no, ocr_text, notes)
    checks += [issue] if issue else []
    inv_date, issue = decide_date(h.get("invoice_date"), h.get("invoice_date_as_printed"),
                                  v.get("invoice_date_as_printed"), ocr_text, inv_no)
    checks += [issue] if issue else []
    model_gstin = re.sub(r"\s", "", (h.get("supplier_gstin") or "").upper()) or None
    sup_gstin, gstin_source, issue = find_supplier_gstin(img, model_gstin, v.get("gstins") or [], ocr_text, llm)
    checks += [issue] if issue else []
    if (items_info["truncated"] or items_info["looped"]) and not items_info.get("second_read_clean"):
        checks.append("the item table could not be read completely (model output cut off) - check every row")
    if items_info["malformed"] and not items_info["second_read"]:
        checks.append(f"{items_info['malformed']} item row(s) could not be parsed - check the table")
    if items_info["conflicts"]:
        rows = ", ".join(map(str, items_info["conflicts"][:8]))
        checks.append(f"row(s) {rows} read differently in two passes - check qty, rate and amount")

    d = {
        "supplier": {"name": h.get("supplier_name"), "gstin": sup_gstin,
                     "gstin_verified": gstin_ok(sup_gstin) and gstin_source not in ("unverified", "none"),
                     "address": h.get("supplier_address"), "phone": h.get("supplier_phone")},
        "buyer": {"name": h.get("buyer_name"), "gstin": config.COMPANY_GSTIN},
        "invoice_number": inv_no,
        "invoice_series": series,
        "invoice_date": inv_date,
        "is_handwritten": bool(h.get("items_handwritten")) or items_info["ink"] == "pen",
        "continued_on_next_page": bool(h.get("continued_on_next_page")),
        "line_items": items,
        "totals": {k: h.get(k) for k in ("subtotal", "cgst", "sgst", "igst", "cess", "round_off", "grand_total")},
        "amount_in_words": h.get("amount_in_words"),
        "header_corrected": bool(h.get("header_corrected")) or struck,
        "receiver_bill_ref": h.get("receiver_bill_ref"),
        "handwritten_notes": list(dict.fromkeys(h.get("handwritten_notes") or [])),
    }
    issues = validate(d, checks)
    d["_meta"] = {
        "source": str(path), "model": llm.name, "rotated_deg": deg, "deskew_deg": skew,
        "status": "needs_review" if issues else "auto_ok", "issues": issues,
        "items_second_read": items_info["second_read"], "rows_fixed_by_second_read": items_info["rows_fixed"],
        "items_primary": items_info.get("primary", "rows"), "items_zoom_rows": items_info.get("zoom_rows"),
        "gstin_source": gstin_source,
        # what each read saw, so a reviewer (or a developer) can see why a check passed or failed
        "evidence": {"invoice_number_reads": [h.get("invoice_number"), second_no],
                     "date_reads": [h.get("invoice_date_as_printed"), h.get("invoice_date"), v.get("invoice_date_as_printed")],
                     "gstin_reads": [model_gstin, v.get("gstins")], "struck_through": struck,
                     "ink": items_info["ink"], "header_says_handwritten": bool(h.get("items_handwritten")),
                     "columns": items_info["columns"]},
        "raw_replies": items_info["raw"],   # the model's item-table text, for debugging misreads
        "seconds": round(time.time() - t0, 1),
        "usage": llm.usage_summary(),
    }
    if save_dir:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(path).stem
        (save_dir / f"{stem}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False))
        img.save(save_dir / f"{stem}_upright.jpg", quality=85)
    return d
