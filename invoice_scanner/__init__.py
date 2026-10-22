"""Scan photographed purchase bills into validated, ERP-ready JSON.

    from invoice_scanner import scan_bill
    result = scan_bill("bill.jpg")
    if result["_meta"]["status"] == "auto_ok":
        ...  # safe to post; otherwise show result["_meta"]["issues"] to a reviewer
"""
from .pipeline import scan_bill

__version__ = "0.1.0"
__all__ = ["scan_bill", "__version__"]
