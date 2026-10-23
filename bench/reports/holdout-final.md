# Synthetic benchmark report

100 synthetic bills with 854 item rows. Results `results/e2e-holdout-rv`, ground truth `bench/data/synth-v1-holdout/gt`.

## Headline

| Metric | Result |
|---|---|
| **Silent errors**: auto_ok but wrong (must be 0) | **0** |
| **Rows price-perfect** (qty, rate and amount all exact) | **794/854 (93.0%)** |
| Rows price-perfect, amount must equal the printed line total | 788/854 (92.3%) |
| Bills with every row price-perfect and no extra rows | 86/100 (86.0%) |
| Bills fully correct (rows + header) | 74/100 (74.0%) |
| Automation rate (auto_ok) | 39/100 (39.0%); ceiling 58.0% (bills that need no review) |
| auto_ok precision (auto_ok bills that are fully correct) | 100.0% |
| Missed expected review (truth says review, got auto_ok) | 0 of 42 |
| Unnecessary review (correct, needs no review, still flagged) | 7 of 46 |
| Cost | $0.1746 (Rs 15.37) total; Rs 0.154 per bill; about Rs 154 per 1,000 bills |
| Latency per bill | avg 15.7 s, median 12.1 s, p90 27.3 s, max 41.1 s |

## Item rows

| | Correct | Accuracy |
|---|--:|--:|
| Quantity | 806 / 854 | 94.4% |
| Rate (pre-tax or tax-inclusive) | 807 / 854 | 94.5% |
| Amount (printed, taxable or taxable + GST) | 798 / 854 | 93.4% |
| Amount, printed value only | 792 / 854 | 92.7% |
| Description readable (similarity >= 0.8) | 828 / 854 | 97.0% |

Missed rows: 21. Extra rows: 13 (0 of them out of printed order). Predicted rows that are price-perfect: 794/846 (93.8%).

## Header fields

| Field | Correct | Accuracy |
|---|--:|--:|
| GSTIN | 93 / 100 | 93.0% |
| invoice no. | 95 / 100 | 95.0% |
| date | 98 / 100 | 98.0% |
| grand total | 90 / 97 | 92.8% |
| supplier name | 96 / 100 | 96.0% |

Grand total is not scored on continued pages (no total printed).

## By template

| Template | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| carbon | 10 | 36 | 94.4% | 100.0% | 94.4% | 94.4% | 0 / 0 | 80.0% | 70.0% | 50.0% | 0 | Rs 0.098 |
| dotmatrix | 12 | 324 | 86.7% | 88.6% | 88.9% | 86.7% | 14 / 13 | 58.3% | 41.7% | 33.3% | 0 | Rs 0.293 |
| gst_modern | 18 | 104 | 98.1% | 100.0% | 100.0% | 98.1% | 0 / 0 | 94.4% | 83.3% | 66.7% | 0 | Rs 0.143 |
| handbook | 32 | 188 | 96.8% | 97.9% | 98.9% | 98.9% | 0 / 0 | 84.4% | 71.9% | 0.0% | 0 | Rs 0.134 |
| software | 12 | 48 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 91.7% | 75.0% | 0 | Rs 0.129 |
| tally | 16 | 154 | 95.5% | 95.5% | 95.5% | 95.5% | 7 / 0 | 93.8% | 81.2% | 56.2% | 0 | Rs 0.154 |

## By photo difficulty

| Difficulty | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| easy | 30 | 290 | 94.5% | 95.2% | 95.5% | 95.5% | 10 / 2 | 80.0% | 76.7% | 43.3% | 0 | Rs 0.162 |
| medium | 45 | 344 | 99.1% | 100.0% | 99.7% | 99.1% | 0 / 0 | 95.6% | 82.2% | 44.4% | 0 | Rs 0.131 |
| hard | 25 | 220 | 81.4% | 84.5% | 85.0% | 81.8% | 11 / 11 | 76.0% | 56.0% | 24.0% | 0 | Rs 0.185 |

## By flag

