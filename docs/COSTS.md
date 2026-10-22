# Costs

All figures are measured on the 15 evaluation bills with `nvidia/nemotron-3.5-super-vl` (paid) on OpenRouter. Rupee values assume ₹88/USD; OpenRouter bills in USD.

The cost of each model call is read from OpenRouter's response (`usage.cost`), and per-bill costs are stored in `_meta.usage`. In testing, the sum of those per-call costs matched the account balance change to within $0.000002. (The account total takes 2–3 minutes to catch up after a run.)

## Per bill

| | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| Cheapest (simple printed bill) | 3 | ~4,300 | ~470 | ₹0.055 |
| **Average** | **4.5** | **~7,300** | **~800** | **₹0.10** |
| Most expensive (handwritten, no GSTIN, or a loop) | 6–7 | ~10,000–11,500 | up to ~4,600 | ₹0.21–0.26 |

| Volume | Cost |
|---|---|
| 100 bills | ~₹10 |
| 1,000 bills | ~₹100 |
| 50 bills/day for a month | ~₹150 |

Reproduce with:

```bash
python tools/cost_report.py results --inr 88 --csv cost_report.csv
```

## Where the money goes

| Step | When | Cost each |
|---|---|---|
| Header + totals | every bill | ₹0.019 |
| Line items | every bill | ₹0.025–0.035 (scales with row count) |
| Strike-through check | every bill | ₹0.013 |
| GSTIN letterhead crop | 0–3 per bill (3 when no GSTIN exists) | ₹0.019 |
| Line-item re-read | only when the arithmetic fails | ₹0.02–0.04 |

Input tokens are about 90% of the total: each call re-sends the image (about 1,300 tokens for a 1280×960 photo; about 1,900 for an upscaled crop).

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

At about ₹100 per 1,000 bills, one wrong bill reaching the ERP costs more in staff time than all of these savings combined. Accuracy comes first.
