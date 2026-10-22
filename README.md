# Invoice Scanner

Turn a phone photo of a purchase bill into validated, structured data that the ERP can insert, so staff can "scan and insert" bills instead of typing them in.

It handles the bills a store actually receives: printed GST tax invoices, dot-matrix bills, pink carbon copies, handwritten cash bills, photos taken sideways, and bills with a GOODS RECEIVED rubber stamp over the line items.

Each bill comes out in one of two states:

- **`auto_ok`**: every check passed. Safe to insert into the ERP.
- **`needs_review`**: something didn't add up. The result lists exactly what (for example `total 26676 disagrees with amount in words (26766)`), so a person confirms or fixes it before it's posted.

The design goal is that **a wrong bill is never marked `auto_ok`**. On the 15-bill evaluation set that number is 0.

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

All figures are measured on the 15 real bills in [`eval/`](eval/) with the default model, `nvidia/nemotron-3.5-super-vl` via OpenRouter.

| | Result |
|---|---|
| Line items: every row read, right count | 15 / 15 bills |
| Invoice date | 15 / 15 |
| Supplier GSTIN | 14 / 15 ¹ |
| Invoice number | 13 / 15 ² |
| Grand total | 13 / 15 ³ |
| **Wrong bills marked `auto_ok`** | **0** |
| Bills `auto_ok` / `needs_review` | 5 / 10 |
| Time per bill | 7–47 s, usually about 10–20 s |
| Cost per bill | **₹0.10 on average** (₹0.06–0.21) |

¹ The miss is a GSTIN printed on a *different* bill lying underneath in the photo.
² One is a printed number struck out and rewritten by hand; one is tiny print. Both are flagged for review.
³ One digit swap and one handwritten "less 2%" discount. Both are flagged for review.

Every miss above lands in `needs_review` with the reason, so none of them would reach the ERP without a person checking it. See [docs/EVALUATION.md](docs/EVALUATION.md) for per-bill detail and [docs/COSTS.md](docs/COSTS.md) for the cost breakdown.

---

## How it works

```
photo ──► 1. orientation ──► 2. header + totals ──► 3. line items ──► 4. supplier GSTIN ──► 5. strike-through ──► 6. validation ──► JSON
          (Tesseract,         (vision model,         (vision model,      (Tesseract free;      check                (pure Python)       auto_ok /
           free, local)        JSON schema)           pipe rows +          model on zoomed      (vision model)                           needs_review
                                                      1 self-check)        crops if needed)
```

