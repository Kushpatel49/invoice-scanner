#!/usr/bin/env python3
"""Re-apply the current decision rules to saved scan results, without calling the model.

    python tools/revalidate.py results/dev --out results/dev-revalidated

Each result records what the model read (_meta.evidence: both invoice-number reads, the date reads,
the GSTIN reads). This re-runs the consensus rules (invoice number, date, supplier GSTIN) on those reads
plus fresh Tesseract OCR of the saved upright photo, then re-validates the bill. Item rows, and the
issues raised while reading them, are kept as they were. The supplier GSTIN decision is kept too unless
--redo-gstin is given (OCR of the re-saved JPEG differs slightly, and paid corner crops can't be redone).

Use it to iterate on validation rules for free; re-run the scanner when the way bills are *read* changes.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from invoice_scanner.gstin import find_supplier_gstin, gstin_ok  # noqa: E402
from invoice_scanner.ocr import page_text  # noqa: E402
from invoice_scanner.validate import decide_date, decide_invoice_number, validate  # noqa: E402

# issues raised while reading the item table: these don't change without re-reading
ITEM_READ_ISSUES = ("the item table could not be read", "item row(s) could not be parsed", "row(s) ")


class NoModel:
    """Stands in for the LLM: returns nothing, so no paid crop is read."""
    def chat(self, *a, **k):
        return ""


def revalidate(d, upright, redo_gstin=False):
    m, ev = d["_meta"], d["_meta"]["evidence"]
    ocr_text = page_text(upright)
    notes = [n for n in [d.get("receiver_bill_ref"), *(d.get("handwritten_notes") or [])] if n]
    checks = []
    header_no, second_no = ev["invoice_number_reads"]
    inv_no, series, issue = decide_invoice_number(header_no, second_no, ocr_text, notes)
    checks += [issue] if issue else []
    header_printed, header_iso, second_printed = ev["date_reads"]
    inv_date, issue = decide_date(header_iso, header_printed, second_printed, ocr_text, inv_no)
    checks += [issue] if issue else []
    if redo_gstin and m.get("gstin_source") != "crop":
        guess, verify = ev["gstin_reads"]
        gstin, source, issue = find_supplier_gstin(upright, guess, verify or [], ocr_text, NoModel())
        checks += [issue] if issue else []
        d["supplier"].update(gstin=gstin, gstin_verified=gstin_ok(gstin) and source not in ("unverified", "none"))
        m["gstin_source"] = source
    else:
        checks += [i for i in m["issues"] if "GSTIN" in i and not i.startswith("supplier GSTIN not found")]
    checks += [i for i in m["issues"] if i.startswith(ITEM_READ_ISSUES)]
    d.update(invoice_number=inv_no, invoice_series=series, invoice_date=inv_date)
    issues = validate(d, checks)
    m.update(issues=issues, status="needs_review" if issues else "auto_ok", revalidated=True)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", required=True)
    ap.add_argument("--redo-gstin", action="store_true", help="also re-decide the supplier GSTIN (no paid crops)")
    a = ap.parse_args()
    src, out = Path(a.results), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    changed = 0
    for f in sorted(src.glob("*.json")):
        d = json.loads(f.read_text())
        meta = d.get("_meta") or {}
        if d.get("error") or "evidence" not in meta:
            shutil.copy(f, out / f.name)
            continue
        upright = src / f"{f.stem}_upright.jpg"
        before = meta["status"]
        d = revalidate(d, Image.open(upright), a.redo_gstin)
        shutil.copy(upright, out / upright.name)
        (out / f.name).write_text(json.dumps(d, indent=2, ensure_ascii=False))
        if d["_meta"]["status"] != before:
            changed += 1
            print(f"{f.stem}: {before} -> {d['_meta']['status']}  {d['_meta']['issues'][:2]}")
    print(f"revalidated {src} -> {out}; {changed} status changes")


if __name__ == "__main__":
    main()