| Flag | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| handwritten | 32 | 188 | 96.8% | 97.9% | 98.9% | 98.9% | 0 / 0 | 84.4% | 71.9% | 0.0% | 0 | Rs 0.134 |
| continued | 3 | 48 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 100.0% | 0.0% | 0 | Rs 0.193 |
| stamp_over_table | 62 | 501 | 95.6% | 96.8% | 96.6% | 96.2% | 10 / 2 | 83.9% | 74.2% | 33.9% | 0 | Rs 0.150 |
| rotated | 45 | 426 | 88.0% | 90.1% | 90.6% | 89.0% | 18 / 11 | 77.8% | 68.9% | 40.0% | 0 | Rs 0.173 |
| underlay | 4 | 57 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 0.0% | 0.0% | 0 | Rs 0.214 |
| has_correction | 12 | 117 | 93.2% | 95.7% | 96.6% | 93.2% | 3 / 2 | 75.0% | 33.3% | 0.0% | 0 | Rs 0.198 |
| no_gstin | 18 | 89 | 96.6% | 97.8% | 98.9% | 100.0% | 0 / 0 | 83.3% | 72.2% | 0.0% | 0 | Rs 0.152 |
| tax_inclusive | 7 | 40 | 95.0% | 100.0% | 100.0% | 95.0% | 0 / 0 | 85.7% | 71.4% | 42.9% | 0 | Rs 0.212 |
| no flags | 9 | 84 | 97.6% | 98.8% | 98.8% | 97.6% | 0 / 0 | 88.9% | 88.9% | 77.8% | 0 | Rs 0.142 |

A bill can have several flags, so flag rows overlap.

## Worst 20 bills

