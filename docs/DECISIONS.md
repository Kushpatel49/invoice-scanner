# Design decisions

Why the code is the way it is. Each entry is something that was tried on the real sample bills, what happened, and what was done about it. Read this before "simplifying" a step; most of the simple versions were tried first.

## Model choice

**Hosted Nemotron VL (OpenRouter), with local Qwen3-VL 8B kept as a fallback.**

| Model | Line items right | Time per bill | Notes |
|---|---|---|---|
| `qwen3-vl:8b-instruct` (local Ollama, M4 16 GB) | 10 / 15 | 35–110 s | Misread digits under stamps (4500 read as 1500); loops on long tables |
| `qwen/qwen3-vl-30b-a3b-instruct` (OpenRouter) | 9 / 13 * | 24–114 s | Invented rows on egg/mushroom bills; false strike-through flags |
| `nvidia/nemotron-3.5-super-vl` (OpenRouter) | **15 / 15** | 7–47 s | Read rates under GOODS RECEIVED stamps correctly |

\* That run was stopped after 13 bills.

- **PaddleOCR was considered** but can't run inside Ollama (it isn't a GGUF/LLM model), and plain OCR still needs something to understand the table structure. A vision LLM does both.
- **The plain `qwen3-vl:8b` Ollama tag** ignores `think: false` and reasons for hundreds of tokens before answering (3–6 minutes per bill). Use the `-instruct` tag.

## Nemotron reasoning off

With reasoning enabled (even `effort: low`), Nemotron used its whole 6,000-token budget thinking and returned no answer. With it disabled, it answered in about 3 s and was just as accurate.

## Provider routing: `sort: price` + `require_parameters`

OpenRouter serves Nemotron from 7 hosts. Crusoe is the cheapest (input $0.10/M vs $0.15–0.25/M), and it is also the **only full-precision (bf16) host**; the others run 4-bit versions. Io Net and BaseTen don't support `response_format`, which the header and strike-through calls depend on. So requests are routed cheapest-first, hosts that would ignore the schema are skipped, and the next host is used if Crusoe is down. This cut cost by about 25% with no accuracy loss.

## Separate requests instead of one

- **Header and line items are split.** Asking for everything as one JSON made the local model loop until the token limit on a 48-row bill, leaving the JSON unterminated. Pipe-separated rows use about 4x fewer tokens than JSON, and a model stuck repeating a row is easy to detect (`parse_items` stops after the same row appears 3 times).
- **The strike-through check is its own request.** As a field inside the header schema (`header_corrected`), the model missed inv05's crossed-out invoice number every time. Asked on its own, it caught it 4 times out of 4, with no false alarms on 10 clean bills. It also had to be told to ignore the receiver's "Bill-641" notes (otherwise inv03 was a false positive). And it must be asked to *report the printed and replacement numbers*: with only a bare yes/no field it answered "no" every time.
- **`handwritten_notes` has `maxItems: 8`.** Without the cap, the model once repeated "quality issue return" until the token limit.

## Orientation via Tesseract, not the model

Asked "which way is the text facing?", the vision model answered "up" for every photo; a second wording gave contradictory answers. Tesseract OSD is right when confident (≥ 2) but wrong or near-random below that (inv01 got 270° when the answer was 90°, at confidence 0.63). The fallback that works: OCR each candidate rotation and pick the one with the most confident words. It's right on all 15 samples, by margins of 3–10x.

## GSTIN: checksum first, never trust the model's assignment

- The model often put **our own GSTIN** in the supplier field, even when told not to. So our GSTIN is excluded in code, not just in the prompt.
- GSTINs are printed tiny. Full-page reads missed several; **upscaled letterhead crops** (2x top band, then 3x corners) found them. inv12 is only found by the third crop.
- **The checksum is the safety net.** In testing it caught a V read as Y and an invented GSTIN.
- **OCR look-alike repair** (S→5, O→0 by position) recovers real GSTINs, but too loose a matcher invents them: unlimited repairs plus matching across any number of words gave about 1 false GSTIN per 6 pages of random text. Limits of ≤ 2 repairs, ≤ 2 adjacent words and a valid state code bring that to about 1 per 230 pages.
- **The free full-page Tesseract read is tried before paid crops.** Same checksum safety, and it saves a model call on most printed GST bills.

## Self-correction round for line items

When rows fail qty × rate = amount, or don't add up to the total, the specific problems are sent back with the image and the model re-reads once. The version with fewer problems is kept, so the re-read can't make things worse. It cost ₹0.02–0.04 when triggered (5 of 15 bills).

## Validation rules worth knowing

- **Line amounts may be tax-inclusive.** R K Mercantile prints 20 × 365 = 7,665, which includes 5% GST, so each row is checked against 0/3/5/12/18/28%.
- **Use the rate, not the MRP.** SH Foods prints both; the prompt says to use the price paid, not MRP (an early run used MRP 149 instead of 102.17).
- **Total vs amount in words** caught a digit swap (26,676 vs 26,766) that the arithmetic checks alone would have attributed to the line items.
- **Handwritten bills always go to review.** That's deliberate: digit accuracy on handwriting is the weakest part (the model read "fifty nine" as 1839 instead of 1859).
- **Blank pre-printed rows** (egg and mushroom bills list all products, with only some filled in) are dropped by the parser. Before that they showed up as items with no values.

## Cost trims rejected (for now)

These would save money but risk accuracy on unusual bills:

- **Skip GSTIN crops when the model says there's no GSTIN.** inv12's GSTIN is only found by the third crop, and a missed GSTIN loses GST input credit.
- **Merge the header and items requests.** Risk of loops on long tables.
- **Fold the strike-through check into the header.** Measured: it missed every time.
- **Send smaller images.** Handwriting and tiny print degrade first.

The better route is a supplier master; see [ROADMAP.md](ROADMAP.md).
