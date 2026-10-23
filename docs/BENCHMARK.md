# Synthetic benchmark

Fifteen real bills were enough to build the scanner, but not to measure it: on them it looked nearly perfect. The synthetic benchmark is 200 realistic phone photos of Indian purchase bills, generated with **exact ground truth** for every quantity, rate, amount, total, GSTIN, invoice number and date. That makes pricing accuracy measurable to the paisa, along with the one number that matters most: **wrong bills marked ready to post**.

> **Final result, held-out set** (100 bills never used while tuning), `nvidia/nemotron-3.5-super-vl`:
> **0 wrong bills marked `auto_ok`** (precision 100%) · **93.0% of rows exactly right** (qty, rate and amount) · 86/100 bills with every row right · 74/100 fully correct, header included · ₹0.154 per bill.

## What's in it

| | |
|---|---|
| `bench/data/synth-v1/` | **Dev set**: 100 bills (seed 2026), 975 item rows. Used for diagnosis and tuning |
| `bench/data/synth-v1-holdout/` | **Held-out set**: 100 bills (seed 4049), 854 item rows. Only for reporting; **never tune on it** |
| `images/synNNN.jpg` | The photo: 1280×960 or 960×1280, WhatsApp-compressed |
| `gt/synNNN.json` | The ground truth: the full bill spec, plus the photo recipe |
| `manifest.csv`, `contact_sheet.jpg` | One line per bill with its flags; thumbnails of all 100 |

