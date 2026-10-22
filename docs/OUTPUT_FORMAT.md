# Output format

`scan_bill()` returns, and the CLI writes to `<results>/<name>.json`, one object per bill. Example: a real result for `eval/samples/inv06.jpg`, with `per_call` shortened.

```json
{
  "supplier": {
    "name": "R K MERCANTILE",
    "gstin": "32AGVPR6347Q2ZA",
    "gstin_verified": true,
    "address": null,
    "phone": null
  },
  "buyer": { "name": null, "gstin": "32AAHCG9621M1ZC" },
  "invoice_number": "26-27/1064",
  "invoice_date": "2026-08-29",
  "is_handwritten": false,
  "continued_on_next_page": false,
  "line_items": [
    {
      "description": "FROZEN Chicken Boneless Breast(Varha )",
      "hsn": "02071200",
      "quantity": 20.0,
      "unit": "KGS",
      "rate": 365.0,
      "tax_percent": 5.0,
      "amount": 7665.0
    }
  ],
  "totals": {
    "subtotal": null, "cgst": null, "sgst": null, "igst": null,
    "cess": null, "round_off": null, "grand_total": 7665.0
  },
  "amount_in_words": "Seven Thousand Six Hundred Sixty Five Rupees only",
  "header_corrected": false,
  "handwritten_notes": ["Bill - 621"],
  "_meta": {
    "source": "eval/samples/inv06.jpg",
    "model": "openrouter:nvidia/nemotron-3.5-super-vl",
    "rotated_deg": 90,
    "items_rechecked": false,
    "gstin_source": "crop",
    "seconds": 7.4,
    "status": "auto_ok",
    "issues": [],
    "usage": {
      "calls": 4,
      "prompt_tokens": 6518,
      "completion_tokens": 257,
      "cost_usd": 0.0007546,
      "per_call": [
        { "step": "header", "prompt_tokens": 1608, "completion_tokens": 141, "cost_usd": 0.0002172, "provider": "Crusoe" }
      ]
    }
  }
}
```

## Fields

### Bill data

| Field | Type | Notes |
|---|---|---|
| `supplier.name` | string / null | As printed on the letterhead |
| `supplier.gstin` | string / null | The supplier's GSTIN; never our own |
| `supplier.gstin_verified` | bool | Passes format, state code and checksum. If `false`, the value is the model's unverified guess |
| `supplier.address`, `.phone` | string / null | Often null; not validated |
| `buyer.name` | string / null | As written ("M/s ...", "Bill to"); often null |
| `buyer.gstin` | string | Always `COMPANY_GSTIN` from config |
| `invoice_number` | string / null | As printed. If corrected by hand, see `header_corrected` |
| `invoice_date` | string / null | `YYYY-MM-DD` |
| `is_handwritten` | bool | The item rows are pen-written |
| `continued_on_next_page` | bool | Page 1 of a multi-page bill: no total on this page |
| `line_items[]` | array | In printed order; blank template rows removed |
| `line_items[].description` | string | Serial number stripped |
| `line_items[].hsn` | string / null | |
| `line_items[].quantity` | number / null | Number only; the unit is separate |
| `line_items[].unit` | string / null | KGS, Boxes, PACK, Nos... |
| `line_items[].rate` | number / null | Price paid per unit, not MRP |
| `line_items[].tax_percent` | number / null | |
| `line_items[].amount` | number / null | The row total as printed (may include GST) |
| `totals.grand_total` | number / null | Final payable of this invoice (not previous/closing balance) |
| `totals.subtotal`, `.cgst`, `.sgst`, `.igst`, `.cess`, `.round_off` | number / null | **Often null even when printed**; don't rely on them yet |
| `amount_in_words` | string / null | Copied verbatim; cross-checked against `grand_total` |
| `header_corrected` | bool | The invoice no./date/total was struck out and rewritten |
| `handwritten_notes[]` | strings | Receiver's pen notes ("Bill-641", "quality issue return") |

### `_meta`: processing information

| Field | Notes |
|---|---|
| `status` | **`auto_ok`** (insert) or **`needs_review`** (show to a person) |
| `issues[]` | Why it needs review, in plain language. Messages starting `line N` refer to `line_items[N-1]` |
| `source` | Input path |
| `model` | `backend:model` used |
| `rotated_deg` | Clockwise rotation applied |
| `items_rechecked` | The self-correction re-read was used |
| `gstin_source` | `header/ocr` (free read), `crop` (zoomed letterhead), `unverified` (model guess or none) |
| `seconds` | Wall time for this bill |
| `usage` | Calls, tokens and exact USD cost; `per_call` lists every model call with its step and host |

## ERP mapping guidance

- **Insert automatically only when `status == "auto_ok"`.** Everything else goes to a review screen showing the upright photo (`<name>_upright.jpg`), the extracted fields and `issues`. `tools/make_review.py` is a working mock-up of that screen.
- **Treat `invoice_number` + `supplier.gstin` (or the supplier name when there's no GSTIN) as the duplicate key.** The same bill gets photographed twice.
- **Line items with a `line N` issue** usually have a right amount and a misread qty or rate; the issue text gives the implied rate.
- **Store `handwritten_notes`.** The receiver's "Bill-6xx" note is the store's own reference number, and remarks like "quality issue return" matter for returns.
