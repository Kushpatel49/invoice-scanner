# Evaluation

## The test set

[`eval/samples/`](../eval/samples/) holds 15 real purchase bills received at the Kakkanad store (29–31 Aug 2026), photographed on a phone as staff would. [`eval/ground_truth.json`](../eval/ground_truth.json) has the hand-checked answers.

| Bill | Supplier | What makes it hard |
|---|---|---|
| inv01 | Green Leaf | 48 dot-matrix rows, rotated, page 1 of several (no total) |
| inv02 | Nutri Leaves | 26 rows; a GSTIN from the bill underneath shows at the edge |
| inv03 | Muralya Dairy | Dense GST table, rotated, small print |
| inv04 | NKA Fruits | No GSTIN on the bill, stamp over the table |
| inv05 | Arayacherril Varkey & Sons | Printed invoice no. struck out and rewritten by hand; handwritten amounts |
| inv06 | R K Mercantile | Tax-inclusive line amount, stamp over the text |
| inv07 | SH Foods | 6 near-identical rows; MRP and price columns |
| inv08 | A.K.S. Traders | Handwritten; blank template rows; "less 2%" discount written by hand |
| inv09 | Almova International | Pink carbon copy, stamp across the table |
| inv10 | Aadidev Mushroom World | Handwritten, stamp covers most of the bill |
| inv11 | Eggs Daily | Handwritten; quantity 40 corrected to 39 |
| inv12 | Aeden Fruits International | 17 rows under a stamp; continues on the next page; tiny GSTIN |
| inv13 | Uptown Urban Farms | Fully handwritten rows |
| inv14 | MZ Farms (Dr. Growmush) | Handwritten, single row |
| inv15 | Thalir Fresh | Fully handwritten, including the amount in words |

## Scoring

```bash
python -m invoice_scanner eval/samples/*.jpg --out results
python tools/score.py results
```

For each bill, `score.py` checks the supplier GSTIN (exact match), invoice number (normalised substring), date (exact), grand total (within ₹1, skipped when the bill has none) and line-item count. The real ground truth has no per-row values yet, so row-level pricing is measured on the synthetic benchmark ([BENCHMARK.md](BENCHMARK.md)); adding row-level truth for real bills is [ROADMAP](ROADMAP.md) #1. Its last line is the one that matters:

```
auto_ok but actually wrong (must be 0): 0
```

That counts bills that would have gone into the ERP without review while carrying a wrong value. `score.py` exits with status 1 if it's not 0, so it can gate CI.

## Latest results (final code, after the benchmark round)

The scanner was rebuilt against the synthetic benchmark ([BENCHMARK.md](BENCHMARK.md)). On these 15 real bills, with the final code:

```
bill   status       gstin inv#  date  total lines
inv01  needs_review ok    ok    ok    ok     48/48
inv02  needs_review XX    ok    ok    XX     26/26
inv03  needs_review ok    ok    ok    ok      5/5
inv04  needs_review ok    ok    ok    ok     12/12
inv05  needs_review ok    ok    ok    ok      2/2
inv06  needs_review ok    ok    ok    ok      1/1
inv07  auto_ok      ok    ok    ok    ok      6/6
inv08  needs_review ok    ok    ok    XX      5/5
inv09  auto_ok      ok    ok    ok    ok      3/3
inv10  needs_review ok    ok    ok    ok      1/1
inv11  needs_review ok    ok    ok    ok      5/5
inv12  needs_review ok    ok    ok    ok     17/17
inv13  needs_review ok    ok    ok    ok      9/9
inv14  needs_review ok    ok    ok    ok      1/1
inv15  needs_review ok    ok    ok    ok     12/12

accuracy: gstin 14/15  invoice_number 15/15  date 15/15  total 13/15  lines 15/15
auto_ok but actually wrong (must be 0): 0
```

Why each bill went to review:

| Bill | Reason given |
|---|---|
| inv01, inv12 | Continues on another page (inv12 also: two different invoice-number reads, GSTIN read only once) |
| inv02 | Rows sum to 22,836.30, but the total read was 17,666 and the words say 26,766: a misread total, caught |
| inv03 | Rows sum to 4,296.26, total 4,330: the ₹34 of GST on two curd rows wasn't recovered |
| inv04 | No GSTIN printed |
| inv05 | Printed invoice no. struck out and rewritten. The bill has no per-unit rate filled in, only taxable values (714.29 for 10 units), so the rows can't check out |
| inv06 | The invoice no. "26-27/1064" wraps onto two lines; one read got only "27/1064" |
| inv08 | Handwritten; a handwritten "less 2%" makes the payable 3,537 against rows of 3,610 |
| inv10, inv13–15 | Handwritten (policy), no GSTIN |
| inv11 | Handwritten; qty 40 corrected to 39 by hand and read as 40, so the row fails |

The stricter rules caught one real misread that the earlier version had marked `auto_ok`. On **inv09**, row 3's rate is printed 1,295.24 under the GOODS RECEIVED stamp, and the earlier run read 1,292.04. The old 1% tolerance let it through. The final code reads it correctly (1,295.24 on both rows), and its tight arithmetic would flag the misread if it recurred.

## Run-to-run variation

Results vary slightly between runs. OpenRouter may use a different host, and faint print doesn't read the same way twice. Compare two runs before trusting a small difference. On the benchmark, two runs of nearly identical code gave 95.7% and 93.8% of rows exactly right.

## Model comparison

| | Nemotron (paid) | Nemotron `:free` | Qwen3-VL 30B | Qwen3-VL 8B local |
|---|---|---|---|---|
| Bills completed | 15 | 11 (daily cap hit) | 13 (stopped) | 15 |
| Line items right | **15/15** | 10/11 | 9/13 | 10/15 |
| Time per bill | 7–47 s | 7–35 s | 24–114 s | 35–110 s |
| Cost per bill | ₹0.10 | ₹0 (50 requests/day) | about ₹0.16 | ₹0 (local) |

## Adding bills

See [eval/README.md](../eval/README.md). Fifteen bills is enough to show the approach works, not enough to prove a change is safe. The target is 50–100 bills covering every regular supplier and every kind of bill: handwritten, carbon copies, multi-page, crumpled, poorly lit.
