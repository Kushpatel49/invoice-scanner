# Synthetic benchmark

Realistic phone photos of Indian purchase bills with **exact ground truth**, used to measure and improve the scanner's pricing accuracy. Full documentation, metric definitions and results are in [docs/BENCHMARK.md](../docs/BENCHMARK.md).

```
bench/
  synth/            the generator
    spec.py           random bill specs = ground truth (suppliers, items, GST, totals, corrections, notes)
    templates/        6 bill formats modelled on the store's real bills
    effects.py        phone-photo realism: stamps, pen notes, corrections, rotation, lighting, compression
    hand.py           fonts, handwriting, pen marks
    fonts/            bundled OFL fonts (see fonts/README.md)
    preview.py        render clean pages for checking a template
  build.py          writes a dataset: images/, gt/, manifest.csv, contact_sheet.jpg
  score.py          scores scanner output against the ground truth (row-level pricing + safety)
  reports/          scored reports: dev baseline, dev final, held-out final
  data/
    synth-v1/         100-bill dev set (seed 2026): used for diagnosis and tuning
    synth-v1-holdout/ 100-bill held-out set (seed 4049): only for reporting; never tune on it
```

Quick start:

```bash
python3 -m invoice_scanner bench/data/synth-v1/images/*.jpg --out results/dev --workers 6
python3 -m bench.score --results results/dev --gt bench/data/synth-v1/gt --md results/dev.md
```

Regenerate a dataset (deterministic for a given seed):

```bash
python3 -m bench.build --out bench/data/synth-v2 --n 100 --seed 7
```
