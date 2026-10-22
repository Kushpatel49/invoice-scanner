# Architecture

## Flow of one bill

`scan_bill(path)` in [`pipeline.py`](../invoice_scanner/pipeline.py) runs these steps in order:

| # | Step | Module | Model calls | What it does |
|---|---|---|---|---|
| 1 | Load | `pipeline` | 0 | Apply the EXIF rotation, shrink to at most 1600 px on the long side |
| 2 | Orientation | `ocr.orientation` | 0 | Turn the photo upright (Tesseract) |
| 3 | Header | `extract.read_header` | 1 | Supplier, invoice no., date, totals, amount in words, pen notes (JSON schema) |
| 4 | Line items | `extract.read_items` | 1–2 | Item rows as pipe-separated text; one self-correcting re-read if the arithmetic fails |
| 5 | Supplier GSTIN | `gstin.find_supplier_gstin` | 0–3 | Checksum-verified GSTIN that isn't ours; free OCR first, then zoomed letterhead crops |
| 6 | Strike-through | `extract.invoice_no_struck` | 1 | Was the printed invoice number crossed out and rewritten by hand? |
| 7 | Validate | `validate.validate` | 0 | Deterministic checks; any issue means `needs_review` |
| 8 | Save | `pipeline` | 0 | Optionally write `<stem>.json` and `<stem>_upright.jpg` |

A typical bill makes 4–7 model calls. Each call sends the image plus a prompt, about 1,300–2,000 input tokens.

## Modules

### `config.py`
Reads settings from environment variables, loading `.env` from the working directory or repo root first. It holds the company identity (name, GSTIN, aliases), model names and URLs, `MAX_SIDE` and `GST_RATES`. Nothing else in the package reads the environment except the OpenRouter key lookup in `llm.py`.

### `llm.py`
`LLM(backend, model)` has a single method that matters: `chat(prompt, img, schema=None, max_tokens, step)`. It returns text, or a JSON string when a `schema` is given.

- **OpenRouter.** Image sent as a base64 data URL. Settings: `temperature 0`, reasoning disabled, `response_format: json_schema` when a schema is given. Provider routing is `sort: price` + `require_parameters` + fallbacks. It retries with backoff on 429/5xx and network errors.
- **Ollama.** Same interface, against a local server (`format` = schema).
- **Usage.** Every call appends `{step, prompt_tokens, completion_tokens, cost_usd, provider}` to `llm.usage`. The pipeline clears it per bill and stores `usage_summary()` in `_meta.usage`. `cost_usd` is the exact amount OpenRouter billed, taken from its response.

### `ocr.py`
Thin wrapper around the `tesseract` CLI.
- `orientation(img)` returns the clockwise rotation (0/90/180/270). It trusts Tesseract OSD when its confidence is ≥ 2. Otherwise it OCRs each candidate rotation and picks the one with the most confidently read words. A landscape photo is only tried at 90/270.

### `extract.py`
Prompts, schemas and parsing for the model passes.
- `header_prompt()` / `HEADER_SCHEMA`: built at call time so company settings and the current year apply.
- `ITEMS_PROMPT` and `parse_items()`: rows are `description | hsn | qty | unit | rate | tax% | amount`, ending with `END`. The parser strips serial numbers and skips blank pre-printed template rows (no qty and no amount). It also stops if the same row repeats more than twice, which means the model is stuck repeating itself.
- `item_problems()` / `read_items()`: the self-check. If any row fails qty × rate = amount (pre-tax or tax-inclusive at a standard GST rate), or the rows don't sum to the total, the problems are sent back to the model with a request to re-read. The version with fewer problems is kept.
- `invoice_no_struck()`: the standalone strike-through question.

### `gstin.py`
- `gstin_ok(g)`: format, state code (01–38, 97, 99) and the mod-36 check character.
- `repair_gstin(chunk)`: fixes OCR look-alikes per position (a digit position turns `S` into `5`, a letter position turns `0` into `O`, and so on).
- `gstin_candidates(text)`: scans text for checksum-valid GSTINs. A match may span at most 2 adjacent words and need at most 2 repairs; these limits keep false matches from random OCR noise to about 1 per 230 pages.
- `find_supplier_gstin(img, model_guess, llm)` returns `(gstin, source)`:
  1. `header/ocr`: a valid GSTIN that isn't ours, from the header pass or a full-page Tesseract read (free).
  2. `crop`: the model lists GSTINs on upscaled letterhead crops (top 45% at 2x, then the top-left and top-right corners at 3x); stops at the first valid one.
  3. `unverified`: the model's guess (`gstin_verified: false`), or `None`.

### `validate.py`
`validate(d)` returns a list of human-readable issues; an empty list means `auto_ok`. Checks:

| Check | Issue text starts with |
|---|---|
| No rows extracted | `no line items extracted` |
| qty × rate ≠ amount (pre-tax or tax-inclusive at 0/3/5/12/18/28%; tolerance max(₹1, 1%)) | `line N (...)`, with the implied rate as a hint |
| Rows don't sum to the grand total (alone, plus tax, or plus round-off) | `line items sum to` |
| Page continues, or no total on the page | `invoice continues on another page` |
| Grand total ≠ amount in words (exact to ₹1) | `total ... disagrees with amount in words` |
| Invoice number/date/total corrected by hand | `invoice number/date/total corrected by hand` |
| Subtotal + tax ≠ total | `subtotal ... + tax` |
| No supplier GSTIN / fails checksum | `supplier GSTIN not found` / `... fails checksum` |
| Missing invoice number | `invoice number missing` |
| Date unparseable or outside 2020 to next year | `invoice date unreadable` / `implausible date` |
| Line items handwritten | `handwritten bill - confirm values` |

`words_to_number()` handles Indian number words (lakh, crore) and drops paise.

## Where to change things

| You want to... | Change |
|---|---|
| Extract a new header field | Add it to `HEADER_SCHEMA` and `header_prompt()` in `extract.py`, then map it in `pipeline.py` |
| Add a safety check | `validate.py`, plus a test in `tests/test_validate.py` |
| Try another model | `--model <openrouter id>`, or `OPENROUTER_MODEL` in `.env`; then run the evaluation |
| Support another buyer company | `COMPANY_*` in `.env` |
| Look up GSTINs differently (e.g. a supplier master) | `gstin.find_supplier_gstin` |
