# Synthetic benchmark report

100 synthetic bills with 975 item rows. Results `results/final-synth-v1-rv`, ground truth `bench/data/synth-v1/gt`.

## Headline

| Metric | Result |
|---|---|
| **Silent errors**: auto_ok but wrong (must be 0) | **0** |
| **Rows price-perfect** (qty, rate and amount all exact) | **915/975 (93.8%)** |
| Rows price-perfect, amount must equal the printed line total | 915/975 (93.8%) |
| Bills with every row price-perfect and no extra rows | 91/100 (91.0%) |
| Bills fully correct (rows + header) | 81/100 (81.0%) |
| Automation rate (auto_ok) | 39/100 (39.0%); ceiling 58.0% (bills that need no review) |
| auto_ok precision (auto_ok bills that are fully correct) | 100.0% |
| Missed expected review (truth says review, got auto_ok) | 0 of 42 |
| Unnecessary review (correct, needs no review, still flagged) | 7 of 46 |
| Cost | $0.1767 (Rs 15.55) total; Rs 0.155 per bill; about Rs 156 per 1,000 bills |
| Latency per bill | avg 17.1 s, median 13.2 s, p90 29.4 s, max 47.0 s |

## Item rows

| | Correct | Accuracy |
|---|--:|--:|
| Quantity | 927 / 975 | 95.1% |
| Rate (pre-tax or tax-inclusive) | 920 / 975 | 94.4% |
| Amount (printed, taxable or taxable + GST) | 916 / 975 | 94.0% |
| Amount, printed value only | 916 / 975 | 94.0% |
| Description readable (similarity >= 0.8) | 925 / 975 | 94.9% |

Missed rows: 34. Extra rows: 11 (0 of them out of printed order). Predicted rows that are price-perfect: 915/952 (96.1%).

## Header fields

| Field | Correct | Accuracy |
|---|--:|--:|
| GSTIN | 96 / 100 | 96.0% |
| invoice no. | 98 / 100 | 98.0% |
| date | 99 / 100 | 99.0% |
| grand total | 89 / 94 | 94.7% |
| supplier name | 98 / 100 | 98.0% |

Grand total is not scored on continued pages (no total printed).

## By template

| Template | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| carbon | 10 | 44 | 97.7% | 97.7% | 97.7% | 97.7% | 0 / 0 | 90.0% | 80.0% | 60.0% | 0 | Rs 0.156 |
| dotmatrix | 12 | 392 | 85.5% | 88.0% | 86.2% | 85.7% | 34 / 11 | 41.7% | 41.7% | 25.0% | 0 | Rs 0.345 |
| gst_modern | 18 | 114 | 98.2% | 100.0% | 100.0% | 98.2% | 0 / 0 | 94.4% | 88.9% | 72.2% | 0 | Rs 0.149 |
| handbook | 32 | 203 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 90.6% | 0.0% | 0 | Rs 0.113 |
| software | 12 | 49 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 83.3% | 75.0% | 0 | Rs 0.127 |
| tally | 16 | 173 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 81.2% | 50.0% | 0 | Rs 0.127 |

## By photo difficulty

| Difficulty | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| easy | 30 | 284 | 98.6% | 98.9% | 98.6% | 98.6% | 2 / 2 | 96.7% | 83.3% | 33.3% | 0 | Rs 0.141 |
| medium | 45 | 429 | 88.8% | 90.2% | 90.0% | 89.0% | 31 / 8 | 86.7% | 77.8% | 48.9% | 0 | Rs 0.166 |
| hard | 25 | 262 | 97.0% | 98.9% | 97.0% | 97.0% | 1 / 1 | 92.0% | 84.0% | 28.0% | 0 | Rs 0.154 |

## By flag

