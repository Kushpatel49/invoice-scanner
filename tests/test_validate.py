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
                         "not confirmed")

    def test_missing_date(self):
        self.assertIssue(bill(invoice_date=None), "invoice date missing")

    def test_header_checks_are_passed_through(self):
        self.assertEqual(validate(bill(), ["invoice number unclear: read as 'A' and 'B'"]),
                         ["invoice number unclear: read as 'A' and 'B'"])

    def test_no_items(self):
        self.assertIssue(bill(line_items=[]), "no line items")


if __name__ == "__main__":
    unittest.main()


from datetime import date

from invoice_scanner.validate import (decide_date, decide_invoice_number, dates_in_text, fy_range, is_receiver_ref,
                                      parse_date_dayfirst, row_ok, serial_problem, split_series, sum_check)

TODAY = date(2026, 10, 23)


class RowRule(unittest.TestCase):
    def test_exact_and_rounded(self):
        self.assertTrue(row_ok(20, 365, 7665, 5))            # GST-inclusive amount
        self.assertTrue(row_ok(15, 102.17, 1609.20, 5))      # rate printed rounded (real SH Foods bill)
        self.assertTrue(row_ok(6.2, 149, 923.8, 0))
        self.assertTrue(row_ok(5, 46, 230, None))            # cash bill
        self.assertTrue(row_ok(2.5, 41, 103, None))          # 102.5 rounded to a whole rupee

    def test_misreads_caught(self):
        self.assertFalse(row_ok(3, 1292.04, 4080, 5))        # real Almova bill: 1295.24 misread under the stamp
        self.assertFalse(row_ok(1, 271.9, 284.55, 5))        # 271 read as 271.9
        self.assertFalse(row_ok(10.15, 140, 1421.70, 0))     # qty 10.155 read as 10.15
        self.assertFalse(row_ok(-1, 10, 10, 0))
        self.assertFalse(row_ok(1, 10, None, 0))

    def test_half_rate_means_full_gst(self):
        self.assertTrue(row_ok(15, 31.24, 492.03, 2.5))      # CGST 2.5% printed -> 5% GST

    def test_sum_with_row_tax_when_header_tax_missing(self):
        items = [{"amount": 2180.8, "tax_percent": 0}, {"amount": 987, "tax_percent": 0},
                 {"amount": 445.56, "tax_percent": 0}, {"amount": 468.6, "tax_percent": 5},
                 {"amount": 214.3, "tax_percent": 5}]
        self.assertEqual(sum_check(items, {"grand_total": 4330}), (True, None))   # real Muralya bill
        items[3]["tax_percent"] = items[4]["tax_percent"] = 0
        self.assertFalse(sum_check(items, {"grand_total": 4330})[0])

    def test_sum_inclusive_rows_and_subtotal(self):
        self.assertTrue(sum_check([{"amount": 7665, "tax_percent": 5}], {"grand_total": 7665, "subtotal": 7300})[0])
        rows = [{"amount": 100.40, "tax_percent": 0}, {"amount": 49.80, "tax_percent": 0}]
        # rounded to Rs 150 without a printed round off: the printed subtotal must confirm the rows
        self.assertTrue(sum_check(rows, {"grand_total": 150, "subtotal": 150.20})[0])
        self.assertTrue(sum_check(rows, {"grand_total": 150})[0])
        ok, msg = sum_check(rows, {"grand_total": 150, "subtotal": 160})
        self.assertFalse(ok)
        self.assertIn("subtotal", msg)

    def test_sum_tight_when_round_off_known(self):
        items = [{"amount": 100.40, "tax_percent": 0}]
        self.assertTrue(sum_check(items, {"grand_total": 100, "round_off": -0.40})[0])
        self.assertFalse(sum_check(items, {"grand_total": 101, "round_off": -0.40})[0])

    def test_serials(self):
        mk = lambda *sls: [{"sl": s} for s in sls]
        self.assertIsNone(serial_problem(mk(1, 2, 3)))
        self.assertIsNone(serial_problem(mk(1, None, 3)))     # serials not printed everywhere: skip
        self.assertIn("jump", serial_problem(mk(1, 2, 4)))
        self.assertIn("jump", serial_problem(mk(1, 2, 2)))


