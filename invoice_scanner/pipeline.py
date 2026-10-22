"""The end-to-end scan of one bill photo. See docs/ARCHITECTURE.md."""
import json
import re
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import config
from .extract import invoice_no_struck, read_header, read_items
from .gstin import find_supplier_gstin, gstin_ok
from .llm import LLM
from .ocr import orientation
from .validate import validate


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

    h = read_header(img, llm)
    items, rechecked = read_items(img, llm, h)
    model_gstin = re.sub(r"\s", "", (h.get("supplier_gstin") or "").upper()) or None
    sup_gstin, gstin_source = find_supplier_gstin(img, model_gstin, llm)

    d = {
        "supplier": {"name": h.get("supplier_name"), "gstin": sup_gstin, "gstin_verified": gstin_ok(sup_gstin),
                     "address": h.get("supplier_address"), "phone": h.get("supplier_phone")},
        "buyer": {"name": h.get("buyer_name"), "gstin": config.COMPANY_GSTIN},
        "invoice_number": h.get("invoice_number"),
        "invoice_date": h.get("invoice_date"),
        "is_handwritten": bool(h.get("items_handwritten")),
        "continued_on_next_page": bool(h.get("continued_on_next_page")),
        "line_items": items,
        "totals": {k: h.get(k) for k in ("subtotal", "cgst", "sgst", "igst", "cess", "round_off", "grand_total")},
        "amount_in_words": h.get("amount_in_words"),
        "header_corrected": bool(h.get("header_corrected")) or invoice_no_struck(img, llm),
        "handwritten_notes": list(dict.fromkeys(h.get("handwritten_notes") or [])),
    }
    issues = validate(d)
    d["_meta"] = {
        "source": str(path), "model": llm.name, "rotated_deg": deg, "items_rechecked": rechecked,
        "gstin_source": gstin_source, "seconds": round(time.time() - t0, 1),
        "status": "needs_review" if issues else "auto_ok", "issues": issues,
        "usage": llm.usage_summary(),
    }
    if save_dir:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(path).stem
        (save_dir / f"{stem}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False))
        img.save(save_dir / f"{stem}_upright.jpg", quality=85)
    return d
