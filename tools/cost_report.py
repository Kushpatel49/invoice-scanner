#!/usr/bin/env python3
"""Per-bill token and cost report for a results folder, in USD and INR.

    python tools/cost_report.py results [--inr 88] [--csv cost_report.csv]

Costs are what OpenRouter billed for each call (returned in the API response),
not estimates; they matched the account balance to within $0.000002 in testing.
"""
import argparse
import collections
import csv
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", default="results")
    ap.add_argument("--inr", type=float, default=88.0, help="rupees per US dollar (default 88)")
    ap.add_argument("--csv", help="also write a per-bill CSV here")
    a = ap.parse_args()

    rows, steps = [], collections.defaultdict(lambda: [0, 0, 0, 0.0])
    for f in sorted(Path(a.results).glob("*.json")):
        d = json.loads(f.read_text())
        u = d["_meta"]["usage"]
        rows.append((f.stem, d["_meta"]["status"], len(d["line_items"]), u))
        for c in u["per_call"]:
            s = steps[c["step"]]
            s[0] += 1; s[1] += c["prompt_tokens"]; s[2] += c["completion_tokens"]; s[3] += c["cost_usd"]
    if not rows:
        raise SystemExit(f"no results in {a.results}")

    print(f"{'bill':10} {'calls':>5} {'in tok':>7} {'out tok':>7} {'USD':>9} {'INR':>7}")
    for stem, _, _, u in rows:
        print(f"{stem:10} {u['calls']:5} {u['prompt_tokens']:7} {u['completion_tokens']:7} "
              f"{u['cost_usd']:9.5f} {u['cost_usd'] * a.inr:7.3f}")
    costs = sorted(u["cost_usd"] for *_, u in rows)
    n, total = len(costs), sum(costs)
    print(f"\n{n} bills: total ${total:.5f} (Rs {total * a.inr:.2f}); average Rs {total / n * a.inr:.3f}/bill; "
          f"median Rs {costs[n // 2] * a.inr:.3f}; range Rs {costs[0] * a.inr:.3f}-{costs[-1] * a.inr:.3f}")
    print(f"per 1,000 bills: about Rs {total / n * 1000 * a.inr:,.0f}")
    print("\nby step:")
    for k, (c, p, o, cost) in sorted(steps.items(), key=lambda kv: -kv[1][3]):
        print(f"  {k:14} calls={c:3} avg in={p / c:5.0f} out={o / c:5.0f}  Rs {cost / c * a.inr:.3f} each, "
              f"{cost / total:4.0%} of spend")

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["bill", "status", "line_items", "calls", "input_tokens", "output_tokens", "cost_usd", "cost_inr"])
            for stem, status, lines, u in rows:
                w.writerow([stem, status, lines, u["calls"], u["prompt_tokens"], u["completion_tokens"],
                            f"{u['cost_usd']:.6f}", f"{u['cost_usd'] * a.inr:.3f}"])
        print(f"\nwrote {a.csv}")


if __name__ == "__main__":
    main()