| Flag | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| handwritten | 32 | 203 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 90.6% | 0.0% | 0 | Rs 0.113 |
| continued | 6 | 126 | 79.4% | 79.4% | 79.4% | 79.4% | 24 / 1 | 66.7% | 50.0% | 0.0% | 0 | Rs 0.258 |
| stamp_over_table | 65 | 660 | 92.6% | 93.5% | 93.2% | 92.7% | 32 / 9 | 89.2% | 83.1% | 36.9% | 0 | Rs 0.154 |
| rotated | 50 | 536 | 95.0% | 96.8% | 95.7% | 95.2% | 7 / 7 | 90.0% | 80.0% | 42.0% | 0 | Rs 0.151 |
| underlay | 4 | 21 | 95.2% | 95.2% | 95.2% | 95.2% | 0 / 0 | 75.0% | 0.0% | 0.0% | 0 | Rs 0.210 |
| has_correction | 12 | 91 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 91.7% | 0.0% | 0 | Rs 0.139 |
| no_gstin | 23 | 161 | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 0 | 100.0% | 91.3% | 0.0% | 0 | Rs 0.124 |
| tax_inclusive | 14 | 71 | 95.8% | 98.6% | 98.6% | 95.8% | 0 / 0 | 85.7% | 78.6% | 71.4% | 0 | Rs 0.190 |
| no flags | 9 | 101 | 96.0% | 97.0% | 97.0% | 96.0% | 1 / 1 | 88.9% | 88.9% | 77.8% | 0 | Rs 0.169 |

A bill can have several flags, so flag rows overlap.

## Worst 19 bills

