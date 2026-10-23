# Invoice Scanner

Turn a phone photo of a purchase bill into validated, structured data that the ERP can insert, so staff can "scan and insert" bills instead of typing them in.

It handles the bills a store actually receives: printed GST tax invoices, dot-matrix bills, pink carbon copies, handwritten cash bills, photos taken sideways, and bills with a GOODS RECEIVED rubber stamp over the line items.

Each bill comes out in one of two states:

- **`auto_ok`**: every check passed. Safe to insert into the ERP.
- **`needs_review`**: something didn't add up. The result lists exactly what (for example `total 26676 disagrees with amount in words (26766)`), so a person confirms or fixes it before it's posted.

The design goal is that **a wrong bill is never marked `auto_ok`**. On the 100-bill held-out benchmark, on the 100-bill dev set and on the 15 real bills, that number is 0.

> **Keep this repository private.** `eval/samples/` holds real supplier bills with GSTINs, phone numbers and bank account details.

---

## Contents

- [Results so far](#results-so-far)
- [How it works](#how-it-works)
- [Setup](#setup)
- [Usage](#usage)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Development](#development)
- [Known limitations](#known-limitations)
- [Further docs](#further-docs)

---

## Results so far

Measured with the default model, `nvidia/nemotron-3.5-super-vl` via OpenRouter, on two kinds of test set:

- **The synthetic benchmark** ([docs/BENCHMARK.md](docs/BENCHMARK.md)): 200 realistic phone photos of the store's kinds of bills, with exact ground truth. 100 are a dev set; **100 are held out** and were never used while tuning.
- **The 15 real bills** in [`eval/`](eval/).

| | Held-out benchmark (100 bills) | Real bills (15) |
|---|---|---|
| **Wrong bills marked `auto_ok`** | **0** (precision 100%) | **0** |
| Rows with qty, rate and amount exactly right | **93.0%** of 854 | line counts 15 / 15 |
| Bills with every row exactly right | 86 / 100 | – |
| Bills fully correct, header included | 74 / 100 | – |
| Invoice number / date / GSTIN / total | 95% / 98% / 93% / 93% | 15 / 15 / 14 / 13 of 15 |
| Bills `auto_ok` | 39 (58 could be) | 2 (most real samples are handwritten or multi-page) |
| Cost per bill | **₹0.154** average, ₹0.114 median | ₹0.18 |
| Time per bill | 12 s median (bills run in parallel with `--workers`) | |

Every miss lands in `needs_review` with its reason, so none of them would reach the ERP without a person checking it:

- **Most rows that aren't exactly right are on dot-matrix sheets,** where 87% of rows are right. Every other format gets 94–100%.
- **The tax lines are sometimes misread.** Correct GST bills then go to review because the total can't be proven.

See [docs/BENCHMARK.md](docs/BENCHMARK.md) for the breakdowns and how the numbers moved, and [docs/COSTS.md](docs/COSTS.md) for cost.

---

## How it works

```
photo ─► upright + level ─► header read ─► zoomed header read ─► item table read(s) ─► consensus + validation ─► JSON
         (Tesseract,        (vision model,  (2x crop: 2nd read    (fixed format; when     (pure Python: exact       auto_ok /
          numpy; free)       JSON schema)    of number, date,      in doubt a 2nd,         arithmetic, two reads     needs_review
                                             GSTIN; strike-out)    verbatim read; long     must agree, OCR breaks
                                                                   tables zoomed in        small ties)
                                                                   strips)
```

1. **Upright and level.** Tesseract finds how the photo is rotated (phones often save bills sideways), and a projection profile removes small skew. Both run locally and cost nothing. Skewed rows were the main cause of numbers being matched to the wrong item.
2. **Header.** The vision model fills a small JSON schema: supplier, invoice number, date as printed, totals and tax lines, amount in words, pen notes.
3. **Zoomed header read.** A 2x crop of the top of the page is read again. This gives a second, independent read of the invoice number, date and GSTINs, and asks whether the printed number was struck out and rewritten.
4. **Item table.**
   - **The first read** returns rows as `sl | description | hsn | qty | unit | rate | tax% | amount`, copying numbers exactly.
   - **When there's reason to doubt it,** the table is read a second, different way: transcribed verbatim with its headings, mapped to fields in code. The two are merged row by row. A row that fails qty × rate = amount takes the other read's passing value, and **two plausible reads that disagree go to review**.
   - **Long tables** are read again in zoomed strips.
5. **Consensus and validation,** in plain Python:
   - **Exact arithmetic,** allowing for rounding only.
   - **Rows must add up to the total** (with printed or implied GST).
   - **Two reads must agree** on the invoice number and the date (parsed day-first in code), with OCR settling only small slips.
   - **The GSTIN** must pass its checksum and be confirmed by two sources, and two GSTINs on one photo mean review.
   - **Serial numbers, handwriting and multi-page bills** are checked too.

   Any failure means `needs_review`, with the reason.

Each design choice exists because a simpler version failed on real or benchmark bills; [docs/DECISIONS.md](docs/DECISIONS.md) records what was tried and the evidence. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the module-level detail.

---

## Setup

Requirements:

- **Python 3.9+**
- **Tesseract** (used for orientation and free GSTIN reading)
  - macOS: `brew install tesseract`
  - Ubuntu/Debian: `sudo apt install tesseract-ocr`
  - Windows: install from the [UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki) and add it to `PATH`
- **An OpenRouter API key** ([create one](https://openrouter.ai/settings/keys)). Optionally, a local [Ollama](https://ollama.com) as an offline fallback.

Steps:

```bash
git clone https://github.com/kushpatel49/invoice-scanner.git
cd invoice-scanner
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # or: pip install -r requirements.txt
cp .env.example .env             # then put your OPENROUTER_API_KEY in .env
```

Check the setup without spending anything:

```bash
python -m unittest discover -s tests     # 118 offline tests, including orientation on all sample bills
```

---

## Usage

### Command line

```bash
python -m invoice_scanner path/to/bills/*.jpg --out results --workers 6
```

The `invoice-scanner` command does the same once you've run `pip install -e .`.

Sample output:

```
model=openrouter:nvidia/nemotron-3.5-super-vl  bills=15  workers=6
inv07.jpg: auto_ok        6 lines  total=9655.0  gstin=32ADPFS4356R1Z8  10.8s  rot=90  calls=4 tok=7907+1231 $0.00128
inv06.jpg: needs_review   1 lines  total=7665.0  gstin=32AGVPR6347Q2ZA  6.7s  rot=90  calls=3 tok=6311+390 $0.00079
    - invoice number unclear: read as '27/1064' and '26-27/1064'
inv04.jpg: needs_review  12 lines  total=51000.0  gstin=None  13.4s  rot=90  calls=5 tok=9593+955 $0.00134
    - supplier GSTIN not found
...
2 ready to post, 13 need review, 0 errors; model cost $0.0308. Results in results/
```

For each photo, `results/` gets `<name>.json` (the data) and `<name>_upright.jpg` (the rotated photo, for the review screen).

Options:

- `--workers N`: scan N bills in parallel (4–8 is fine on OpenRouter; keep 1 for Ollama).
- `--skip-existing`: skip photos that already have a result in `--out`, to resume an interrupted run.
- `--backend openrouter|ollama`: which model service to use.
- `--model <id>`: try a different model, for example `--model qwen/qwen3-vl-30b-a3b-instruct`.

### Python (for ERP integration)

```python
from invoice_scanner import scan_bill

result = scan_bill("bill.jpg")            # optional: save_dir="results"

if result["_meta"]["status"] == "auto_ok":
    insert_purchase_bill(result)          # your ERP code
else:
    send_to_review_queue(result, reasons=result["_meta"]["issues"])
```

The full field list is in [docs/OUTPUT_FORMAT.md](docs/OUTPUT_FORMAT.md).

### Tools

```bash
python -m bench.score --results results --gt bench/data/synth-v1-holdout/gt --md report.md   # benchmark scoring
python tools/score.py results                     # accuracy on the real bills (eval/ground_truth.json)
python tools/revalidate.py results --out results-rv   # re-apply current validation rules to saved results, free
python tools/make_review.py results               # review.html: each photo beside its extracted data
python tools/cost_report.py results --inr 88      # tokens and cost per bill, in USD and INR
```

---

## Configuration

Settings are environment variables. Put them in `.env`; [`.env.example`](.env.example) lists them all.

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | (none) | Required for the default backend |
| `SCANNER_BACKEND` | `openrouter` if a key is set, else `ollama` | Which model service to use |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3.5-super-vl` | Hosted vision model |
| `OLLAMA_MODEL` | `qwen3-vl:8b-instruct` | Local model (`ollama pull qwen3-vl:8b-instruct`) |
| `COMPANY_NAME` | `Greens Angaadi Agro Pvt Ltd` | The buyer on every bill |
| `COMPANY_GSTIN` | `32AAHCG9621M1ZC` | Never accepted as the supplier's GSTIN |
| `COMPANY_ALIASES` | `Greens Angadi, Aeden Fresh, Kakkanad` | Other names suppliers write for us |

Use the paid Nemotron, not the `:free` variant. The free tier allows 50 requests a day (about 8 bills), and free models may train on what you send. See [docs/COSTS.md](docs/COSTS.md).

---

## Project layout

```
invoice_scanner/          the package
  pipeline.py             scan_bill(): runs the steps in order
  extract.py              prompts, schemas, parsing, the two table reads + merge, zoomed strips, header verify
  validate.py             exact arithmetic, consensus (invoice no., date), checks -> auto_ok / needs_review
  gstin.py                GSTIN checksum, OCR look-alike repair, two-source supplier GSTIN lookup
  ocr.py                  Tesseract + numpy: orientation, deskew, page text
  llm.py                  OpenRouter / Ollama client with per-call cost tracking
  config.py               settings (env / .env)
  cli.py                  command line (parallel workers, resume)
bench/                    synthetic benchmark: generator, 2 x 100-bill datasets, scorer (see bench/README.md)
tools/                    score.py, revalidate.py, make_review.py, cost_report.py
tests/                    offline unit tests (no API calls)
eval/                     15 real sample bills + hand-checked ground truth
docs/                     architecture, decisions, benchmark, evaluation, costs, output format, roadmap
```

---

## Development

- **Measure every change on the benchmark.** Tune on the dev set, report on the held-out set:
  ```bash
  python -m invoice_scanner bench/data/synth-v1/images/*.jpg --out results/dev --workers 6
  python -m bench.score --results results/dev --gt bench/data/synth-v1/gt --md results/dev.md
  ```
  A full run costs about ₹15 and takes about 5 minutes. **Silent errors** (wrong bills marked `auto_ok`) must stay **0**; `bench/score.py` exits non-zero if they don't. A prompt change can be tried on a subset first (one template's bills) for about ₹2.
- **Changing only validation rules?** `tools/revalidate.py` re-applies them to saved results without calling the model, so you can iterate for free.
- **Results vary between runs.** OpenRouter routes to different hosts, and faint dot-matrix print doesn't read the same way twice: two runs of nearly identical code gave 95.7% and 93.8% of dev rows right. Compare two runs before believing a 1–2 point gain.
- **Unit tests** cover everything that doesn't need the model and run offline: `python -m unittest discover -s tests`.
- **Also check the real bills** after any change: `python -m invoice_scanner eval/samples/*.jpg --out results/real --workers 6 && python tools/score.py results/real`.
- **Grow the real evaluation set.** Synthetic bills are only as varied as their generator. Adding real bills with row-level ground truth is the most valuable next step ([docs/ROADMAP.md](docs/ROADMAP.md)).

---

## Known limitations

- **Multi-page invoices** are flagged (`continued_on_next_page`) but not merged. Each photo is processed on its own.
- **Dot-matrix sheets** are the weakest format (about 87% of rows exactly right). Their rows are tiny in a phone photo; misreads are caught and sent to review, which costs automation.
- **Tax lines (CGST/SGST/subtotal) are sometimes misread.** Correct GST bills then go to review because the total can't be proven.
- **Handwritten bills always go to review.** That's deliberate: digits in handwriting are the least reliable thing the model reads.
- **A bill photographed on top of another bill** shows two GSTINs and goes to review; the scanner can't tell which is the supplier's.
- **If only day and month are written,** the year is assumed to be the current one. That's wrong for a December bill scanned in January.
- **One photo, one bill.** A photo containing two bills isn't split.

[docs/ROADMAP.md](docs/ROADMAP.md) has the planned next steps: more real test bills, a supplier master, dot-matrix accuracy, multi-page merge, the ERP insert, and an HTTP service.

## Further docs

| Doc | What's in it |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline and modules in detail |
| [DECISIONS.md](docs/DECISIONS.md) | What was tried, what failed, and why the code is the way it is |
| [BENCHMARK.md](docs/BENCHMARK.md) | The synthetic benchmark: how it's built, metrics, results, how to use it |
| [EVALUATION.md](docs/EVALUATION.md) | The 15 real bills, model comparison |
| [COSTS.md](docs/COSTS.md) | Tokens and rupees per bill, provider choice, cost trims |
| [OUTPUT_FORMAT.md](docs/OUTPUT_FORMAT.md) | Every field in the result JSON |
| [ROADMAP.md](docs/ROADMAP.md) | What to build next |
