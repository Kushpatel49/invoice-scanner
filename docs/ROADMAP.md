# Roadmap

Ordered by value. Each item says what "done" looks like.

## 1. Grow the real evaluation set (do first)

The synthetic benchmark ([BENCHMARK.md](BENCHMARK.md)) is now the main way changes are measured, but synthetic bills are only as varied as their generator. Collect **50–100 more real bills**:

- every regular supplier
- more handwritten bills, carbon copies and multi-page bills
- crumpled paper and poorly lit photos

Hand-check them into `eval/ground_truth.json`, including line items: qty, rate and amount per row, so the real set can be scored as strictly as the synthetic one.

**Done when:** `tools/score.py` runs row-level on 50+ real bills and "wrong bills marked auto_ok" is 0.

## 2. Supplier master

Keep a table of known suppliers: name, aliases, GSTIN (or "no GSTIN"), and their usual items with typical rates. On each bill:

- **Match the supplier,** by fuzzy name match or by a GSTIN found by the free OCR read.
- **Known supplier:** take the GSTIN from the master and skip the paid letterhead crops. That saves ₹0.02–0.06 per bill, and the stored GSTIN becomes a third independent confirmation, which also removes most "GSTIN not confirmed" reviews.
- **Typical rates:** a rate far from a supplier's usual one for an item becomes a review issue. This catches self-consistent misreads that the two reads happen to agree on.
- **New supplier:** after a person confirms the first bill, add the supplier to the master.

Hook point: `gstin.find_supplier_gstin()`, plus a new check in `validate.py`.

**Done when:** repeat-supplier bills make no crop calls, and benchmark accuracy doesn't drop.

## 3. Dot-matrix accuracy

Dot-matrix sheets are the weakest format: 85–92% of rows right across runs, against 98–100% for the other formats. The rows are 13–15 px tall in a 1280-px photo. Things to try, each A/B'd on the benchmark:

- 3x strips instead of 2x
- asking the store for closer photos of long bills (the cheapest fix)
- a vote between two zoomed reads on rows where they disagree

## 4. Multi-page invoices

Today a page with `continued_on_next_page` is flagged, and later pages are processed as separate bills. Group the photos of one invoice (same supplier + invoice number, or uploaded together), merge their line items, and take the total from the last page. Then run validation on the merged invoice.

**Done when:** inv01 and inv12 can be completed with their next pages and pass validation.

## 5. ERP insert and review screen

- Map the result JSON to the ERP's purchase bill entry (see [OUTPUT_FORMAT.md](OUTPUT_FORMAT.md)).
- Auto-insert `auto_ok` bills. Send `needs_review` bills to a review screen: the photo beside editable fields, with the issues highlighted. For rows "read differently in two passes", show both readings. `tools/make_review.py` shows the idea.
- Prevent duplicates (invoice number + supplier).
- Store the original photo with the ERP record.

## 6. Run it as a service

Wrap `scan_bill()` in a small HTTP API (for example FastAPI: `POST /scan` with an image, returning the JSON) so the ERP, a mobile app or a WhatsApp/scanner inbox can call it. Bills are independent, so a queue with a few workers works; `--workers` already does this for the CLI. Mind OpenRouter's rate limits and the key's spending cap.

## 7. Smaller improvements

- **Handwriting flag:** the `INK:` line flips between runs on some printed bills. Use the two signals logged in `_meta.evidence` on real bills to settle the rule.
- **Tax lines:** they are still sometimes misread (e.g. CGST 564.83 for 1,569.84), which sends correct bills to review. A dedicated small request for the totals block may pay for itself.
- **Year rollover:** use the scan date to decide the year for bills dated in late December and scanned in January.
- **Think-aloud cost:** about 8% of first item reads think aloud until the token limit (₹0.14 wasted each). Try putting the rules in a system message, or a JSON-schema items format, which can't contain prose. Measure on the benchmark.
- **Two bills in one photo:** detect it and ask for separate photos.
- **Accuracy alerts:** log `status` and `issues` per bill, and watch the share of `needs_review` and the most common issues per supplier.
