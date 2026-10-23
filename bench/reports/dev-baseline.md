# Synthetic benchmark report

100 synthetic bills with 975 item rows. Results `results/synth-v1-baseline`, ground truth `bench/data/synth-v1/gt`.

## Headline

| Metric | Result |
|---|---|
| **Silent errors**: auto_ok but wrong (must be 0) | **17** (FAIL) |
| **Rows price-perfect** (qty, rate and amount all exact) | **811/975 (83.2%)** |
| Rows price-perfect, amount must equal the printed line total | 811/975 (83.2%) |
| Bills with every row price-perfect and no extra rows | 65/100 (65.0%) |
| Bills fully correct (rows + header) | 42/100 (42.0%) |
| Automation rate (auto_ok) | 26/100 (26.0%); ceiling 58.0% (bills that need no review) |
| auto_ok precision (auto_ok bills that are fully correct) | 34.6% |
| Missed expected review (truth says review, got auto_ok) | 7 of 42 |
| Unnecessary review (correct, needs no review, still flagged) | 11 of 15 |
| Cost | $0.1230 (Rs 10.82) total; Rs 0.108 per bill; about Rs 108 per 1,000 bills |
| Latency per bill | avg 20.2 s, median 16.6 s, p90 38.0 s, max 105.6 s |

## Item rows

| | Correct | Accuracy |
|---|--:|--:|
| Quantity | 858 / 975 | 88.0% |
| Rate (pre-tax or tax-inclusive) | 888 / 975 | 91.1% |
| Amount (printed, taxable or taxable + GST) | 855 / 975 | 87.7% |
| Amount, printed value only | 855 / 975 | 87.7% |
| Description readable (similarity >= 0.8) | 923 / 975 | 94.7% |

Missed rows: 20. Extra rows: 21 (0 of them out of printed order). Predicted rows that are price-perfect: 811/976 (83.1%).

## Header fields

| Field | Correct | Accuracy |
|---|--:|--:|
| GSTIN | 91 / 100 | 91.0% |
| invoice no. | 78 / 100 | 78.0% |
| date | 87 / 100 | 87.0% |
| grand total | 92 / 94 | 97.9% |
| supplier name | 99 / 100 | 99.0% |

Grand total is not scored on continued pages (no total printed).

## By template

| Template | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| carbon | 10 | 44 | 81.8% | 86.4% | 95.5% | 95.5% | 0 / 0 | 70.0% | 20.0% | 30.0% | 3 | Rs 0.074 |
| dotmatrix | 12 | 392 | 76.0% | 81.6% | 86.5% | 80.6% | 13 / 13 | 16.7% | 8.3% | 16.7% | 2 | Rs 0.156 |
| gst_modern | 18 | 114 | 74.6% | 82.5% | 86.8% | 80.7% | 6 / 0 | 50.0% | 27.8% | 16.7% | 1 | Rs 0.086 |
| handbook | 32 | 203 | 91.1% | 96.1% | 96.5% | 94.6% | 0 / 3 | 84.4% | 71.9% | 18.8% | 1 | Rs 0.117 |
| software | 12 | 49 | 98.0% | 100.0% | 98.0% | 100.0% | 0 / 4 | 83.3% | 50.0% | 33.3% | 3 | Rs 0.116 |
| tally | 16 | 173 | 91.9% | 93.6% | 94.8% | 94.8% | 1 / 1 | 62.5% | 31.2% | 50.0% | 7 | Rs 0.095 |

## By photo difficulty

| Difficulty | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| easy | 30 | 284 | 94.0% | 97.2% | 97.9% | 96.1% | 0 / 4 | 83.3% | 50.0% | 30.0% | 4 | Rs 0.107 |
| medium | 45 | 429 | 77.9% | 82.5% | 85.1% | 83.5% | 18 / 12 | 57.8% | 37.8% | 22.2% | 9 | Rs 0.105 |
| hard | 25 | 262 | 80.2% | 87.0% | 93.5% | 85.5% | 2 / 5 | 56.0% | 40.0% | 28.0% | 4 | Rs 0.116 |

