# Architecture

## Flow of one bill

`scan_bill(path)` in [`pipeline.py`](../invoice_scanner/pipeline.py) runs these steps in order:

| # | Step | Module | Model calls | What it does |
|---|---|---|---|---|
| 1 | Load | `pipeline` | 0 | Apply the EXIF rotation, shrink to at most 1600 px on the long side |
| 2 | Orientation | `ocr.orientation` | 0 | Turn the photo upright (Tesseract) |
| 3 | Deskew | `ocr.deskew` | 0 | Level small skews (projection profile, numpy) |
| 4 | Page text | `ocr.page_text` | 0 | Tesseract text of the page, plus the top 45% at 2x: evidence for checks |
| 5 | Header | `extract.read_header` | 1 | Supplier, invoice no., date as printed, totals and tax lines, amount in words, pen notes (JSON schema) |
| 6 | Header verify | `extract.verify_header` | 1 (rarely 2) | 2x crop of the top of the page: strike-through question, plus a second read of the invoice no., date and GSTINs |
| 7 | Line items | `extract.read_items` | 1–2 | Fixed-format rows; when in doubt, a second verbatim-table read, merged row by row |
| 8 | Long tables | `extract.zoom_if_needed` | 0 or 2–4 | Over 15 rows, or rows still failing: 2x strips stitched by serial number, merged again |
| 9 | Consensus | `validate.decide_invoice_number` / `decide_date` | 0 | Two reads must agree; OCR (whole tokens) breaks ties |
| 10 | Supplier GSTIN | `gstin.find_supplier_gstin` | 0–2 | Two sources must agree (OCR + model, or both model reads); 3x corner crops only if needed |
| 11 | Validate | `validate.validate` | 0 | Deterministic checks; any issue means `needs_review` |
| 12 | Save | `pipeline` | 0 | Optionally write `<stem>.json` and `<stem>_upright.jpg` |

- **Calls per bill:** a short, clean bill makes 3 model calls (header, verify, items); a long dot-matrix bill makes up to 8.
- **Cost:** on the 100-bill dev set, the average was about ₹0.16 and the median ₹0.12 (see [COSTS.md](COSTS.md)).

## Modules

### `config.py`
Reads settings from environment variables, loading `.env` from the working directory or repo root first. It holds:

- the company identity (name, GSTIN, aliases)
- model names and URLs
- `MAX_SIDE` and `GST_RATES`

### `llm.py`
`LLM(backend, model).chat(prompt, img, schema=None, max_tokens, step)` returns text, or a JSON string when a `schema` is given.

- **OpenRouter:** `temperature 0`, reasoning disabled, `response_format: json_schema` when a schema is given, and provider routing `sort: price` + `require_parameters` + fallbacks.
- **Retries:** with backoff on 429/5xx, network errors, and OpenRouter's 402 "in-flight budget" refusal for parallel requests. Any other 402 means out of credit and fails immediately.
- **Ollama:** same interface.
- **Usage:** every call appends `{step, prompt_tokens, completion_tokens, cost_usd, provider, finish_reason}` to `llm.usage`. `cost_usd` is the exact amount OpenRouter billed. `finish_reason == "length"` marks a reply cut off at `max_tokens`.

### `ocr.py`
Tesseract CLI and numpy helpers. These are free and run locally.

- **`orientation(img)`:** the clockwise rotation (0/90/180/270). It trusts OSD at confidence ≥ 2; otherwise it OCRs each candidate rotation and keeps the most confident one.
- **`skew_angle(img)` / `deskew(img)`:** finds the small rotation (±6°) at which row sums of the binarised page are most uneven, then rotates by it. Returns 0 when no angle is clearly better (handwriting, unruled pages).
- **`page_text(img)`:** the full page (psm 3) plus the top 45% at 2x (psm 11). Computed once per bill and used to confirm or contradict model reads.

### `extract.py`
Prompts, schemas and parsing for the model passes.

- **`header_prompt()` / `HEADER_SCHEMA`:** among other fields, `invoice_date_as_printed` (parsed in code), `receiver_bill_ref` (the "Bill-6xx" pen note), the summed tax lines, and `items_handwritten` (true when the quantities, rates or amounts are pen-written).
- **`verify_header()`:** the 2x top crop. It returns `struck_through`, `printed_number`, `replacement_number`, `invoice_date_as_printed` and `gstins`. If the number isn't in the crop, it retries on the full page.
- **`ITEMS_PROMPT` / `parse_items()`:**
  - The first read: `INK: pen|printed`, then rows `sl | description | hsn | qty | unit | rate | tax% | amount`, then `END`.
  - **`final_block()`** keeps only the answer when the model thinks aloud before it.
  - The parser handles markdown pipes, missing serials, blank template rows, `?` for unreadable digits (row marked `unreadable`), "1892/-" and "Rs." forms, quantities like "9,000" meaning 9.000 (`decimal_qty`), and loops (3 identical rows, or a repeated block).
