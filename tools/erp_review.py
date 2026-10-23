#!/usr/bin/env python3
"""Build the data and photos for the ERP review page: each scanned bill as the ERP would receive it,
with its review status and, where ground truth exists, which values are right.

    python tools/erp_review.py --real results/e2e-real --synthetic results/e2e-holdout \\
        --synthetic-gt bench/data/synth-v1-holdout/gt --out results/erp-review

Writes <out>/index.html (the review page, data embedded), <out>/preview.html (the same page as a full
document for opening locally) and <out>/img/{real,syn}/<id>.jpg (upright photos, web-sized).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from bench.score import align_rows, check_row  # noqa: E402
from invoice_scanner.erp import erp_row, to_erp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
norm = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def web_photo(src, dst, side=1100):
    im = Image.open(src).convert("RGB")
    im.thumbnail((side, side))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=80, optimize=True)


def header_check(d, truth_no, truth_date, truth_gstin, truth_total, exact_no=True):
    """Which extracted header values match the truth (None = not checked)."""
    got_no = norm(d.get("invoice_number"))
    ok_no = (got_no == norm(truth_no)) if exact_no else (bool(norm(truth_no)) and norm(truth_no) in got_no)
    total = (d.get("totals") or {}).get("grand_total")
    return {
        "invoiceNo": {"ok": ok_no, "truth": truth_no},
        "invoiceDate": {"ok": d.get("invoice_date") == truth_date, "truth": truth_date},
        "gstin": {"ok": (d["supplier"].get("gstin") or None) == (truth_gstin or None), "truth": truth_gstin},
        "grandTotal": None if truth_total is None else
        {"ok": total is not None and abs(total - truth_total) < 0.01, "truth": truth_total},
    }


def bill_entry(d, bill_id, kind, photo):
    m = d["_meta"]
    rows = [erp_row(it) for it in d["line_items"]]
    return {
        "id": bill_id, "set": kind, "photo": photo,
        "status": m["status"], "issues": m["issues"],
        "erp": to_erp(d),
        "rowsChecked": [ok for _, ok in rows],
        "extra": {"gstin": d["supplier"].get("gstin"), "gstinConfirmed": d["supplier"].get("gstin_verified"),
                  "grandTotal": (d.get("totals") or {}).get("grand_total"),
                  "receiverRef": d.get("receiver_bill_ref"), "notes": d.get("handwritten_notes") or [],
                  "handwritten": d.get("is_handwritten"), "continued": d.get("continued_on_next_page")},
        "costInr": round(m["usage"]["cost_usd"] * 88, 3),
    }


def synthetic_truth(d, gt):
    """Row-by-row comparison with the generator's ground truth."""
    items, truth = d["line_items"], gt["items"]
    al = align_rows(items, truth)
    rows = [{"extra": True} for _ in items]
    for i, j, _ in al["pairs"]:
        c, t = check_row(items[j], truth[i]), truth[i]
        rows[j] = {"qty": c["qty"], "rate": c["rate"], "amount": c["amount"], "perfect": c["price_perfect"],
                   "truth": {"qty": t["quantity"], "rate": t["rate"], "amount": t["amount"]}}
    missed = [{"name": truth[i]["description"], "qty": truth[i]["quantity"], "rate": truth[i]["rate"],
               "amount": truth[i]["amount"]} for i in al["missed"]]
    head = header_check(d, gt["invoice_number"], gt["invoice_date"], gt["supplier"]["gstin"], gt["totals"]["grand_total"])
    head["supplierName"] = {"ok": None, "truth": gt["supplier"]["name"]}
    perfect = all(r.get("perfect") for r in rows) and not missed and all(v["ok"] for k, v in head.items()
                                                                           if v and v["ok"] is not None)
    return {"rows": rows, "missed": missed, "header": head, "allRight": perfect}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", required=True)
    ap.add_argument("--real-gt", default=str(ROOT / "eval" / "ground_truth.json"))
    ap.add_argument("--synthetic", required=True)
    ap.add_argument("--synthetic-gt", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    bills = []

    real_gt = json.loads(Path(a.real_gt).read_text())
    for f in sorted(Path(a.real).glob("*.json")):
        d = json.loads(f.read_text())
        photo = f"img/real/{f.stem}.jpg"
        web_photo(Path(a.real) / f"{f.stem}_upright.jpg", out / photo)
        e = bill_entry(d, f.stem, "real", photo)
        g = real_gt.get(f.stem)
        if g:
            head = header_check(d, g["invoice_number"], g["date"], g["gstin"], g["total"], exact_no=False)
            e["truth"] = {"header": head, "rows": None, "missed": [], "lineCount": g["lines"],
                          "note": g.get("note")}
        bills.append(e)

    manifest = {}
    for f in sorted(Path(a.synthetic_gt).glob("*.json")):
        manifest[f.stem] = json.loads(f.read_text())
    for f in sorted(Path(a.synthetic).glob("syn*.json")):
        d = json.loads(f.read_text())
        gt = manifest[f.stem]
        photo = f"img/syn/{f.stem}.jpg"
        web_photo(Path(a.synthetic) / f"{f.stem}_upright.jpg", out / photo)
        e = bill_entry(d, f.stem, "synthetic", photo)
        e["template"] = gt["template"]
        e["difficulty"] = gt["photo"]["difficulty"]
        e["truth"] = synthetic_truth(d, gt)
        bills.append(e)

    data = json.dumps({"bills": bills}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (Path(__file__).with_name("erp_review_page.html")).read_text().replace("/*__DATA__*/", data, 1)
    (out / "index.html").write_text(page)   # page content, as published (the host adds the document skeleton)
    (out / "preview.html").write_text(      # the same page as a full document, for opening locally
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
        'initial-scale=1,viewport-fit=cover"></head><body style="margin:0">' + page + "</body></html>")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"{len(bills)} bills -> {out}  ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
