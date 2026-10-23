"""Map a scan result to the ERP's purchase-bill import format.

    from invoice_scanner.erp import to_erp
    payload = to_erp(scan_bill("bill.jpg"))

The ERP format (one bill):

    {"invoiceDetails": {"invoiceNo", "invoiceDate", "dueDate", "shippingDate", "supplierName",
                        "supplierMobileNo", "flatDiscount"},
     "productDetail": [{"itemCode", "name", "qty", "mrp", "sellingPrice", "landingCost", "purchasePrice",
                        "taxable", "tax", "total", "discount1Percentage", "discount2Percentage",
                        "discount1Amount", "discount2Amount"}]}

What comes from where:
  - purchasePrice  the row's rate before GST
  - taxable        qty x purchasePrice (the pre-GST line value)
  - tax            the row's GST amount (total - taxable)
  - total          the line total including GST
  - landingCost    total / qty: what one unit costs the store, GST included
  - The bill does not carry: itemCode (match against the ERP item master), sellingPrice (the store's
    own), dueDate / shippingDate, discounts (not extracted yet) - these are left "" or 0.0.
Bills only print one of the two GST conventions per row, so a row's printed amount is read as
tax-inclusive when qty x rate x (1 + GST%) gives it, and as the pre-GST value otherwise.
"""
import re

from .validate import gst_rate

DATE_FORMAT = "%Y-%m-%d"   # how invoiceDate is written; change to the ERP's format if it differs


def _r2(x):
    return round(float(x) + 1e-9, 2) if x is not None else 0.0


def _mobile(phone):
    """The supplier's 10-digit mobile number, or "" (landlines and unreadable numbers are left out)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 12 and digits.startswith("91"):
        digits = digits[2:]
    m = re.search(r"[6-9]\d{9}", digits)
    return m.group(0) if m else ""


def _mrp_in(text):
    """An MRP printed inside the description ('KUMBAYAH MANGO 275ML MRP 149/-'), else None."""
    m = re.search(r"\bMRP\s*[:.\-]?\s*(?:Rs\.?|₹)?\s*(\d+(?:\.\d+)?)", text or "", re.I)
    return float(m.group(1)) if m else None


def erp_row(it):
    """One item row in ERP form. Also returns whether its numbers checked out (qty x rate = amount)."""
    q, r, a = it.get("quantity"), it.get("rate"), it.get("amount")
    t = gst_rate(it.get("tax_percent")) or 0
    if None in (q, r, a) or q <= 0:
        taxable, tax, total, checked = _r2(a), 0.0, _r2(a), False
    else:
        tol = 0.011 + 0.005 * q + 0.0005 * r
        if t and abs(q * r * (1 + t / 100) - a) <= tol * (1 + t / 100):
            taxable, total, checked = _r2(q * r), _r2(a), True      # printed amount includes GST
            tax = _r2(total - taxable)
        else:
            taxable, checked = _r2(a), abs(q * r - a) <= max(tol, 0.5 if a == int(a) else 0)
            tax = _r2(taxable * t / 100)                             # printed amount is before GST
            total = _r2(taxable + tax)
    return {
        "itemCode": "",
        "name": it.get("description") or "",
        "qty": q if q is not None else 0,
        "mrp": _r2(it.get("mrp") if it.get("mrp") is not None else _mrp_in(it.get("description"))),
        "sellingPrice": 0.0,
        "landingCost": _r2(total / q) if q else 0.0,
        "purchasePrice": _r2(r),
        "taxable": taxable,
        "tax": tax,
        "total": total,
        "discount1Percentage": 0.0,
        "discount2Percentage": 0.0,
        "discount1Amount": 0.0,
        "discount2Amount": 0.0,
    }, checked


def to_erp(result):
    """The ERP import payload for one scanned bill (see the module docstring)."""
    from datetime import date
    inv_date = result.get("invoice_date")
    try:
        inv_date = date.fromisoformat(inv_date).strftime(DATE_FORMAT) if inv_date else ""
    except ValueError:
        inv_date = ""
    supplier = result.get("supplier") or {}
    return {
        "invoiceDetails": {
            "invoiceNo": result.get("invoice_number") or "",
            "invoiceDate": inv_date,
            "dueDate": "",
            "shippingDate": "",
            "supplierName": supplier.get("name") or "",
            "supplierMobileNo": _mobile(supplier.get("phone")),
            "flatDiscount": 0.0,
        },
        "productDetail": [erp_row(it)[0] for it in result.get("line_items") or []],
    }