| Bill | Template | Difficulty | Flags | Status | Rows right | What went wrong |
|---|---|---|---|---|--:|---|
| syn091 | dotmatrix | medium | continued, stamp_over_table | needs_review | 2/26 | missed row 3 'DRUMSTICK' 38 x 96.89 = 3681.82; missed row 4 'CUCUMBER SALAD' 28 x 27.75 = 777; missed row 5 'ONION BIG' 33 x 31 = 1023; missed row 6 'SPRING ONION' 6.8 x 133 = 904.4; missed row 7 'MINT LEAVES' 28 x 17 = 476; missed row 8 'TOMATO HYBRID' 16.64 x 19 = 316.16; ... 19 more |
| syn033 | dotmatrix | medium | stamp_over_table, rotated | needs_review | 35/47 | missed row 12 'BEANS BUSH' 27.7 x 97 = 2686.9; missed row 17 'LADIES FINGER' 11.048 x 69.95 = 772.81; missed row 31 'CORIANDER LEAVES' 10.992 x 97 = 1066.22; missed row 36 'SNAKE GOURD' 16 x 46 = 736; missed row 41 'CURRY LEAVES' 14.77 x 59.69 = 881.62; row 3 CUCUMBER SALAD: qty 5 (truth 9), amount 125 (truth 225); ... 11 more |
| syn093 | dotmatrix | hard | rotated | needs_review | 29/36 | missed row 5 'DRUMSTICK' 7 x 138 = 966; row 3 RED CABBAGE: rate 75 (truth 73), amount 692.25 (truth 673.79); row 4 CAPSICUM YELLOW: rate 210 (truth 217), amount 6720 (truth 6944); row 11 LADIES FINGER: qty 22 (truth 22.92), rate 49.16 (truth 44.16), amount 1081.52 (truth 1012.15); row 19 BEANS BUSH: rate 110 (truth 111.5), amount 3190 (truth 3233.5); row 26 SWEET POTATO: rate 61.5 (truth 61), amount 503.2 (truth 499.1); ... 3 more |
| syn003 | dotmatrix | easy | stamp_over_table | needs_review | 37/41 | missed row 14 'CHILLY GREEN' 19.319 x 46.61 = 900.46; missed row 29 'MINT LEAVES' 49 x 17 = 833; row 6 BRINJAL GREEN LONG: qty 14.9 (truth 14.3), rate 42 (truth 42.02), amount 625.79 (truth 600.89); row 36 SPRING ONION: rate 128 (truth 119), amount 1792 (truth 1666); extra row 'CHERRY GREEN' 19.315 x 44.61 = 861.66; extra row 'MANGO LEMON' 3 x 17 = 51 |
| syn004 | dotmatrix | medium | stamp_over_table, rotated | needs_review | 27/31 | missed row 30 'CABBAGE' 26.9 x 21.75 = 585.08; row 6 POTATO: rate 27 (truth 27.19), amount 713.37 (truth 718.39); row 7 AMARANTHUS GREEN BUNCH: rate 11 (truth 13), amount 209 (truth 247); row 31 BOTTLE GOURD: qty 26.9 (truth 21.24), rate 21.75 (truth 32), amount 585.08 (truth 679.68); extra row 'BANALE' 21.24 x 32 = 679.68; grand total '33664' (truth '33664.8') |
| syn089 | dotmatrix | medium | - | needs_review | 23/27 | missed row 16 'GINGER' 28.619 x 174.5 = 4994.02; row 3 BAJI CHILLY: rate 49.71 (truth 49.01), amount 298.26 (truth 294.06); row 4 TOMATO HYBRID: qty 21 (truth 21.6), amount 1044.75 (truth 1074.6); row 15 BEETROOT OOTY: qty 2 (truth 11), rate 50 (truth 52), amount 100 (truth 572); extra row 'BITTER GOURD' 28.619 x 174.5 = 4994.02 |
| syn063 | gst_modern | medium | stamp_over_table, rotated, tax_inclusive | needs_review | 6/8 | row 2 INSTANT PUNCHA EDIYAPPAM 1 K: amount 521.88 (truth 521.86 or 497); row 8 INSTANT VEG PALAPPAM 1 LTR: amount 633.18 (truth 633.16 or 603); grand total '13788.78' (truth '13788') |
| syn055 | dotmatrix | medium | continued, stamp_over_table, rotated | needs_review | 38/40 | row 37 RAW BANANA (NENDRAN): qty 15.384 (truth 13.395), rate 148 (truth 58.93), amount 2276.83 (truth 789.37); row 38 GARLIC (INDIAN): qty 2 (truth 15.384), rate 232 (truth 148), amount 464 (truth 2276.83) |
| syn098 | tally | medium | stamp_over_table, rotated | needs_review | 8/8 | grand total 'none' (truth '6224'); supplier name None (truth 'PERIYAR VEGETABLE COMPANY') |
| syn018 | carbon | hard | stamp_over_table, underlay, tax_inclusive | needs_review | 5/6 | row 1 CHILLI POWDER 500 G: qty 14 (truth 6), rate 93.04 (truth 153 or 160.65), amount 1302.56 (truth 963.9 or 918) |
| syn027 | tally | easy | rotated | needs_review | 7/7 | date '2026-08-20' (truth '2026-08-29') |
| syn029 | tally | medium | continued, underlay | needs_review | 11/11 | GSTIN '33CFSPP8725N1ZI' (truth '32ZFLPP8689Q1ZJ') |
| syn034 | handbook | easy | handwritten, stamp_over_table, no_gstin | needs_review | 9/9 | supplier name 'A.K.S. TRADERS, THRISSUR' (truth 'A.K.S. TRADERS') |
| syn052 | handbook | hard | handwritten, stamp_over_table, no_gstin | needs_review | 8/8 | grand total '45993' (truth '45593') |
| syn057 | software | easy | stamp_over_table, underlay | needs_review | 2/2 | GSTIN '32WVICT4262G1ZN' (truth '32NFACU4994O1Z4') |
| syn068 | gst_modern | easy | rotated | needs_review | 7/7 | grand total '45780.1' (truth '45790.1') |
| syn074 | carbon | hard | underlay | needs_review | 2/2 | GSTIN '32DYZCM9084S1ZN' (truth '32KWBFD1057N1Z4') |
| syn082 | software | medium | rotated, has_correction, tax_inclusive | needs_review | 3/3 | invoice no. 'COK26-27/1969' (truth 'COK26-27/9208') |
| syn083 | handbook | medium | handwritten, rotated | needs_review | 7/7 | invoice no. '26-27 834' (truth '834') |

## How it is scored

- Predicted rows are paired with truth rows top to bottom by an order-preserving alignment that weighs description similarity and agreement of amount, qty and rate. Numbers only choose between truth rows whose descriptions fit equally well, so one item's price read against another item counts as wrong. Unpaired truth rows are missed; unpaired predicted rows are extra.
- Quantity must match within 0.001; rate and amount within Rs 0.01. Rate may be the pre-tax or tax-inclusive rate; amount may be the printed amount, the taxable value or taxable + CGST + SGST. A tax-inclusive rate must come with a tax-inclusive amount.
- GSTIN exact (no GSTIN printed means none must be returned); invoice number exact on letters and digits; date exact; grand total within Rs 0.01; supplier name similarity >= 0.8.
- A silent error is a bill marked auto_ok that is not fully correct: it would go into the ERP wrong.
