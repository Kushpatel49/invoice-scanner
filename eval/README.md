# Evaluation set

`samples/` holds real purchase bills photographed at the store; `ground_truth.json` has the hand-checked answers that `tools/score.py` compares against.

> These are real supplier documents (GSTINs, phone numbers, bank details). Keep this repository private.

## Ground truth format

```json
"inv05": {
  "supplier": "Arayacherril Varkey & Sons",
  "gstin": "32AAQCA8177P1ZU",
  "invoice_number": "2872",
  "date": "2026-08-29",
  "total": 1470,
  "lines": 2,
  "rotate_deg": 270,
  "note": "printed RO 2199 struck out, handwritten 26AB0A0 2872"
}
```

| Key | Meaning |
|---|---|
| `supplier` | For humans only; not scored |
| `gstin` | Supplier GSTIN exactly, or `null` if none is printed on this bill |
| `invoice_number` | Scored as a normalised substring (letters and digits only), so `"2872"` matches `"RO 2872"` |
| `date` | `YYYY-MM-DD` |
| `total` | Grand total payable, or `null` if this page has none (multi-page bill) |
| `lines` | Number of real item rows (not blank template rows) |
| `rotate_deg` | Clockwise rotation that makes the photo upright; checked offline by `tests/test_orientation.py` |
| `note` | Anything unusual: corrections, discounts, overlapping bills |

## Adding a bill

1. Save the photo as `samples/invNN.jpg` (the next number), exactly as staff would take it; don't straighten or crop it.
2. Read the bill yourself and add an entry to `ground_truth.json`. For `rotate_deg`: 90 if the top of the text points left in the photo, 270 if it points right, 180 if upside down.
3. Run `python -m unittest tests.test_orientation` (free) and the full scoring run.

When the scanner disagrees with your ground truth, zoom into the photo before assuming the scanner is wrong. During development the "ground truth" itself was wrong once (inv03's invoice number is 108**6**47, not 108**8**47).
