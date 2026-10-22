# Roadmap

Ordered by value. Each item says what "done" looks like.

## 1. Grow the evaluation set (do first)

Fifteen bills prove the approach, not its safety across everything the stores receive. Collect **50–100 more real bills**: every regular supplier, plus more handwritten bills, carbon copies, multi-page bills, crumpled paper and poorly lit photos. Hand-check them into `eval/ground_truth.json`.

**Done when:** `tools/score.py` runs on 50+ bills and "wrong bills marked auto_ok" is 0.

## 2. Supplier master

Keep a table of known suppliers: name, aliases, GSTIN (or "no GSTIN"), and their usual items with typical rates. On each bill:

- **Match the supplier** (fuzzy name match, or a GSTIN found by the free OCR read).
- **Known supplier:** take the GSTIN from the master and skip the paid letterhead crops. That saves ₹0.02–0.06 per bill, and the stored GSTIN becomes an extra check on the extraction.
- **Typical rates:** a rate far from a supplier's usual one for an item becomes a review issue.
- **New supplier:** after a person confirms the first bill, add the supplier to the master.

Hook point: `gstin.find_supplier_gstin()`, plus a new check in `validate.py`.

**Done when:** repeat-supplier bills make no crop calls, and accuracy on the eval set doesn't drop.

## 3. Multi-page invoices

Today a page with `continued_on_next_page` is flagged, and later pages are processed as separate bills. Group the photos of one invoice (same supplier + invoice number, or uploaded together), merge their line items, and take the total from the last page. Then run validation on the merged invoice.

**Done when:** inv01 and inv12 can be completed with their next pages and pass validation.

## 4. ERP insert and review screen

- Map the result JSON to the ERP's purchase bill entry (see [OUTPUT_FORMAT.md](OUTPUT_FORMAT.md) for guidance).
- Auto-insert `auto_ok` bills. Send `needs_review` bills to a review screen: the photo beside editable fields with the issues highlighted. `tools/make_review.py` shows the idea.
- Prevent duplicates (invoice number + supplier).
- Store the original photo with the ERP record.

## 5. Run it as a service

Wrap `scan_bill()` in a small HTTP API (for example FastAPI: `POST /scan` with an image, returning the JSON) so the ERP, a mobile app or a WhatsApp/scanner inbox can call it. Process bills in a queue: they're independent, so several can run at once. Mind OpenRouter's rate limits.

## 6. Smaller improvements

- **Tax breakdown:** CGST/SGST/subtotal often come back null. Try a dedicated small request for the tax summary, measure the extra cost against what it adds, then add the `subtotal + tax = total` check.
- **Year rollover:** use the scan date to decide the year for bills dated in late December and scanned in January.
- **Item-table loops** (rare, e.g. inv10): stream the response and stop as soon as rows repeat, instead of waiting for the 4,096-token limit.
- **Two bills in one photo:** detect it and ask for separate photos.
- **Accuracy alerts:** log `status` and `issues` per bill, and watch the share of `needs_review` and the most common issues per supplier.
