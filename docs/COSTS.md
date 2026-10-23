# Costs

All figures are measured with `nvidia/nemotron-3.5-super-vl` (paid) on OpenRouter, on the 100-bill held-out benchmark with the final code (see [BENCHMARK.md](BENCHMARK.md)). Rupee values assume ₹88/USD; OpenRouter bills in USD.

The cost of each model call is read from OpenRouter's response (`usage.cost`), and per-bill costs are stored in `_meta.usage`. In testing, the sum of those per-call costs matched the account balance change to within $0.000002. (The account total takes 2–3 minutes to catch up after a run.)

## Per bill

| | Calls | Cost |
|---|---|---|
| Short, clean printed bill (header, zoomed header, one item read) | 3 | ~₹0.07 |
| **Median** | 4 | **₹0.114** |
| **Average** | ~5 | **₹0.154** |
| Long dot-matrix sheet (second read + zoomed strips) or a think-aloud reply | 6–8 | ₹0.30–0.45 |

| Volume | Cost |
|---|---|
| 100 bills | ~₹15 |
| 1,000 bills | ~₹154 |
| 50 bills/day for a month | ~₹230 |

Reproduce with:

```bash
python tools/cost_report.py results --inr 88 --csv cost_report.csv
```

## Where the money goes

Measured on the held-out set:

| Step | When | Calls / 100 bills | Cost each | Share |
|---|---|---|---|---|
| Item table, first read | every bill | 100 | ₹0.043 | 28% |
| Zoomed strips | tables > 15 rows, or rows still failing | 60 (on about 20 bills) | ₹0.053 | 21% |
| Header + totals | every bill | 100 | ₹0.026 | 17% |
| Zoomed header (second read + strike-out check) | every bill | 100 | ₹0.025 | 16% |
| Item table, second (verbatim) read | when the first read is in doubt | 47 | ₹0.035 | 11% |
| GSTIN corner crops | when no GSTIN is confirmed | 58 | ₹0.019 | 7% |

- **Input tokens dominate.** Each call re-sends the image: about 1,700 tokens for a full photo, and 2,500–3,100 for an upscaled crop or strip.
- **Think-aloud replies are waste.** About 8% of first item reads think aloud until the 4,096-token limit, costing about ₹0.14 each. See [ROADMAP.md](ROADMAP.md).

## What the accuracy work cost

| | ₹/bill | Rows exactly right (dev) | Silent errors (dev) |
|---|---|---|---|
| Before the benchmark | 0.108 | 83.2% | 17 |
| Exact arithmetic + header consensus | 0.111 | 90.8% | 0 |
| + second table read, deskew, zoomed strips | 0.155 | 93.8–95.7% | 0 |

The safety work (zero silent errors) cost almost nothing. The pricing work (the extra reads) added about ₹0.045 per bill, about ₹45 per 1,000 bills, for about 3–5 more points of rows exactly right and roughly 10 more fully correct bills per 100. The extra reads are gated, so short clean bills don't pay for them.

## Provider choice

| Host | Precision | Input $/M | Output $/M | Supports JSON schema |
|---|---|---|---|---|
| **Crusoe** | **bf16 (full)** | **0.10** | **0.40** | yes |
| Together | unknown | 0.15 | 0.50 | yes |
| DeepInfra | fp4 | 0.15 | 0.50 | yes |
| CoreWeave | nvfp4 | 0.15 | 0.50 | yes |
| Io Net | nvfp4 | 0.15 | 0.50 | **no** |
| BaseTen | fp4 | 0.20 | 0.50 | **no** |
| Venice | fp4 | 0.25 | 1.25 | yes |

These prices were checked in October 2026. Re-check with:

```bash
curl -s https://openrouter.ai/api/v1/models/nvidia/nemotron-3.5-super-vl/endpoints -H "Authorization: Bearer $OPENROUTER_API_KEY"
```

`llm.py` asks for `sort: price` with `require_parameters: true`, which picks Crusoe while it's up. Before this, requests were spread across all 7 hosts and cost ₹0.137 per bill on average; after, ₹0.10, with the same accuracy.

## Free tier

`nvidia/nemotron-3.5-super-vl:free` costs nothing but is capped at **50 requests per day** (about 8 bills), or 1,000 a day after a one-time $10 credit purchase. Free models may also log or train on the bills you send. On the 11 bills it completed, accuracy matched the paid model except for one handwritten bill. **Use the paid model for production.**

## Further savings, and their risk

| Idea | Saving | Risk | Status |
|---|---|---|---|
| Route to the cheapest host | ~25% | None measured | **Done** |
| Skip crops when a GSTIN is already found (free OCR / header) | ~₹0.02 on many printed bills | None: checksum-guarded | **Done** |
| **Supplier master**: known supplier means known GSTIN, so skip all crops | ~₹0.02–0.06 per repeat bill | None; improves accuracy | Recommended next ([ROADMAP](ROADMAP.md)) |
| Skip crops when the model says "no GSTIN" | ~₹0.04 on no-GSTIN bills | Misses tiny GSTINs (inv12) | Rejected |
| Merge the header and items calls | ~₹0.02 | Loops on long tables | Rejected |
| Fold the strike-through check into the header | ₹0.013 | Measured: misses every time | Rejected |
| Smaller images | up to ~35% | Handwriting / tiny print degrade first | Rejected |

| Stop first item reads thinking aloud (system-message rules or a JSON-schema items format) | ~₹0.01 average | Needs a benchmark A/B | Open ([ROADMAP](ROADMAP.md)) |

At about ₹154 per 1,000 bills, one wrong bill reaching the ERP costs more in staff time than all of these savings combined. Accuracy comes first.