## By flag

| Flag | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows | Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| handwritten | 32 | 203 | 91.1% | 96.1% | 96.5% | 94.6% | 0 / 3 | 84.4% | 71.9% | 18.8% | 1 | Rs 0.117 |
| continued | 6 | 126 | 78.6% | 82.5% | 82.5% | 84.9% | 2 / 1 | 33.3% | 33.3% | 0.0% | 0 | Rs 0.129 |
| stamp_over_table | 65 | 660 | 81.7% | 85.5% | 90.8% | 87.4% | 11 / 18 | 61.5% | 40.0% | 30.8% | 13 | Rs 0.112 |
| rotated | 50 | 536 | 86.9% | 91.2% | 93.8% | 89.4% | 9 / 13 | 70.0% | 44.0% | 34.0% | 11 | Rs 0.102 |
| underlay | 4 | 21 | 61.9% | 71.4% | 90.5% | 95.2% | 0 / 4 | 25.0% | 0.0% | 25.0% | 1 | Rs 0.134 |
| has_correction | 12 | 91 | 92.3% | 100.0% | 100.0% | 92.3% | 0 / 0 | 83.3% | 75.0% | 25.0% | 1 | Rs 0.105 |
| no_gstin | 23 | 161 | 88.2% | 94.4% | 95.7% | 93.2% | 0 / 0 | 78.3% | 65.2% | 0.0% | 0 | Rs 0.130 |
| tax_inclusive | 14 | 71 | 62.0% | 73.2% | 85.9% | 80.3% | 0 / 0 | 35.7% | 21.4% | 57.1% | 5 | Rs 0.073 |
| no flags | 9 | 101 | 79.2% | 85.2% | 87.1% | 80.2% | 8 / 2 | 66.7% | 33.3% | 0.0% | 0 | Rs 0.114 |

A bill can have several flags, so flag rows overlap.

## Worst 20 bills

