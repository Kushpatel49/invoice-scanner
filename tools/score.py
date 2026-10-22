#!/usr/bin/env python3
"""Score a results folder against eval/ground_truth.json.

    python tools/score.py results

Per bill: supplier GSTIN, invoice number, date, grand total and line-item count.
The number that matters most is the last line: bills marked auto_ok whose data
is actually wrong. That must stay 0 - it is the only way a bad bill reaches the ERP.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    res_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
    gt = json.loads((ROOT / "eval" / "ground_truth.json").read_text())
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    tally = dict.fromkeys(("gstin", "invoice_number", "date", "total", "lines"), 0)
    silent_wrong = missing = 0
    print(f"{'bill':6} {'status':12} {'gstin':5} {'inv#':5} {'date':5} {'total':5} {'lines':9} sec")
    for k, g in gt.items():
        f = res_dir / f"{k}.json"
        if not f.exists():
            missing += 1
            print(k, "missing")
            continue
        d = json.loads(f.read_text())
        ok = {
            "gstin": d["supplier"]["gstin"] == g["gstin"],
            # substring match: "RO 2199" style prefixes on the printed number are fine
            "invoice_number": norm(g["invoice_number"]) in norm(d["invoice_number"]),
            "date": d["invoice_date"] == g["date"],
            # null truth = no total on this page (multi-page bill); anything is accepted
            "total": g["total"] is None or (d["totals"]["grand_total"] is not None
                                            and abs(d["totals"]["grand_total"] - g["total"]) < 1),
            "lines": len(d["line_items"]) == g["lines"],
        }
        for x in ok:
            tally[x] += ok[x]
        st = d["_meta"]["status"]
        if st == "auto_ok" and not all(ok.values()):
            silent_wrong += 1
        m = lambda b: "ok" if b else "XX"
        print(f"{k:6} {st:12} {m(ok['gstin']):5} {m(ok['invoice_number']):5} {m(ok['date']):5} {m(ok['total']):5} "
              f"{len(d['line_items']):>3}/{g['lines']:<3}{'' if ok['lines'] else 'XX'}  {d['_meta']['seconds']}")
    n = len(gt)
    print("\naccuracy: " + "  ".join(f"{k} {v}/{n}" for k, v in tally.items()) + (f"  ({missing} missing)" if missing else ""))
    print(f"auto_ok but actually wrong (must be 0): {silent_wrong}")
    return 1 if silent_wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