- **`TABLE_PROMPT` / `parse_table()` / `map_columns()`:**
  - The second read: the table transcribed verbatim with its headings.
  - `heading_role()` maps headings to sl, desc, hsn, qty (Billed over Shipped), unit, rate (not MRP, GST-inclusive or tax-rate columns), amount (the last amount-like column that isn't tax, taxable or discount), Ps (joined to Rs) and tax rate (CGST% + SGST% summed; "365.00 (5%)" cells understood).
- **`read_items()`:**
  - Runs the second read only when `needs_second_read()`: any row failing `row_ok`, a total that doesn't reconcile, more than 12 rows, or a first read that was cut off or malformed.
  - **`merge_reads()`:** a passing row keeps its value; a failing row takes the other read's passing value; two passing reads that disagree become a **conflict** and send the bill to review; the read with more passing rows leads when the first is mostly broken.
  - **`pair_reads()`:** aligns the two reads by serial number, or in order by description similarity.
- **`zoom_if_needed()` / `read_items_zoomed()`:**
  - The third read for tables of more than 15 rows, or with rows still failing.
  - Overlapping 2x strips (`strips()`), stitched by serial number.
  - A dissenting zoomed row can't overrule a row two reads already agreed on.

### `gstin.py`
- **`gstin_ok(g)`:** checks the format, the state code (01–38, 97, 99) and the mod-36 check character.
- **`repair_gstin(chunk)`:** fixes OCR look-alikes per position, including 2 or 7 read in place of the fixed `Z`.
- **`gstin_candidates(text)`:** finds checksum-valid GSTINs. A match may span at most 2 adjacent words and need at most 2 repairs.
- **`find_supplier_gstin(img, header_guess, verify_gstins, ocr_text, llm)`** returns `(gstin, source, issue)`, with source:
  - `ocr+model` or `model x2`: two sources agree.
  - `ocr`: a single OCR candidate.
  - `crop`: confirmed on a 3x corner crop.
  - `unverified`: one model read only, flagged.
  - `none`: nothing found.

  Two different valid GSTINs on the photo (another bill underneath) always raise the "several GSTINs" issue.

### `validate.py`
Deterministic rules. `validate(d, checks)` returns human-readable issues; an empty list means `auto_ok`. `checks` are the consensus issues decided in the pipeline.

| Check | Function | Issue text starts with |
|---|---|---|
| qty × rate (× own GST factor) = amount, rounding-level tolerance only | `row_ok` | `line N (...)`, with the implied rate as a hint |
| Unreadable digit or missing number in a row | parser / `validate` | `line N (...): a digit was unreadable` / `missing qty/rate/amount` |
| Rows (+ tax, printed or implied by row rates) (+ round off) = grand total, to the paisa | `sum_check` | `line items sum to` |
| Printed serial numbers skip or repeat (printed bills) | `serial_problem` | `row numbers jump` |
| Two reads of a row disagree | pipeline | `row(s) N read differently in two passes` |
| Page continues / no total | `validate` | `invoice continues on another page` |
| Words vs total, when the arithmetic can't confirm it | `words_to_number` | `total ... disagrees with amount in words` |
| Invoice number: reads disagree / single unconfirmed read / pen note | `decide_invoice_number` | `invoice number unclear` / `not confirmed` / `looks like the receiver's pen note` |
| Date: reads disagree / unconfirmed / contradicted by OCR / implausible / outside the invoice no.'s FY | `decide_date` | `invoice date ...` |
| Struck-through invoice number, date or total | verify + header | `invoice number/date/total corrected by hand` |
| GSTIN missing / unconfirmed / several on the photo | `find_supplier_gstin` | `supplier GSTIN ...` / `several GSTINs on the photo` |
| Handwritten figures | header + `INK:` | `handwritten bill - confirm values` |

## Where to change things

| You want to... | Change |
|---|---|
| Extract a new header field | `HEADER_SCHEMA` and `header_prompt()` in `extract.py`, then map it in `pipeline.py` |
| Add a safety check | `validate.py`, plus a test in `tests/test_validate.py`; then run the benchmark |
| Change how the item table is read | `extract.py`; always A/B it on the benchmark (see [BENCHMARK.md](BENCHMARK.md)) |
| Try another model | `--model <openrouter id>` or `OPENROUTER_MODEL`; then run the benchmark |
| Support another buyer company | `COMPANY_*` in `.env` |
| Look up GSTINs differently (e.g. a supplier master) | `gstin.find_supplier_gstin` |
