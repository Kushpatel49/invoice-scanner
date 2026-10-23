"""Render clean template pages (no photo effects) for visual checking.

    python -m bench.synth.preview gst_modern --n 4 --seed 1 --out /tmp/prev [--boxes] [--photo]

--boxes draws the layout bboxes on top (red table, green rows/qty/amount, blue invoice no.).
--photo also runs effects.apply (once effects.py exists).
"""
import argparse
import json
import random
from pathlib import Path

from PIL import ImageDraw

from bench.synth.spec import make_spec
from bench.synth import templates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template", choices=templates.TEMPLATES)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="preview")
    ap.add_argument("--boxes", action="store_true")
    ap.add_argument("--photo", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mod = templates.get(a.template)
    for i in range(a.n):
        rng = random.Random(a.seed * 1000 + i)
        spec = make_spec(rng, f"prev{i}", a.template)
        page, layout = mod.render(spec, rng)
        if a.boxes:
            d = ImageDraw.Draw(page)
            for key, color in (("table_bbox", "red"), ("header_bbox", "orange"), ("invoice_number_bbox", "blue"),
                               ("date_bbox", "blue"), ("total_bbox", "purple"), ("notes_area", "cyan")):
                if layout.get(key):
                    d.rectangle(layout[key], outline=color, width=3)
            for r in layout.get("rows", []):
                for k in ("qty_bbox", "amount_bbox", "desc_bbox"):
                    if r.get(k):
                        d.rectangle(r[k], outline="green", width=2)
        if a.photo:
            from bench.synth import effects
            page, recipe = effects.apply(page, layout, spec, rng)
            spec["photo"] = recipe
        page.save(out / f"{a.template}_{i}.jpg", quality=88)
        (out / f"{a.template}_{i}.json").write_text(json.dumps(spec, indent=1))
        print(out / f"{a.template}_{i}.jpg", page.size, len(spec["items"]), "items",
              "continued" if spec["continued"] else "", spec["corrections"])


if __name__ == "__main__":
    main()
