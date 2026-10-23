"""Bill templates. Each module exposes

    render(spec: dict, rng: random.Random) -> (page: PIL.Image.Image (RGB), layout: dict)

`spec` comes from bench.synth.spec.make_spec; it is also the ground truth, so the
page must print exactly these values:

  - supplier name / address / GSTIN (when not None) / phone / FSSAI / email as the format allows
  - spec["buyer"]["display"] as the bill-to line
  - spec["invoice_number_printed"]   (NOT spec["invoice_number"]; they differ when a
                                       correction is drawn later by effects.py)
  - spec["date_printed"]
  - every row in spec["items"] in order: description, hsn, quantity, unit, rate,
    (tax_percent / cgst / sgst / taxable / mrp where the format has such columns), and the
    row's line total column == item["amount"] exactly (formatted like a real bill: 1,609.20)
  - totals (subtotal / CGST / SGST / round off / grand total) and spec["amount_in_words"],
    UNLESS spec["continued"] is True: then print no totals, end the table with "continued..."
  - for handwritten templates, a quantity correction (spec["corrections"]["quantity"]) is drawn by
    the template in its own cell: print the "printed" value, strike it, write "new" next to it.

layout (page pixel coordinates, used by effects.py to place stamps, notes and strike-throughs):

  {
    "table_bbox": (x0, y0, x1, y1),           # item table incl. header row
    "header_bbox": (x0, y0, x1, y1),          # seller letterhead block
    "invoice_number_bbox": (x0, y0, x1, y1),  # the printed invoice number text itself
    "date_bbox": (x0, y0, x1, y1),
    "rows": [{"y0", "y1", "desc_bbox", "qty_bbox", "amount_bbox"}, ...],   # one per printed row;
                                              # y0/y1 = the row's band in the table (cell band, not ink extent)
    "total_bbox": (x0, y0, x1, y1) | None,    # tight box around the grand-total value text; None if continued
    "notes_area": (x0, y0, x1, y1),           # blank margin where a receiver would scribble "Bill-641"
    "paper": "white" | "cream" | "pink" | "yellow" | "green",
  }

Use bench.synth.hand for fonts (hand.font), handwriting (hand.hand_text) and pen marks.
"""
import importlib

TEMPLATES = ["gst_modern", "tally", "dotmatrix", "handbook", "software", "carbon"]


def get(name):
    return importlib.import_module(f"bench.synth.templates.{name}")