1. **Orientation.** Tesseract finds how the photo is rotated (phones often save bills sideways) and turns it upright. This runs locally and costs nothing.
2. **Header and totals.** The vision model fills a small JSON schema: supplier, invoice number and date, totals, amount in words, pen notes.
3. **Line items.** A separate request returns the item table as compact `description | hsn | qty | unit | rate | tax% | amount` rows. If the arithmetic fails (qty × rate ≠ amount, or the rows don't add up to the total), the model is shown its own errors and re-reads once.
4. **Supplier GSTIN.** The model often mixes up whose GSTIN is whose, so GSTINs are only accepted if they pass the official checksum, and our own GSTIN is never taken as the supplier's. A free Tesseract read is tried first; zoomed crops of the letterhead are sent to the model only if that fails.
5. **Strike-through check.** A focused yes/no question: was the printed invoice number crossed out and rewritten by hand?
6. **Validation.** Plain Python checks: row arithmetic, sum of rows vs total, total vs amount in words, GSTIN checksum, date sanity, handwriting, multi-page bills. Any failure means `needs_review`, with the reason.

Each design choice exists because a simpler version failed on real bills; [docs/DECISIONS.md](docs/DECISIONS.md) records what was tried and why. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the module-level detail.

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
python -m unittest discover -s tests     # 30 offline tests, including orientation on all sample bills
```

---

## Usage

### Command line

```bash
python -m invoice_scanner path/to/bills/*.jpg --out results
```

The `invoice-scanner` command does the same once you've run `pip install -e .`.

Sample output:

```
model=openrouter:nvidia/nemotron-3.5-super-vl
inv06.jpg: auto_ok        1 lines  total=7665.0  gstin=32AGVPR6347Q2ZA  7.4s  rot=90  calls=4 tok=6518+257 $0.00075
inv12.jpg: needs_review  17 lines  total=None  gstin=32AAPCA0115L1ZX  21.7s  rot=0  calls=5 tok=8182+927 $0.00119
    - invoice continues on another page - attach remaining pages

5 ready to post, 10 need review, 0 errors; model cost $0.0170. Results in results/
```

For each photo, `results/` gets `<name>.json` (the data) and `<name>_upright.jpg` (the rotated photo, for the review screen).

Options:

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
python tools/score.py results                     # accuracy against eval/ground_truth.json
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
  extract.py              prompts, schemas, parsing, item self-check, strike-through check
  gstin.py                GSTIN checksum, OCR look-alike repair, supplier GSTIN lookup
  validate.py             deterministic checks -> auto_ok / needs_review
  ocr.py                  Tesseract: orientation, raw text
  llm.py                  OpenRouter / Ollama client with per-call cost tracking
  config.py               settings (env / .env)
  cli.py                  command line
tools/                    score.py, make_review.py, cost_report.py
tests/                    offline unit tests (no API calls)
eval/                     15 real sample bills + hand-checked ground truth
docs/                     architecture, decisions, evaluation, costs, output format, roadmap
```

---

## Development

- **Before changing a prompt or step:** run the evaluation and compare with the numbers above:
  ```bash
  python -m invoice_scanner eval/samples/*.jpg --out results && python tools/score.py results
  ```
  A full run costs about ₹1.50 and takes 3–5 minutes. The last line of `score.py` (wrong bills marked `auto_ok`) must stay **0**. `score.py` also exits non-zero if it isn't.
- **Run results vary slightly.** OpenRouter can route a request to different hosts, and messy handwriting doesn't always read the same way twice. Compare a change across a couple of runs before concluding it helped.
- **Unit tests** cover everything that doesn't need the model and run offline: `python -m unittest discover -s tests`.
- **Grow the evaluation set.** 15 bills is enough to show the approach works, not to prove a change is safe across every kind of bill. Adding real bills (handwritten, crumpled, multi-page, every regular supplier) is the most valuable thing to do next. See [eval/README.md](eval/README.md).

---

## Known limitations

- **Multi-page invoices** are flagged (`continued_on_next_page`) but not merged. Each photo is processed on its own.
- **The tax breakdown** (CGST/SGST/subtotal) is often returned empty even when it's printed. Validation relies on the grand total and line amounts, so this doesn't cause wrong `auto_ok`s, but don't rely on these fields yet.
- **Handwritten bills always go to review.** That's deliberate: digits in handwriting are the least reliable thing the model reads.
- **A bill photographed on top of another bill** can pick up the GSTIN of the bill underneath.
- **If only day and month are written**, the year is assumed to be the current one. That's wrong for a December bill scanned in January.
- **One photo, one bill.** A photo containing two bills isn't split.

[docs/ROADMAP.md](docs/ROADMAP.md) has the planned next steps: a supplier master, multi-page merge, the ERP insert, and an HTTP service.

## Further docs

| Doc | What's in it |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline and modules in detail |
| [DECISIONS.md](docs/DECISIONS.md) | What was tried, what failed, and why the code is the way it is |
| [EVALUATION.md](docs/EVALUATION.md) | Test set, scoring, model comparison |
| [COSTS.md](docs/COSTS.md) | Tokens and rupees per bill, provider choice, cost trims |
| [OUTPUT_FORMAT.md](docs/OUTPUT_FORMAT.md) | Every field in the result JSON |
| [ROADMAP.md](docs/ROADMAP.md) | What to build next |