| Bill | Template | Difficulty | Flags | Status | Rows right | What went wrong |
|---|---|---|---|---|--:|---|
| syn082 | dotmatrix | hard | rotated | needs_review | 10/43 | missed row 8 'SWEET POTATO' 3 x 47 = 141; missed row 11 'LEMON' 12 x 121 = 1452; missed row 14 'BROCCOLI' 15.46 x 273.18 = 4223.36; missed row 17 'GINGER' 4.509 x 145 = 653.81; missed row 20 'PEELED BABY CORN' 5 x 48.79 = 243.95; missed row 23 'KALE' 3 x 20.93 = 62.79; ... 41 more |
| syn041 | tally | easy | stamp_over_table, rotated | needs_review | 0/7 | missed row 1 'BOTTLE GOURD' 20.29 x 32.26 = 654.56; missed row 2 'CAULIFLOWER' 33 x 53.39 = 1761.87; missed row 3 'RAW BANANA (NENDRAN)' 28.98 x 55 = 1593.9; missed row 4 'GARLIC (INDIAN)' 11 x 258.02 = 2838.22; missed row 5 'BITTER GOURD GREEN' 27.1 x 59.07 = 1600.8; missed row 6 'CABBAGE' 19.78 x 23 = 454.94; ... 4 more |
| syn036 | dotmatrix | easy | stamp_over_table, has_correction | needs_review | 36/40 | missed row 6 'KOVAKKA' 25.763 x 63 = 1623.07; missed row 20 'RED CABBAGE' 32 x 84 = 2688; missed row 33 'TAPIOCA' 3.35 x 39.79 = 133.3; row 34 SWEET POTATO: qty 3.35 (truth 6.736), rate 39.79 (truth 61), amount 133.3 (truth 410.9); extra row 'MINT' 25.763 x 63 = 1623.07; extra row 'GINGER' 33 x 86 = 2838; ... 2 more |
| syn091 | gst_modern | medium | stamp_over_table, rotated, has_correction, tax_inclusive | needs_review | 6/8 | row 2 INSTANT IDLY BATTER 1 LTR: amount 5698 (truth 5980.8 or 5696); row 7 PUTTU PODI 1 KG: amount 2218.19 (truth 2326.99 or 2216.19); invoice no. '+91-9444-7081' (truth '7081'); grand total '22948.82' (truth '22946.82') |
| syn063 | dotmatrix | easy | - | needs_review | 42/44 | row 13 ROMAINE LETTUCE: rate 140 (truth 141), amount 1680 (truth 1692); row 29 BOTTLE GOURD: qty 29 (truth 29.73), amount 957 (truth 981.09); GSTIN None (truth '32SACFA2645Y1ZH') |
| syn013 | tally | hard | stamp_over_table | needs_review | 9/9 | grand total 'none' (truth '15971'); supplier name None (truth 'NKA FRUITS') |
| syn031 | dotmatrix | hard | stamp_over_table, rotated | needs_review | 29/31 | row 5 ROMAINE LETTUCE: qty 16 (truth 1.926), rate 124.16 (truth 160), amount 1986.56 (truth 308.16); row 17 ASH GOURD: qty 13 (truth 33), amount 390 (truth 990) |
| syn048 | gst_modern | hard | stamp_over_table, has_correction | needs_review | 8/8 | grand total 'none' (truth '17245.3'); supplier name None (truth 'MILKY WAY DAIRY') |
| syn062 | dotmatrix | hard | stamp_over_table | needs_review | 11/13 | row 2 RED CABBAGE: qty 29.362 (truth 29.382), amount 1777 (truth 1777.9); row 5 PEELED BABY CORN: rate 40 (truth 48), amount 2352 (truth 2832) |
| syn094 | handbook | hard | handwritten, rotated, has_correction | needs_review | 3/5 | row 1 MINT LEAVES: qty 6260 (truth 60), amount 10201 (truth 1020); row 5 POTATO: amount 7561 (truth 756) |
| syn003 | handbook | medium | handwritten, stamp_over_table, has_correction, no_gstin | needs_review | 4/4 | supplier name 'NADAN EGGS SUPPLIERS' (truth 'EGGS DAILY') |
| syn008 | dotmatrix | easy | stamp_over_table, underlay | needs_review | 22/22 | GSTIN '32TZPPF9931O2Z6' (truth '32FOMFN6682I1ZX') |
| syn017 | dotmatrix | medium | rotated, underlay | needs_review | 30/30 | GSTIN '32OELFH9744I1ZF' (truth '32HKKCE8969Q1ZU') |
| syn035 | software | hard | underlay, tax_inclusive | needs_review | 3/3 | GSTIN '32CMEPV3338A1ZD' (truth '32ODOFM0318M1ZP') |
| syn056 | handbook | medium | handwritten, rotated | needs_review | 9/9 | grand total '4287.51' (truth '4287.57') |
| syn057 | handbook | medium | handwritten, no_gstin | needs_review | 6/6 | supplier name 'GREEN LEAF, THRISSUR' (truth 'GREEN LEAF') |
| syn060 | tally | medium | rotated, has_correction | needs_review | 14/14 | invoice no. '7454 - 1802' (truth '1802') |
| syn061 | handbook | hard | handwritten, has_correction | needs_review | 5/5 | GSTIN None (truth '32IRUFQ7630C1Z0') |
| syn064 | gst_modern | hard | stamp_over_table, rotated, has_correction | needs_review | 4/4 | invoice no. '81/FS/9608' (truth 'B1/FS/8608') |
| syn067 | handbook | easy | handwritten, stamp_over_table, rotated, no_gstin | needs_review | 2/3 | row 2 BEANS BUSH: qty 27.7 (truth 21.7) |

## How it is scored

- Predicted rows are paired with truth rows top to bottom by an order-preserving alignment that weighs description similarity and agreement of amount, qty and rate. Numbers only choose between truth rows whose descriptions fit equally well, so one item's price read against another item counts as wrong. Unpaired truth rows are missed; unpaired predicted rows are extra.
- Quantity must match within 0.001; rate and amount within Rs 0.01. Rate may be the pre-tax or tax-inclusive rate; amount may be the printed amount, the taxable value or taxable + CGST + SGST. A tax-inclusive rate must come with a tax-inclusive amount.
- GSTIN exact (no GSTIN printed means none must be returned); invoice number exact on letters and digits; date exact; grand total within Rs 0.01; supplier name similarity >= 0.8.
- A silent error is a bill marked auto_ok that is not fully correct: it would go into the ERP wrong.