**Bill formats** (6 templates, each modelled on the store's real bills):

| Template | Share | Modelled on | What makes it hard |
|---|---|---|---|
| `handbook` | 32 | Eggs Daily, Thalir Fresh, A.K.S. Traders, hyleaf, Dr. Growmush | Handwritten figures, pre-printed rows left blank, "1892/-" amounts, corrected quantities |
| `gst_modern` | 18 | Muralya Dairy, SH Foods | Dense per-row CGST/SGST columns, MRP vs price, tax-inclusive rows, QR/IRN clutter |
| `tally` | 16 | Aeden Fruits, NKA Fruits | Boxed Tally layout, pages that continue, tiny GSTINs |
| `dotmatrix` | 12 | Green Leaf, Nutri Leaves | 12–48 rows in a 5×7 dot font, 13–15 px tall rows, shipped/billed columns |
| `software` | 12 | R K Mercantile | Previous/current balance traps, ₹ amounts, acknowledgement block |
| `carbon` | 10 | Almova International | Pink/yellow carbon copies, smeared print, INCL rate, closing-balance traps |

**Photo effects,** all randomised:

- the purple GOODS RECEIVED stamp over the table (about 65% of bills)
- "Bill-6xx" pen notes, ticks and signatures
- struck-out invoice numbers with handwritten replacements
- another bill visible underneath, showing its own GSTIN
- folds and creases, desk or keyboard backgrounds, perspective
- rotation (about 45% sideways) and skew up to 5°
- shadows, glare, blur and noise, then WhatsApp-style JPEG

Difficulty is split 30 easy / 45 medium / 25 hard. Every ground-truth value stays legible to a person. A diagnosis pass zoomed in on all 257 errors of the baseline run and found no illegible value and no ground-truth mistake.

## How it is generated

```bash
python3 -m bench.build --out bench/data/synth-v1 --n 100 --seed 2026
```

- `bench/synth/spec.py` draws a random bill: a supplier (with a valid-checksum GSTIN, or none for small vendors), items from per-category catalogs with real HSN codes and price ranges, GST rules, totals, amount in words, corrections and pen notes. **The spec is the ground truth.**
- `bench/synth/templates/<name>.py` draws a clean page from the spec and returns the layout boxes.
- `bench/synth/effects.py` turns the page into a phone photo and records the recipe in the spec.
- Fonts are bundled (OFL), so a seed reproduces the same bills on any machine.

Each template was built, reviewed side by side against the real bills, and checked by an adversarial verifier: every printed value was OCR-matched to the spec, 200+ random specs were rendered without errors, and the layout boxes were checked.

## How it is scored

```bash
python3 -m invoice_scanner bench/data/synth-v1-holdout/images/*.jpg --out results/holdout --workers 6
python3 -m bench.score --results results/holdout --gt bench/data/synth-v1-holdout/gt --md results/holdout.md --json results/holdout.json
```

`bench/score.py` aligns the predicted rows with the true rows (order-preserving dynamic programming on description and numbers), then reports:

| Metric | Meaning |
|---|---|
| **Silent errors** | Bills marked `auto_ok` that are not fully correct. **Must be 0**; `score.py` exits non-zero otherwise |
| `auto_ok` precision | Share of `auto_ok` bills that are fully correct |
| Automation / ceiling | Share of bills marked `auto_ok`, against the share that needs no review (not handwritten, no GSTIN missing, not multi-page, no correction) |
| Missed / unnecessary review | Bills that should have been reviewed but weren't / correct bills sent to review anyway |
| **Rows exactly right** | Matched rows with qty, rate and amount all exact (0.01). The rate may be pre-tax or GST-inclusive; the amount may be the line total, taxable value or taxable + tax, since bills print all of these |
| Bills, every row right | Every true row found and exact, and no extra rows |
| Bills fully correct | Every row right, plus GSTIN, invoice number, date and grand total exact |
| Breakdowns | By template, difficulty and flag (handwritten, stamp over table, rotated, underlay, correction…) |
| Cost and latency | From `_meta.usage`: the exact USD OpenRouter billed, converted to ₹ |

## Results

### Dev set: how each change moved the numbers

| Version | Rows exactly right | Bills, every row right | Bills fully correct | `auto_ok` | **Silent errors** | Unnecessary reviews | ₹/bill |
|---|---|---|---|---|---|---|---|
| Baseline (before the benchmark) | 83.2% | 65 | 42 | 26 | **17** | 11 | 0.108 |
| A: exact arithmetic + header consensus + parser fixes | 90.8% | 78 | 69 | 36 | **0** | 3 | 0.111 |
| A+B: + deskew, second read, zoomed strips | 95.7% | 90 | 78 | 34 | **0** | 8 | 0.159 |
| Final: + think-aloud handling, tie-break rules, zoomed read shown when unclear | 93.8% | 91 | 81 | 39 | **0** | 7 ¹ | 0.155 |

¹ These are mostly bills whose two invoice-number reads disagreed. The zoomed read shown is right, but a disagreement means one read was wrong, so a person confirms. That caution is deliberate.

[DECISIONS.md](DECISIONS.md) explains each change and the evidence for it. The baseline's 17 silent errors were caused by:

- loose arithmetic tolerance: 6
- invoice numbers never checked: 6
- dates never checked: 2
- a missed strike-through: 1
- a missed handwriting flag: 1
- a model-only GSTIN that happened to pass the checksum: 1

### Held-out set: final code

Model reads come from an end-to-end run of the final code. The last rule change (which invoice-number read to show when the two disagree) was applied afterwards with `tools/revalidate.py`, which re-applies the decision rules to the saved reads without calling the model. Without it, the invoice number was 82% right and 64 bills fully correct; safety was the same.

| | Result |
|---|---|
| **Silent errors** | **0** (`auto_ok` precision 100%) |
| `auto_ok` | 39 / 100 (ceiling 58) |
| Missed reviews / unnecessary reviews | 0 / 7 |
| Rows exactly right | **93.0%** (794 / 854); qty 94.4%, rate 94.5%, amount 93.4% |
| Bills with every row right | 86 / 100 |
| Bills fully correct, header included | 74 / 100 |
| Header | GSTIN 93% · invoice no. 95% · date 98% · grand total 93% |
| Cost | ₹0.154 per bill (median ₹0.114) · ₹154 per 1,000 bills |
| Time | 15.7 s average, 12.1 s median per bill (6 workers in parallel) |

By format:

| Template | Rows exactly right | Bills, every row right |
|---|---|---|
| software | 100% | 12 / 12 |
| gst_modern | 98.1% | 17 / 18 |
| handbook | 96.8% | 27 / 32 |
| tally | 95.5% | 15 / 16 |
| carbon | 94.4% | 8 / 10 |
| **dotmatrix** | **86.7%** | 7 / 12 |

Where the misses are:

- **The invoice number** is the most common header miss on the first read: the full-page read sometimes grabs a nearby field ("B2B", a phone number, a date, the receiver's "BIL-610") or drops a digit. The two reads then disagree, so every such bill went to review, and none was posted. In 14 of these 18 cases the zoomed second read was the right one, so it is the value shown to the reviewer.
- **Dot-matrix sheets** remain the weakest format: tiny dot print, 13–15 px tall rows.
- **Hard photos** (strong shadow, blur, stamp right over the numbers) get 81% of rows right, against 95–99% for easy and medium photos.

### The 15 real bills, final code

0 wrong bills marked `auto_ok`. Line counts, invoice numbers and dates were 15/15. inv07 and inv09 were marked `auto_ok`, both fully correct; the other 13 went to review, each for a stated reason:

- **7 are handwritten** and go to review by policy.
- **2 are multi-page.**
- **Several have no GSTIN.**
- **inv06** has an invoice number that wraps onto two lines, which is unclear to the reads.
- **inv03** has GST on two rows that couldn't be reconciled.

Since the benchmark round started, the stricter rules also caught a real misread that had previously been auto-posted: on inv09, the rate 1,295.24 had been read as 1,292.04 under the stamp.

Full reports, including per-template, per-difficulty and per-flag tables and the worst bills: [`bench/reports/`](../bench/reports/): `dev-baseline.md`, `dev-final.md` and `holdout-final.md`.

## Run-to-run variation

OpenRouter routes requests to different hosts, and the model doesn't always read faint print the same way twice. Two runs of nearly identical code gave 95.7% and 93.8% of rows right on the dev set. The difference was almost entirely dot-matrix bills (91.6% vs 85.5%).

- **Before believing a gain of 1–2 points, compare two runs.**
- **Safety (silent errors) held at 0** on every run of the final rule set.

## Using it well

- **Tune on the dev set, report on the held-out set.** If you find yourself fixing things on the held-out set, generate a new held-out set with a new seed.
- **Iterate on validation rules for free:** `tools/revalidate.py results/dev --out results/dev-rv` re-applies the current rules to saved model reads, then rescore. Pay for a new run only when the way bills are *read* changes.
- **A/B any prompt change on a subset first,** such as the hard bills of one template, before a full run (₹15).
- **Synthetic bills are only as varied as the generator.** Keep adding real bills to `eval/` ([ROADMAP.md](ROADMAP.md) #1), and add a template when a new kind of bill shows up.
