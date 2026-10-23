# Output format

`scan_bill()` returns, and the CLI writes to `<results>/<name>.json`, one object per bill. Example: a real result for `eval/samples/inv07.jpg` (SH Foods), shortened where marked.

```json
{
  "supplier": {
    "name": "SH FOODS",
    "gstin": "32ADPFS4356R1Z8",
    "gstin_verified": true,
    "address": null,
    "phone": null
  },
  "buyer": {
    "name": null,
    "gstin": "32AAHCG9621M1ZC"
  },
  "invoice_number": "SH/KK/1120/26-27",
  "invoice_series": null,
  "invoice_date": "2026-08-29",
  "is_handwritten": false,
  "continued_on_next_page": false,
  "line_items": [
    {
      "sl": 1,
      "description": "KUMBAYAH BERRY MIX 275 ML MRP 149/-",
      "hsn": "2202992",
      "quantity": 15.0,
      "unit": "Nos",
      "rate": 102.17,
      "tax_percent": 5.0,
      "amount": 1609.2
    },
    {
      "sl": 2,
      "description": "KUMBAYAH BLACK DOTEX 275ML MRP 149/-",
      "hsn": "2202992",
      "quantity": 15.0,
      "unit": "Nos",
      "rate": 102.17,
      "tax_percent": 5.0,
      "amount": 1609.2
    },
    "... 4 more rows"
  ],
  "totals": {
    "subtotal": 9195.48,
    "cgst": 229.86,
    "sgst": 229.86,
    "igst": null,
    "cess": null,
    "round_off": 0.2,
    "grand_total": 9655.0
  },
  "amount_in_words": "Rupees Nine Thousand Six Hundred Fifty Five Only",
  "header_corrected": false,
  "receiver_bill_ref": "BIL 618",
  "handwritten_notes": [],
  "_meta": {
    "source": "eval/samples/inv07.jpg",
    "model": "openrouter:nvidia/nemotron-3.5-super-vl",
    "rotated_deg": 90,
    "deskew_deg": -2.5,
    "status": "auto_ok",
    "issues": [],
    "items_second_read": true,
    "rows_fixed_by_second_read": [],
    "items_primary": "table",
    "items_zoom_rows": null,
    "gstin_source": "ocr+model",
    "evidence": {
      "invoice_number_reads": [
        "SH/KK/1120/26-27",
        "SH/KK/1120/26-27"
      ],
      "date_reads": [
        "29-08-2026",
        "2026-08-29",
        "29-08-2026"
      ],
      "gstin_reads": [
        "32ADPFS4356R1Z8",
        [
          "32ADPFS4356R1Z8",
          "32AAHCG9621M1ZC",
          "32AAHCG9621M1ZC"
        ]
      ],
      "struck_through": false,
      "ink": "printed",
      "header_says_handwritten": false,
      "columns": "S.N. | Description of Goods | HSN/SAC | Tax % | Qty. | Unit | MRP | Price | CGST Amt | SGST Amt | IGST Amt | Amount(₹)"
    },
    "raw_replies": {
      "items": "(the model's item-table text)"
    },
    "seconds": 10.8,
    "usage": {
      "calls": 4,
      "prompt_tokens": 7907,
      "completion_tokens": 1231,
      "cost_usd": 0.0012831,
      "per_call": [
        "..."
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
| `supplier.gstin_verified` | bool | Passes format, state code and checksum, **and** two sources agreed (OCR + model, or two model reads). If `false`, the value is an unconfirmed guess |
| `supplier.address`, `.phone` | string / null | Often null; not validated |
| `buyer.name` | string / null | As written ("M/s ...", "Bill to"); often null |
| `buyer.gstin` | string | Always `COMPANY_GSTIN` from config |
| `invoice_number` | string / null | As printed (the handwritten replacement if the printed one was struck out; see `header_corrected`). Confirmed by two reads or OCR, otherwise an issue is raised |
| `invoice_series` | string / null | Pre-printed bill-book series split off the number ("26-27 C" from "26-27 C 5207") |
| `invoice_date` | string / null | `YYYY-MM-DD`, parsed day-first in code from the date as printed |
| `is_handwritten` | bool | The quantities, rates or amounts are pen-written |
| `continued_on_next_page` | bool | Page 1 of a multi-page bill: no total on this page |
| `line_items[]` | array | In printed order; blank template rows removed |
| `line_items[].sl` | int / null | The row's printed serial number |
| `line_items[].description` | string | |
| `line_items[].hsn` | string / null | |
| `line_items[].quantity` | number / null | Number only; the unit is separate |
| `line_items[].unit` | string / null | KGS, Boxes, PACK, Nos... |
| `line_items[].rate` | number / null | Price paid per unit, not MRP |
| `line_items[].tax_percent` | number / null | |
| `line_items[].amount` | number / null | The row total as printed (may include GST) |
| `line_items[].unreadable` | bool (only when true) | The model marked a digit of this row as unreadable (`?`) |
| `totals.grand_total` | number / null | Final payable of this invoice (not previous/closing balance) |
| `totals.subtotal`, `.cgst`, `.sgst`, `.igst`, `.cess`, `.round_off` | number / null | Read from the totals block; tax lines summed per tax. Sometimes null or misread - the sum check then falls back to the tax implied by each row's GST rate |
| `amount_in_words` | string / null | Copied verbatim; cross-checked against `grand_total` |
| `header_corrected` | bool | The invoice no./date/total was struck out and rewritten |
| `receiver_bill_ref` | string / null | The receiver's "Bill-6xx" pen note (the store's own reference) |
| `handwritten_notes[]` | strings | Other pen remarks ("quality issue return", "not received") |

### `_meta`: processing information

| Field | Notes |
|---|---|
| `status` | **`auto_ok`** (insert) or **`needs_review`** (show to a person) |
| `issues[]` | Why it needs review, in plain language. Messages starting `line N` refer to `line_items[N-1]` |
| `source` | Input path |
| `model` | `backend:model` used |
| `rotated_deg` / `deskew_deg` | Clockwise rotation and small skew correction applied |
| `items_second_read` | The verbatim-table second read ran; `rows_fixed_by_second_read` lists rows it fixed |
| `items_primary` | Which read leads the merged table: `rows` (fixed format), `table` (verbatim) or `zoom` (strips) |
| `items_zoom_rows` | Rows found by the zoomed strip read (long tables), else null |
| `gstin_source` | `ocr+model` / `model x2` (two sources agree), `ocr`, `crop`, `unverified` (one model read), `none` |
| `evidence` | What each read saw: both invoice-number reads, the date reads, GSTIN reads, `struck_through`, the `INK:` line, whether the header said handwritten, the table's printed column headings |
| `raw_replies` | The model's item-table text (`items`, and `items_table` when the second read ran), for debugging misreads |
| `seconds` | Wall time for this bill |
| `usage` | Calls, tokens and exact USD cost; `per_call` lists every model call with its step and host |

## ERP mapping guidance

- **Insert automatically only when `status == "auto_ok"`.** Everything else goes to a review screen showing the upright photo (`<name>_upright.jpg`), the extracted fields and `issues`. `tools/make_review.py` is a working mock-up of that screen.
- **Treat `invoice_number` + `supplier.gstin` (or the supplier name when there's no GSTIN) as the duplicate key.** The same bill gets photographed twice.
- **Line items with a `line N` issue** usually have a right amount and a misread qty or rate; the issue text gives the implied rate. Rows named in a "read differently in two passes" issue have two plausible readings: check those cells against the photo.
- **Store `handwritten_notes`.** The receiver's "Bill-6xx" note is the store's own reference number, and remarks like "quality issue return" matter for returns.
