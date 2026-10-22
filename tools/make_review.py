#!/usr/bin/env python3
"""Build a single-file HTML review page: each bill photo beside its extracted data,
with problem rows and issues highlighted. A stand-in for the ERP review screen.

    python tools/make_review.py results [--out review.html]
"""
import argparse, base64, html, json, re
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("results", nargs="?", default="results")
ap.add_argument("--out", default="review.html")
args = ap.parse_args()

res = Path(args.results)
e = lambda v: "" if v is None else html.escape(str(v))
money = lambda v: "" if v is None else f"₹{v:,.2f}"
cards, ok_n = [], 0
for f in sorted(res.glob("*.json")):
    d = json.loads(f.read_text())
    m = d["_meta"]
    ok = m["status"] == "auto_ok"
    ok_n += ok
    bad_rows = {int(x.group(1)) for i in m["issues"] if (x := re.match(r"line (\d+) ", i))}
    rows = "".join(
        f"<tr class='{'bad' if n in bad_rows else ''}'><td>{n}</td><td>{e(it['description'])}</td><td>{e(it.get('hsn'))}</td>"
        f"<td class=r>{e(it['quantity'])}</td><td>{e(it.get('unit'))}</td><td class=r>{e(it['rate'])}</td>"
        f"<td class=r>{e(it.get('tax_percent'))}</td><td class=r>{money(it['amount'])}</td></tr>"
        for n, it in enumerate(d["line_items"], 1))
    t = d["totals"]
    tax = " · ".join(f"{k.upper()} {money(t[k])}" for k in ("cgst", "sgst", "igst", "cess") if t.get(k))
    sup = d["supplier"]
    gst = (f"{e(sup['gstin'])} <span class=tick title='checksum valid'>✓</span>" if sup["gstin_verified"]
           else e(sup["gstin"]) or "<span class=muted>none</span>")
    issues = "".join(f"<li>{e(i)}</li>" for i in m["issues"])
    notes = ", ".join(e(n) for n in d["handwritten_notes"])
    # embed the photo so the page is one self-contained file
    img = "data:image/jpeg;base64," + base64.b64encode((res / f"{f.stem}_upright.jpg").read_bytes()).decode()
    cards.append(f"""
<section class="card {'ok' if ok else 'review'}">
  <a class=photo href="{img}" target=_blank><img src="{img}" loading=lazy></a>
  <div class=data>
    <div class=top><h2>{e(sup['name'])}</h2><span class="badge">{'Ready to post' if ok else 'Needs review'}</span></div>
    <dl>
      <dt>Invoice no</dt><dd>{e(d['invoice_number'])}</dd>
      <dt>Date</dt><dd>{e(d['invoice_date'])}</dd>
      <dt>Supplier GSTIN</dt><dd>{gst}</dd>
      <dt>Grand total</dt><dd class=big>{money(t.get('grand_total'))}</dd>
      {f"<dt>Tax</dt><dd>{tax}</dd>" if tax else ""}
      {f"<dt>Pen notes</dt><dd>{notes}</dd>" if notes else ""}
    </dl>
    {f"<ul class=issues>{issues}</ul>" if issues else ""}
    <div class=tbl><table><thead><tr><th>#</th><th>Item</th><th>HSN</th><th class=r>Qty</th><th>Unit</th><th class=r>Rate</th><th class=r>Tax%</th><th class=r>Amount</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
    <p class=meta>{e(Path(m['source']).name)} · {len(d['line_items'])} lines · rotated {m['rotated_deg']}° · {m['seconds']}s{' · items re-read after self-check' if m.get('items_rechecked') else ''}</p>
  </div>
</section>""")

page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Purchase Bill Review</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--muted:#77756f;--line:#e4e2dc;--ok:#1f7a4d;--okbg:#e7f4ec;--warn:#a5530a;--warnbg:#fdf0e1;--bad:#fbe4e1}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--muted:#9a978f;--line:#33322f;--ok:#5fc48f;--okbg:#17301f;--warn:#f0a25a;--warnbg:#36250f;--bad:#3d1f1b}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,sans-serif}}
header{{padding:24px 16px 8px;max-width:1300px;margin:auto}} h1{{margin:0 0 4px;font-size:22px}} header p{{margin:0;color:var(--muted)}}
main{{max-width:1300px;margin:auto;padding:8px 16px 40px;display:grid;gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:10px;display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);overflow:hidden}}
.card.ok{{border-left-color:var(--ok)}}
.photo{{background:#0001;display:block}} .photo img{{width:100%;height:100%;max-height:520px;object-fit:contain;display:block}}
.data{{padding:14px 16px;min-width:0}} .top{{display:flex;gap:10px;align-items:center;justify-content:space-between}} h2{{margin:0;font-size:17px}}
.badge{{font-size:12px;font-weight:600;padding:3px 9px;border-radius:99px;background:var(--warnbg);color:var(--warn);white-space:nowrap}}
.ok .badge{{background:var(--okbg);color:var(--ok)}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;margin:10px 0}} dt{{color:var(--muted)}} dd{{margin:0;font-variant-numeric:tabular-nums}}
.big{{font-weight:700;font-size:16px}} .tick{{color:var(--ok);font-weight:700}} .muted{{color:var(--muted)}}
.issues{{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:8px 10px 8px 28px;margin:8px 0}}
.tbl{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}}
th{{color:var(--muted);font-weight:500}} .r{{text-align:right;font-variant-numeric:tabular-nums}} tr.bad td{{background:var(--bad)}}
.meta{{color:var(--muted);font-size:12px;margin:8px 0 0}}
@media (max-width:760px){{.card{{grid-template-columns:1fr}} .photo img{{max-height:320px}}}}
</style></head><body>
<header><h1>Purchase bill review</h1><p>{len(cards)} bills scanned · {ok_n} ready to post · {len(cards)-ok_n} need a quick check</p></header>
<main>{''.join(cards)}</main></body></html>"""
Path(args.out).write_text(page)
print(f"wrote {args.out}")
