"""Generate the synthetic benchmark: bill photos + exact ground truth.

    python3 -m bench.build --out bench/data/synth-v1 --n 100 --seed 2026

Writes
    <out>/images/synNNN.jpg     the phone-photo-like bill
    <out>/gt/synNNN.json        ground truth: the full spec incl. the photo recipe
    <out>/manifest.csv          one line per bill: template, difficulty, flags
    <out>/contact_sheet.jpg     thumbnails of every bill for a quick visual check

The same --seed always produces the same bills (fonts are bundled in bench/synth/fonts).
"""
import argparse
import csv
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

from bench.synth import effects, templates
from bench.synth.hand import font
from bench.synth.spec import make_spec

# Share of each template, modelled on the bills the store actually receives:
# roughly a third handwritten bill books, the rest printed formats.
MIX = {"handbook": 32, "gst_modern": 18, "tally": 16, "dotmatrix": 12, "software": 12, "carbon": 10}
DIFFICULTY = {"easy": 30, "medium": 45, "hard": 25}


def spread(weights, n, rng):
    """Exactly-proportional list of keys of length n (largest remainder), shuffled."""
    total = sum(weights.values())
    raw = {k: v * n / total for k, v in weights.items()}
    counts = {k: int(x) for k, x in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[: n - sum(counts.values())]:
        counts[k] += 1
    out = [k for k, c in counts.items() for _ in range(c)]
    rng.shuffle(out)
    return out


def flags(spec):
    p = spec.get("photo", {})
    return {
        "handwritten": spec["handwritten_items"],
        "continued": spec["continued"],
        "invoice_no_corrected": bool(spec["corrections"]["invoice_number"]),
        "qty_corrected": bool(spec["corrections"]["quantity"]),
        "no_gstin": spec["supplier"]["gstin"] is None,
        "rotated": p.get("rotate_deg", 0) != 0,
        "stamp_over_table": bool(p.get("stamp_over_table")),
        "underlay": bool(p.get("underlay_gstin")),
        "tax_inclusive": spec["tax_mode"] == "inclusive",
    }


def contact_sheet(paths, out, cols=10, thumb=240):
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb, rows * (thumb + 22)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(paths):
        im = Image.open(p)
        im.thumbnail((thumb - 6, thumb - 6))
        x, y = (i % cols) * thumb, (i // cols) * (thumb + 22)
        sheet.paste(im, (x + (thumb - im.width) // 2, y + 3))
        d.text((x + 4, y + thumb), p.stem, fill=(230, 230, 230), font=font("sans", 15))
    sheet.save(out, quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench/data/synth-v1")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()

    out = Path(a.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "gt").mkdir(parents=True, exist_ok=True)
    plan_rng = random.Random(a.seed)
    tmpl = spread(MIX, a.n, plan_rng)
    diff = spread(DIFFICULTY, a.n, plan_rng)

    rows, paths = [], []
    for i in range(a.n):
        bill_id = f"syn{i + 1:03d}"
        rng = random.Random(a.seed * 1000 + i)
        spec = make_spec(rng, bill_id, tmpl[i])
        page, layout = templates.get(tmpl[i]).render(spec, rng)
        photo, recipe = effects.apply(page, layout, spec, rng, difficulty=diff[i])
        spec["photo"] = recipe
        path = out / "images" / f"{bill_id}.jpg"
        # effects already did the WhatsApp-style JPEG round trip; re-save at that quality so files stay
        # WhatsApp-sized without adding a second, different compression
        photo.save(path, quality=recipe.get("jpeg_quality", 85))
        (out / "gt" / f"{bill_id}.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False))
        f = flags(spec)
        rows.append({"id": bill_id, "template": tmpl[i], "difficulty": recipe.get("difficulty", diff[i]),
                     "items": len(spec["items"]), "rotate_deg": recipe.get("rotate_deg"),
                     "expected_review": spec["expected_review"], **f})
        paths.append(path)
        print(f"{bill_id} {tmpl[i]:10} {rows[-1]['difficulty']:6} {len(spec['items']):3} items  "
              + " ".join(k for k, v in f.items() if v), flush=True)

    with open(out / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    contact_sheet(paths, out / "contact_sheet.jpg")
    print(f"\nwrote {a.n} bills to {out}/")


if __name__ == "__main__":
    main()
