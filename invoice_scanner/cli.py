"""Command line: python -m invoice_scanner bills/*.jpg --out results"""
import argparse
from pathlib import Path

from . import config
from .llm import LLM
from .pipeline import scan_bill


def main(argv=None):
    ap = argparse.ArgumentParser(prog="invoice-scanner", description="Scan bill photos into validated JSON.")
    ap.add_argument("images", nargs="+", help="bill photos (jpg/png)")
    ap.add_argument("--out", default="results", help="output folder (default: results)")
    ap.add_argument("--backend", choices=list(config.MODELS), default=config.default_backend())
    ap.add_argument("--model", help="override the backend's default model")
    a = ap.parse_args(argv)

    llm = LLM(a.backend, a.model)
    print(f"model={llm.name}", flush=True)
    counts, cost = {"auto_ok": 0, "needs_review": 0, "error": 0}, 0.0
    for p in a.images:
        try:
            d = scan_bill(p, llm, save_dir=a.out)
        except Exception as e:
            counts["error"] += 1
            print(f"{Path(p).name}: ERROR {e!r}", flush=True)
            continue
        m, u = d["_meta"], d["_meta"]["usage"]
        counts[m["status"]] += 1
        cost += u["cost_usd"]
        print(f"{Path(p).name}: {m['status']:12} {len(d['line_items']):3} lines  total={d['totals']['grand_total']}  "
              f"gstin={d['supplier']['gstin']}  {m['seconds']}s  rot={m['rotated_deg']}  "
              f"calls={u['calls']} tok={u['prompt_tokens']}+{u['completion_tokens']} ${u['cost_usd']:.5f}", flush=True)
        for i in m["issues"]:
            print(f"    - {i}", flush=True)
    print(f"\n{counts['auto_ok']} ready to post, {counts['needs_review']} need review, {counts['error']} errors; "
          f"model cost ${cost:.4f}. Results in {a.out}/", flush=True)
    return 1 if counts["error"] else 0
