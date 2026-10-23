# Design decisions

Why the code is the way it is. Each entry records something that was tried, what happened, and what was done about it. Read this before "simplifying" a step; most of the simple versions were tried first.

Two kinds of evidence are behind these entries:

- **The 15 real bills** in `eval/`, used during the first build.
- **The 100-bill synthetic dev set** in `bench/` (see [BENCHMARK.md](BENCHMARK.md)), used from the benchmark onwards. A diagnosis pass looked at every failing bill's photo, zoomed in on each wrong value, and confirmed that all 257 errors were on values a person could read.

## Model choice

**Hosted Nemotron VL (OpenRouter), with local Qwen3-VL 8B kept as a fallback.**

| Model | Line items right (15 real bills) | Time per bill | Notes |
|---|---|---|---|
| `qwen3-vl:8b-instruct` (local Ollama, M4 16 GB) | 10 / 15 | 35–110 s | Misread digits under stamps (4500 read as 1500); loops on long tables |
| `qwen/qwen3-vl-30b-a3b-instruct` (OpenRouter) | 9 / 13 * | 24–114 s | Invented rows on egg/mushroom bills; false strike-through flags |
| `nvidia/nemotron-3.5-super-vl` (OpenRouter) | **15 / 15** | 7–47 s | Read rates under GOODS RECEIVED stamps correctly |

\* That run was stopped after 13 bills.

- **PaddleOCR was considered,** but it can't run inside Ollama (it isn't a GGUF/LLM model), and plain OCR still needs something to understand the table structure. A vision LLM does both.
- **The plain `qwen3-vl:8b` Ollama tag** ignores `think: false` and reasons for hundreds of tokens before answering (3–6 minutes per bill). Use the `-instruct` tag.

## Nemotron reasoning off, and it still thinks aloud

- **With reasoning enabled** (even `effort: low`), Nemotron used its whole 6,000-token budget thinking and returned no answer. With reasoning disabled, it answers in about 3 s and is just as accurate.
- **It still sometimes thinks aloud in the answer itself.** Even with reasoning off, on long or rule-heavy prompts it writes "The user wants me to…", an analysis, and draft tables, then the real answer. Parsing every draft duplicated rows: one bill came back with 39 rows for 13. So `extract.final_block()` keeps only the answer, from the last `INK:` line, or else the last unbroken run of table rows.
- **When the thinking runs past the token limit** (8 of 100 dev bills), the first read is marked truncated, and the clean second read becomes the primary (see below).

## Provider routing: `sort: price` + `require_parameters`

OpenRouter serves Nemotron from 7 hosts:

- **Crusoe is the cheapest,** at $0.10/M input against $0.15–0.25/M elsewhere.
- **Crusoe is also the only full-precision (bf16) host;** the others run 4-bit versions.
- **Io Net and BaseTen don't support `response_format`,** which the header and verify calls depend on.

So requests go cheapest-first, hosts that would ignore the schema are skipped, and the next host is used if Crusoe is down. This cut cost by about 25% with no accuracy loss.

## Separate requests instead of one

- **The header and line items are separate requests.** Asking for everything as one JSON made the local model loop until the token limit on a 48-row bill, leaving the JSON unterminated. Pipe-separated rows use about 4x fewer tokens than JSON, and loops are easy to cut: a row repeated 3 times, or a whole block repeated, is dropped.
- **The strike-through question is its own request.** As a field inside the header schema, the model missed inv05's crossed-out invoice number every time; asked on its own, it caught it 4 times out of 4. Three things matter about this request:
  - It tells the model to ignore the receiver's "Bill-641" notes (otherwise inv03 is a false positive).
  - It asks the model to *report the printed and replacement numbers*. With a bare yes/no field, the model answered "no" every time.
  - It runs on a **2x crop of the top 45% of the page** and also returns the date as printed and every GSTIN. That makes it an independent second read of the header (see "Header consensus").
- **`handwritten_notes` has `maxItems: 8`.** Without the cap, the model once repeated "quality issue return" until the token limit.

## Orientation and skew via Tesseract and numpy, not the model

- **Orientation:**
  - Asked which way the text faces, the vision model answered "up" for every photo; a second wording gave contradictory answers.
  - Tesseract OSD is right when confident (≥ 2), but wrong or near-random below that.
  - What works is OCRing each candidate rotation and keeping the one with the most confident words. It's right on all 15 real bills and all 100 dev bills.
