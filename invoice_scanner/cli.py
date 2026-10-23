"""Command line: python -m invoice_scanner bills/*.jpg --out results [--workers 6]"""
import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
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
    ap.add_argument("--workers", type=int, default=1,
                    help="bills scanned in parallel (default 1; 4-8 is fine for OpenRouter, keep 1 for Ollama)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip photos that already have a result in --out (resume an interrupted run)")
    a = ap.parse_args(argv)

    images = a.images
    if a.skip_existing:
        images = [p for p in images if not (Path(a.out) / f"{Path(p).stem}.json").exists()]
    model_name = LLM(a.backend, a.model).name
    print(f"model={model_name}  bills={len(images)}  workers={a.workers}", flush=True)

    counts, cost = {"auto_ok": 0, "needs_review": 0, "error": 0}, 0.0
    lock = threading.Lock()
    local = threading.local()   # one LLM per thread: its usage list is per-bill state

    def run(p):
        nonlocal cost
        if not hasattr(local, "llm"):
            local.llm = LLM(a.backend, a.model)
        try:
            d = scan_bill(p, local.llm, save_dir=a.out)
        except Exception as e:
            # leave a result file so scorers count this as a failed scan, not a missing one
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{Path(p).stem}.json").write_text(json.dumps(
                {"error": repr(e), "_meta": {"source": str(p), "status": "error", "usage": local.llm.usage_summary()}}))
            with lock:
                counts["error"] += 1
                print(f"{Path(p).name}: ERROR {e!r}", flush=True)
            return
        m, u = d["_meta"], d["_meta"]["usage"]
        lines = [f"{Path(p).name}: {m['status']:12} {len(d['line_items']):3} lines  total={d['totals']['grand_total']}  "
                 f"gstin={d['supplier']['gstin']}  {m['seconds']}s  rot={m['rotated_deg']}  "
                 f"calls={u['calls']} tok={u['prompt_tokens']}+{u['completion_tokens']} ${u['cost_usd']:.5f}"]
        lines += [f"    - {i}" for i in m["issues"]]
        with lock:
            counts[m["status"]] += 1
            cost += u["cost_usd"]
            print("\n".join(lines), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        list(pool.map(run, images))

    print(f"\n{counts['auto_ok']} ready to post, {counts['needs_review']} need review, {counts['error']} errors; "
          f"model cost ${cost:.4f}. Results in {a.out}/", flush=True)
    return 1 if counts["error"] else 0