| Bill | Template | Difficulty | Flags | Status | Rows right | What went wrong |
|---|---|---|---|---|--:|---|
| syn082 | software | medium | rotated, has_correction, tax_inclusive | **auto_ok** | 3/3 | AUTO_OK BUT WRONG; auto_ok but truth expects review (invoice number corrected); invoice no. 'COK26-27/1969' (truth 'COK26-27/9208') |
| syn083 | handbook | medium | handwritten, rotated | **auto_ok** | 7/7 | AUTO_OK BUT WRONG; auto_ok but truth expects review (handwritten); invoice no. '26-27 c 834' (truth '834') |
| syn004 | dotmatrix | medium | stamp_over_table, rotated | **auto_ok** | 25/31 | AUTO_OK BUT WRONG; missed row 30 'CABBAGE' 26.9 x 21.75 = 585.08; row 2 CARROT OOTY: qty 12 (truth 27), amount 684 (truth 1539); row 5 LADIES FINGER: qty 12 (truth 26), amount 636 (truth 1378); row 14 BEANS BUSH: amount 1569.78 (truth 1569.75); row 27 KOVAKKA: qty 24.02 (truth 3), amount 1771.5 (truth 221.25); ... 3 more |
| syn063 | gst_modern | medium | stamp_over_table, rotated, tax_inclusive | **auto_ok** | 6/8 | AUTO_OK BUT WRONG; row 3 INSTANT EDIYAPPAM 1 KG: amount 6469.76 (truth 6459.76 or 6152.16); row 5 INSTANT IDLY BATTER 1 LTR: amount 552.94 (truth 552.64 or 526.32); invoice no. 'TI-03256' (truth 'TI-93256'); date '2026-04-20' (truth '2026-08-24') |
| syn077 | tally | hard | stamp_over_table, rotated | **auto_ok** | 12/14 | AUTO_OK BUT WRONG; row 9 GARLIC (INDIAN): qty 12.322 (truth 12.392), amount 2655.19 (truth 2670.48); row 10 LADIES FINGER: amount 202.43 (truth 202.39); invoice no. 'EKIM/2021/1196' (truth 'EKM/2026/1196') |
| syn010 | tally | medium | stamp_over_table, rotated | **auto_ok** | 14/15 | AUTO_OK BUT WRONG; row 2 GRAPES SEEDLESS: qty 10.15 (truth 10.155); date '2026-05-25' (truth '2026-08-25') |
| syn007 | carbon | easy | stamp_over_table, rotated, tax_inclusive | **auto_ok** | 6/7 | AUTO_OK BUT WRONG; row 1 CARDAMOM 100 G: rate 271.9 (truth 271 or 284.55) |
| syn020 | tally | easy | stamp_over_table, rotated | **auto_ok** | 4/4 | AUTO_OK BUT WRONG; invoice no. 'TI-8430' (truth 'TI-84340') |
| syn023 | carbon | easy | stamp_over_table | **auto_ok** | 5/5 | AUTO_OK BUT WRONG; date '2026-01-28' (truth '2026-08-31') |
| syn031 | tally | medium | stamp_over_table, rotated | **auto_ok** | 7/7 | AUTO_OK BUT WRONG; invoice no. 'COKD-26/1835' (truth 'COK26-27/1835') |
| syn042 | dotmatrix | hard | stamp_over_table | **auto_ok** | 26/26 | AUTO_OK BUT WRONG; GSTIN '32INKCJ1833G1ZU' (truth '32NKJCR1836U1ZS') |
| syn053 | software | hard | stamp_over_table, tax_inclusive | **auto_ok** | 3/3 | AUTO_OK BUT WRONG; invoice no. 'INV/2026/18055' (truth 'INV/2026/180055') |
| syn060 | tally | easy | stamp_over_table, rotated | **auto_ok** | 15/15 | AUTO_OK BUT WRONG; invoice no. 'OKX28-27158' (truth 'COK26-27/2158') |
| syn072 | tally | medium | stamp_over_table | **auto_ok** | 7/7 | AUTO_OK BUT WRONG; date '2026-07-28' (truth '2026-08-27') |
| syn074 | carbon | hard | underlay | **auto_ok** | 2/2 | AUTO_OK BUT WRONG; invoice no. '661' (truth '6954') |
| syn075 | software | medium | tax_inclusive | **auto_ok** | 5/6 | AUTO_OK BUT WRONG; row 2 FROZEN GREEN PEAS 1 KG: rate 140 (truth 140.5 or 147.53) |
| syn098 | tally | medium | stamp_over_table, rotated | **auto_ok** | 8/8 | AUTO_OK BUT WRONG; invoice no. 'GST/283/26-27' (truth 'GST/3283/26-27') |
| syn024 | handbook | easy | handwritten, rotated, has_correction | auto_ok | 11/11 | auto_ok but truth expects review (handwritten) |
| syn041 | handbook | easy | handwritten, stamp_over_table | auto_ok | 6/6 | auto_ok but truth expects review (handwritten) |
| syn059 | handbook | easy | handwritten, stamp_over_table, rotated, has_correction | auto_ok | 8/8 | auto_ok but truth expects review (handwritten) |

## How it is scored

- Predicted rows are paired with truth rows top to bottom by an order-preserving alignment that weighs description similarity and agreement of amount, qty and rate. Numbers only choose between truth rows whose descriptions fit equally well, so one item's price read against another item counts as wrong. Unpaired truth rows are missed; unpaired predicted rows are extra.
- Quantity must match within 0.001; rate and amount within Rs 0.01. Rate may be the pre-tax or tax-inclusive rate; amount may be the printed amount, the taxable value or taxable + CGST + SGST. A tax-inclusive rate must come with a tax-inclusive amount.
- GSTIN exact (no GSTIN printed means none must be returned); invoice number exact on letters and digits; date exact; grand total within Rs 0.01; supplier name similarity >= 0.8.
- A silent error is a bill marked auto_ok that is not fully correct: it would go into the ERP wrong.
