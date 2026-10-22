import copy
import unittest

from invoice_scanner.validate import validate

CLEAN = {
    "supplier": {"name": "R K MERCANTILE", "gstin": "32AGVPR6347Q2ZA", "gstin_verified": True},
    "invoice_number": "26-27/1064",
    "invoice_date": "2026-08-29",
    "is_handwritten": False,
    "continued_on_next_page": False,
    "header_corrected": False,
    "amount_in_words": "Seven Thousand Six Hundred Sixty Five Rupees only",
    "line_items": [{"description": "FROZEN Chicken Boneless Breast", "quantity": 20, "rate": 365,
                    "tax_percent": 5, "amount": 7665}],
    "totals": {"subtotal": 7300, "cgst": 182.5, "sgst": 182.5, "igst": None, "cess": None,
               "round_off": None, "grand_total": 7665},
}


def bill(**changes):
    d = copy.deepcopy(CLEAN)
    for k, v in changes.items():
        d[k] = v
    return d


class Validate(unittest.TestCase):
    def assertIssue(self, d, fragment):
        issues = validate(d)
        self.assertTrue(any(fragment in i for i in issues), f"expected '{fragment}' in {issues}")

    def test_clean_bill_has_no_issues(self):
        self.assertEqual(validate(bill()), [])

    def test_row_arithmetic(self):
        d = bill()
        d["line_items"][0]["rate"] = 1500
        self.assertIssue(d, "line 1")

    def test_total_vs_words(self):
        d = bill()
        d["totals"]["grand_total"] = 7656
        self.assertIssue(d, "amount in words")

    def test_continued_page(self):
        self.assertIssue(bill(continued_on_next_page=True), "continues on another page")

    def test_handwritten_always_reviewed(self):
        self.assertIssue(bill(is_handwritten=True), "handwritten bill")

    def test_header_correction(self):
        self.assertIssue(bill(header_corrected=True), "corrected by hand")

    def test_gstin_missing_or_unverified(self):
        self.assertIssue(bill(supplier={"name": "x", "gstin": None, "gstin_verified": False}), "GSTIN not found")
        self.assertIssue(bill(supplier={"name": "x", "gstin": "32AGYPR6347Q2ZA", "gstin_verified": False}),
                         "fails checksum")

    def test_dates(self):
        self.assertIssue(bill(invoice_date="29/08/26"), "date unreadable")
        self.assertIssue(bill(invoice_date="2016-08-29"), "implausible date")

    def test_no_items(self):
        self.assertIssue(bill(line_items=[]), "no line items")


if __name__ == "__main__":
    unittest.main()