class InvoiceNumber(unittest.TestCase):
    def test_book_series_and_receiver_notes(self):
        self.assertEqual(split_series("26-27 c 5207"), ("5207", "26-27 c"))
        self.assertEqual(split_series("26-27/1064"), ("26-27/1064", None))
        self.assertTrue(is_receiver_ref("BIL-604"))
        self.assertTrue(is_receiver_ref("661", ["Bil 661"]))
        self.assertFalse(is_receiver_ref("B1/FS/011218"))

    def test_consensus(self):
        self.assertEqual(decide_invoice_number("26-27/1064", "26-27/1064", ""), ("26-27/1064", None, None))
        # dropped digit: OCR prints exactly one of the two reads
        self.assertEqual(decide_invoice_number("TI-8430", "TI-84340", "Invoice No. TI-84340")[0], "TI-84340")
        num, _, issue = decide_invoice_number("COK26-27/1835", "COKD-26/1835", "")
        self.assertIn("unclear", issue)
        # the model took the receiver's pen note; the zoomed read has the printed number
        self.assertEqual(decide_invoice_number("BIL-604", "26-27/7922", ""), ("26-27/7922", None, None))
        self.assertIn("not confirmed", decide_invoice_number("6697", None, "")[2])


class Dates(unittest.TestCase):
    def test_parse_day_first(self):
        for s, d in [("29/08/26", date(2026, 8, 29)), ("29-Aug-2026", date(2026, 8, 29)),
                     ("29.08.2026", date(2026, 8, 29)), ("31|8", date(2026, 8, 31)), ("1/9/26", date(2026, 9, 1)),
                     ("2026-08-29", date(2026, 8, 29)), ("24/08/26 15:06", date(2026, 8, 24))]:
            self.assertEqual(parse_date_dayfirst(s, TODAY), d, s)

    def test_ocr_dates_and_fy(self):
        self.assertEqual(dates_in_text("Date 30-Aug-2026 / 29/08/26 Ph 9846 123 456", TODAY),
                         {date(2026, 8, 30), date(2026, 8, 29)})
        self.assertEqual(fy_range("26-27/1064"), (date(2026, 4, 1), date(2027, 3, 31)))

    def test_consensus(self):
        self.assertEqual(decide_date("2026-08-29", "29/08/26", "29-08-2026", "", None, TODAY), ("2026-08-29", None))
        # the model converted 25/08 to May; the zoomed read and OCR agree on August
        self.assertEqual(decide_date("2026-05-25", "25/05/26", "25/08/26", "Dt 25/08/2026", None, TODAY)[0], "2026-08-25")
        self.assertIn("not confirmed", decide_date("2026-08-29", "29/08/26", None, "", None, TODAY)[1])
        self.assertIn("financial year", decide_date(None, "29/03/26", "29/03/26", "", "26-27/1064", TODAY)[1])


from invoice_scanner.extract import drop_repeated_block


class RepeatedBlock(unittest.TestCase):
    def test_table_output_twice_is_cut(self):
        r = lambda d, a: {"description": d, "quantity": 1, "rate": a, "amount": a}
        rows = [r("a", 1), r("b", 2), r("c", 3), r("d", 4)]
        self.assertEqual(drop_repeated_block(rows + rows), (rows, True))
        self.assertEqual(drop_repeated_block(rows), (rows, False))


from invoice_scanner.validate import in_ocr_tokens


class OcrTokens(unittest.TestCase):
    def test_whole_tokens_only(self):
        ocr = "Ph 98681 23456 Invoice No 9688 / COK26-27 / 1835"
        self.assertFalse(in_ocr_tokens("9868", ocr))       # only inside a phone number
        self.assertTrue(in_ocr_tokens("9688", ocr))
        self.assertTrue(in_ocr_tokens("COK26-27/1835", ocr))   # split by OCR into adjacent tokens
        self.assertEqual(decide_invoice_number("9868", "9688", ocr)[0], "9688")

    def test_plausible_date_wins(self):
        self.assertEqual(decide_date(None, "30/08/26", "30/08/28", "", None, TODAY)[0], "2026-08-30")


class InvoiceNumberEdgeCases(unittest.TestCase):
    def test_wrapped_number_never_confirms_the_short_read(self):
        # real R K Mercantile bill: "Invoice No.: 26-" / "27/1064" wraps onto two lines
        num, _, issue = decide_invoice_number("27/1064", "26-27/1064", "Invoice No.: 26-\nDate 27/1064")
        self.assertEqual(num, "26-27/1064")
        self.assertIn("unclear", issue)
        self.assertEqual(decide_invoice_number("27/1064", "26-27/1064", "No. 26-27/1064")[2], None)

    def test_handwritten_replacement_is_not_tie_broken_by_ocr(self):
        # OCR only sees the struck-out printed number; the reads differ by more than a slip
        num, _, issue = decide_invoice_number("COK26-27/9208", "COK26-27/1969", "COK26-27/1969")
        self.assertIn("unclear", issue)