- **Skew:** photos are often 2–5° off level. On a dense table the model then attaches a description to the next row's numbers, and every row still multiplies out, so no arithmetic check notices.
  - `ocr.deskew()` levels the page with a projection profile: it finds the small rotation at which row ink sums are most uneven, which takes 0.03 s per photo.
  - It finds the right direction on 28 of the 29 dev photos skewed 2° or more.
  - Deskewing fixed whole dot-matrix bills: syn091 went from 15 to 25 of 26 rows right, syn086 from 22 to 27 of 27.

## Exact arithmetic, no percentage slack

The first validator accepted qty × rate = amount within max(₹1, 1%). On the benchmark that let through:

- a ₹10 misread on a ₹6,459 row
- a rate of 271.9 instead of 271
- a row with a dropped decimal

On the real Almova bill (inv09) it let 1,292.04 through for a printed 1,295.24.

- **Now (`validate.row_ok`):** the tolerance covers only how bills round, scaled by the GST factor:
  - rate rounded to 2 dp (0.005 per unit)
  - qty rounded to 3 dp
  - 1 paisa
  - for whole-rupee amounts, rounding to the rupee
- **The GST factor:** may only be 1 or the row's own rate (a printed CGST half-rate of 2.5% means 5%). All slabs are tried only when no rate is printed.
- **Effect:** 0 of 975 true rows fail the rule, and 6 of the 17 baseline silent errors are caught.
- **Totals (`validate.sum_check`):** rows (+ printed tax, or tax implied by each row's rate) (+ round off) must equal the grand total to within paise. A bill that rounds to the rupee without printing it may differ by up to ₹1, but then a printed subtotal must confirm the rows exactly. If the printed tax lines are misread but the rows equal the subtotal exactly and the amount in words confirms the total, the bill passes, because two independent printed numbers agree.
- **Tax implied from row rates:** the model often returns the header's tax lines as null. Before this, correct GST bills went to review because the total couldn't be reconciled (8 of 11 unnecessary reviews).

## Header consensus: invoice number and date

The invoice number and date were never checked. Six silent errors were misread invoice numbers (TI-84340 read as TI-8430, 180055 as 18055), and two were misread dates. Now:

- **Two independent reads,** the full-page header and the zoomed header crop, must agree (`validate.decide_invoice_number`, `decide_date`). When they disagree, OCR may settle it, within narrow limits:
  - **Whole tokens only.** On syn010 the wrong read "9868" appeared inside a phone number.
  - **Small slips only** (an edit distance of 2 or less). A handwritten replacement against the struck-out printed number differs by more, and OCR can only see the printed one, so it would always pick wrong (syn082).
  - **Never the shorter of two nested reads.** On the real R K Mercantile bill, "26-27/1064" wraps onto two lines, and OCR had "confirmed" the half read "27/1064".

  Anything else goes to review with both readings. The **zoomed read is the value shown**, because on the held-out set it was the right one in 14 of 18 disagreements; the full-page read tends to grab a nearby field.
- **Dates are parsed day-first in code** from the text as printed (`parse_date_dayfirst`). The model's own ISO conversion swapped days and months and invented years (2026-01-28 for 31/08/26). Implausible dates, such as next year's, lose a tie-break. A date outside the financial year in the invoice number ("26-27/…") is flagged.
- **The receiver's pen note** ("BIL-604") was returned as the invoice number on 3 bills. Notes now have their own field (`receiver_bill_ref`), and a number that looks like one, or matches a note's digits, is rejected.
- **A bill-book series prefix** ("26-27 C 5207") is split off into `invoice_series`. The serial is the invoice number, which matches how the store records them.

## Two independent reads of the item table

- **First read:** the fixed 8-field format `sl | description | hsn | qty | unit | rate | tax% | amount`, telling the model to copy numbers exactly and never calculate them. On the 24 hardest dev bills this beat the baseline prompt, at 77.6% of rows exactly right against 71.5%.
- **Second read, only when there's reason to doubt the first:**
  - Triggers: any row fails `row_ok`, the total doesn't reconcile, the table has more than 12 rows, or the first read was cut off or malformed.
  - Method: the table is transcribed **verbatim with its own headings**, and the columns are mapped in code (`extract.map_columns`).
  - On its own it's weaker, because it drifts into prose more often (63% of rows on the same 24 bills). But it is fairly independent of the first read, because the prompt is shaped differently.
- **The merge (`extract.merge_reads`):**
  - A row that passes the arithmetic keeps its first value.
  - A failing row takes the other read's value if that one passes.
  - **Two self-consistent reads that disagree are a conflict, and the bill goes to review.** That is the only check that sees a wrong row that still multiplies out (76 of the 132 wrong rows in the baseline).
- **Simulated on the 24 hard bills:** rows went from 77.6% to 81.1%, with 10 such rows caught and 2 false alarms.
- **The second read is never told the bill total or what the first read said.** The old "fix these problems" re-read was told the total and once invented a table that added up exactly; that silent error was syn004.
- **Third, zoomed read for long tables:** tables of more than 15 rows, or with rows still failing, are cut into overlapping horizontal strips at 2x and read again (`read_items_zoomed`). The strips are stitched together by printed serial number and merged the same way. A single dissenting zoomed read can't overrule a row two earlier reads agreed on. On the 12 dot-matrix dev bills, deskew plus zoom took rows from 83.2% to 92.1%.

## GSTIN: checksum first, two sources must agree

- **Our own GSTIN is excluded in code.** The model often put it in the supplier field, even when told not to.
- **GSTINs are printed tiny.** Upscaled letterhead crops (the 2x header-verify crop, then 3x corners) find what full-page reads miss.
- **The checksum alone isn't enough.** A garbled model read passes the mod-36 checksum about 1 time in 36, and one did (syn042). So a GSTIN is trusted only when two sources agree: OCR and a model read, or both model reads (`gstin.find_supplier_gstin`). A single model read is reported as "not confirmed".
- **Another bill underneath the photo can show its own GSTIN.** Both the model and OCR read it on 2 dev bills. **When two different GSTINs are visible, the bill goes to review.** Nothing in the photo says which is the supplier's.
- **"Different" is decided by edit distance, not the checksum.** On held-out syn035, the real supplier's GSTIN was misread by one character and failed the checksum, so only the underlay's valid GSTIN was "seen". Now any GSTIN-shaped string counts. Measured, garbled reads of the same GSTIN were 2–6 edits apart and genuinely different GSTINs 7 or more, so 7 is the threshold.
- **OCR look-alike repair is limited.** Repair (S→5, O→0, and 2 or 7 → Z by position) is capped at ≤ 2 repairs, ≤ 2 adjacent words and a valid state code. Looser matching invented about 1 GSTIN per 6 pages of random text; this gives about 1 per 230.

## Indian number forms

- **"1892/-"** (rupees only) and "Rs.230/-" are parsed as 1892 and 230. When the "copy exactly" prompt made the model keep the "/-", 10% of handwritten amounts were lost until the parser learned it.
- **"9,000" printed as 9.000 kg** is read as 9.000, but only when that reading, and not 9000, makes qty × rate = amount.
- **Amounts in words** are matched fuzzily ("Eightteen" means eighteen). A garbled number word ("Nine Hundred Twe") makes the words check skip rather than contradict. The words only arbitrate when the arithmetic can't confirm the total; all 10 words-vs-total disagreements in the baseline came with a correct total.

## Handwritten bills always go to review

That's deliberate: digit accuracy on handwriting is the weakest part. A bill counts as handwritten if the header says its quantities, rates or amounts are pen-written, or if the item read's `INK:` line says pen. The `INK:` line alone flips between runs on printed bills (syn017), so both signals are kept in `_meta.evidence` to tune the rule on more real bills.

## Validation rules worth knowing

- **Line amounts may be tax-inclusive.** R K Mercantile prints 20 × 365 = 7,665, which includes 5% GST.
- **Use the rate, not the MRP.** SH Foods prints both; an early run used MRP 149 instead of 102.17.
- **Printed serial numbers must run 1, 2, 3…** on printed bills. Bill books legitimately skip unfilled pre-printed rows, so handwritten bills are exempt.
- **Blank pre-printed rows** (egg and mushroom bill books) are dropped by the parser.

## Cost trims rejected (for now)

These would save money but risk accuracy on unusual bills:

- **Skip GSTIN crops when the model says there's no GSTIN.** inv12's GSTIN is only found by the third crop, and a missed GSTIN loses GST input credit.
- **Merge the header and items requests.** Risk of loops on long tables.
- **Fold the strike-through check into the header.** Measured: it missed every time.
- **Send smaller images.** Handwriting and tiny print degrade first.

The extra reads added in the benchmark round cost about ₹0.05 per bill (₹0.11 → ₹0.16). They are gated, so short clean bills don't pay for them. The better route to lower cost is a supplier master; see [ROADMAP.md](ROADMAP.md).
