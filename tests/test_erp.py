import unittest

from invoice_scanner.erp import _mobile, erp_row, to_erp


class ErpRows(unittest.TestCase):
    def test_tax_inclusive_amount(self):
        # R K Mercantile: 20 kg x 365, 5% GST, printed amount 7,665 includes the GST
        row, ok = erp_row({"description": "FROZEN CHICKEN", "quantity": 20, "rate": 365, "tax_percent": 5, "amount": 7665})
        self.assertTrue(ok)
        self.assertEqual((row["purchasePrice"], row["taxable"], row["tax"], row["total"], row["landingCost"]),
                         (365.0, 7300.0, 365.0, 7665.0, 383.25))

    def test_pre_gst_amount_gets_its_tax_added(self):
        row, ok = erp_row({"description": "PLUM CAKE", "quantity": 41, "rate": 165, "tax_percent": 18, "amount": 6765})
        self.assertTrue(ok)
        self.assertEqual((row["taxable"], row["tax"], row["total"]), (6765.0, 1217.7, 7982.7))

    def test_no_gst_row(self):
        row, ok = erp_row({"description": "CARROT", "quantity": 27, "rate": 57, "tax_percent": None, "amount": 1539})
        self.assertEqual((row["taxable"], row["tax"], row["total"], row["landingCost"]), (1539.0, 0.0, 1539.0, 57.0))
        self.assertTrue(ok)

    def test_row_that_does_not_check_out(self):
        _, ok = erp_row({"description": "X", "quantity": 3, "rate": 1292.04, "tax_percent": 5, "amount": 4080})
        self.assertFalse(ok)


class ErpBill(unittest.TestCase):
    def test_header_and_shape(self):
        payload = to_erp({"invoice_number": "26-27/1064", "invoice_date": "2026-08-29",
                          "supplier": {"name": "R K MERCANTILE", "phone": "Ph: +91 98465 64422"},
                          "line_items": [{"description": "A", "quantity": 1, "rate": 10, "amount": 10}]})
        d = payload["invoiceDetails"]
        self.assertEqual((d["invoiceNo"], d["invoiceDate"], d["supplierMobileNo"]), ("26-27/1064", "2026-08-29", "9846564422"))
        self.assertEqual(set(payload["productDetail"][0]), {
            "itemCode", "name", "qty", "mrp", "sellingPrice", "landingCost", "purchasePrice", "taxable", "tax",
            "total", "discount1Percentage", "discount2Percentage", "discount1Amount", "discount2Amount"})

    def test_mobile_numbers(self):
        self.assertEqual(_mobile("0484 2966081"), "")          # a landline is not a mobile
        self.assertEqual(_mobile("9946564422, 7012155041"), "9946564422")


class Mrp(unittest.TestCase):
    def test_mrp_from_description(self):
        row, _ = erp_row({"description": "KUMBAYAH MANGO 275ML MRP 149/-", "quantity": 15, "rate": 102.17,
                          "tax_percent": 5, "amount": 1609.2})
        self.assertEqual(row["mrp"], 149.0)
        self.assertEqual(erp_row({"description": "CARROT", "quantity": 1, "rate": 2, "amount": 2})[0]["mrp"], 0.0)
