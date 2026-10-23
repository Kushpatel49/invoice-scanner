import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from bench.score import (aggregate, align_rows, breakdowns, check_row, main, name_similarity, num, score_bill,
                         worst_bills)


def item(desc, qty, rate, tax=0, mode="exclusive"):
    """A truth row the way bench/synth/spec.py builds one."""
    taxable = round(qty * rate + 1e-9, 2)
    cgst = sgst = round(taxable * tax / 200 + 1e-9, 2)
    amount = round(taxable + cgst + sgst, 2) if mode == "inclusive" else taxable
    return {"description": desc, "hsn": "0709", "quantity": qty, "unit": "KGS", "rate": rate, "tax_percent": tax,
            "taxable": taxable, "cgst": cgst, "sgst": sgst, "amount": amount, "mrp": None}


def row(desc, qty, rate, amount):
    """A predicted row the way the scanner returns one."""
    return {"description": desc, "hsn": None, "quantity": qty, "unit": None, "rate": rate,
            "tax_percent": None, "amount": amount}


CARROT = item("CARROT OOTY", 3, 60)
BEANS = item("BEANS BUSH", 2.5, 96)
CABBAGE = item("CABBAGE", 4.25, 28)


def spec(items=None, **changes):
    items = copy.deepcopy(items if items is not None else [CARROT, BEANS, CABBAGE])
    total = round(sum(i["amount"] for i in items), 2)
    s = {"id": "syn001", "template": "gst_modern", "tax_mode": "exclusive",
         "supplier": {"name": "MALABAR FRESH FARMS PVT LTD", "gstin": "32AAACM1234F1Z5"},
         "invoice_number": "26-27/1064", "invoice_number_printed": "26-27/1064", "invoice_date": "2026-08-29",
         "items": items, "totals": {"subtotal": total, "grand_total": total}, "continued": False,
         "handwritten_items": False, "corrections": {"invoice_number": None, "quantity": None},
         "expected_review": False, "expected_review_reasons": [], "photo": {"difficulty": "easy", "rotate_deg": 0}}
    s.update(changes)
    return s


def result(s, rows=None, status="auto_ok", **changes):
    """A scanner result that reads spec `s` perfectly, unless rows/changes say otherwise."""
    if rows is None:
        rows = [row(i["description"].title(), i["quantity"], i["rate"], i["amount"]) for i in s["items"]]
    d = {"supplier": {"name": s["supplier"]["name"].title(), "gstin": s["supplier"].get("gstin"), "gstin_verified": True},
         "invoice_number": s["invoice_number"], "invoice_date": s["invoice_date"], "line_items": rows,
         "totals": {"grand_total": s["totals"]["grand_total"]},
         "_meta": {"status": status, "issues": [], "seconds": 10.0, "usage": {"cost_usd": 0.001}}}
    d.update(changes)
    return d


class Alignment(unittest.TestCase):
    def preds(self, items):
        return [row(i["description"], i["quantity"], i["rate"], i["amount"]) for i in items]

    def test_identical(self):
        al = align_rows(self.preds([CARROT, BEANS, CABBAGE]), [CARROT, BEANS, CABBAGE])
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(0, 0), (1, 1), (2, 2)])
        self.assertEqual((al["missed"], al["extra"]), ([], []))

    def test_missing_row(self):
        al = align_rows(self.preds([CARROT, CABBAGE]), [CARROT, BEANS, CABBAGE])
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(0, 0), (2, 1)])
        self.assertEqual((al["missed"], al["extra"]), ([1], []))

    def test_extra_duplicated_row(self):
        al = align_rows(self.preds([CARROT, CARROT, BEANS]), [CARROT, BEANS])
        self.assertEqual(len(al["pairs"]), 2)
        self.assertEqual((al["missed"], al["extra"]), ([], [1]))

    def test_reordered_rows_cost_one_missed_and_one_extra(self):
        # alignment keeps printed order, so a row read out of order is missed + extra
        al = align_rows(self.preds([CARROT, CABBAGE, BEANS]), [CARROT, BEANS, CABBAGE])
        self.assertEqual(len(al["pairs"]), 2)
        self.assertEqual((len(al["missed"]), len(al["extra"])), (1, 1))
        b = score_bill(result(spec(), self.preds([CARROT, CABBAGE, BEANS])), spec())
        self.assertEqual(b["reordered"], 1)
        self.assertTrue(any("out of order" in p for p in b["problems"]))
        self.assertFalse(b["items_perfect"])

    def test_duplicate_descriptions_told_apart_by_numbers(self):
        small, big = item("WHITE EGG PACK 6", 2, 50), item("WHITE EGG PACK 6", 5, 50)
        al = align_rows([row("White Egg Pack 6", 5, 50, 250)], [small, big])
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(1, 0)])
        self.assertEqual(al["missed"], [0])

    def test_near_identical_descriptions_told_apart_by_numbers(self):
        berry, mango = item("KUMBAYAH BERRY MIX 275 ML", 10, 104), item("KUMBAYAH MANGO 275ML", 6, 98)
        al = align_rows([row("KUMBAYAH MANGO 275ML", 6, 98, 588)], [berry, mango])
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(1, 0)])

    def test_numbers_pair_a_misread_description(self):
        al = align_rows([row("BEETRT 0OTY", 5, 40, 200)], [item("BEETROOT OOTY", 5, 40)])
        self.assertEqual(len(al["pairs"]), 1)

    def test_same_description_wrong_numbers_still_paired(self):
        al = align_rows([row("CARROT OOTY", 30, 6, 18)], [CARROT])
        self.assertEqual(len(al["pairs"]), 1)

    def test_unrelated_row_not_paired(self):
        al = align_rows([row("GARLIC (INDIAN)", 2, 200, 400)], [CARROT])
        self.assertEqual((al["pairs"], al["missed"], al["extra"]), ([], [0], [0]))

    def test_one_strong_pair_beats_two_weak(self):
        # pred[1] is truth row 1; pairing pred[0] with row 0 and pred[1] with row 1 is the only good answer
        gt = [item("CAPSICUM GREEN", 2, 70), item("CAPSICUM RED", 1.5, 180), item("CAPSICUM YELLOW", 1, 190)]
        al = align_rows(self.preds([gt[0], gt[2]]), gt)
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(0, 0), (2, 1)])

    def test_empty(self):
        self.assertEqual(align_rows([], []), {"pairs": [], "missed": [], "extra": []})
        self.assertEqual(align_rows([], [CARROT])["missed"], [0])
        self.assertEqual(align_rows(self.preds([CARROT]), [])["extra"], [0])

    def test_numbers_shifted_down_lookalike_rows_are_all_wrong(self):
        # each juice row read with the next row's qty, rate and amount: every item has the wrong price.
        # Pairing by numbers used to score this 5 of 6 right.
        gt = [item("KUMBAYAH BERRY MIX 275 ML", 10, 100, 5), item("KUMBAYAH BLACK DETOX 275ML", 6, 100, 5),
              item("KUMBAYAH MANGO 275ML", 12, 102, 5), item("KUMBAYAH PASSION BLOSSOM 275ML", 4, 104, 5),
              item("KUMBAYAH MANGO 275ML", 8, 102, 5), item("KUMBAYAH BERRY MIX 275 ML", 3, 100, 5)]
        nxt = gt[1:] + [item("X", 99, 1)]
        preds = [row(g["description"], n["quantity"], n["rate"], n["amount"]) for g, n in zip(gt, nxt)]
        al = align_rows(preds, gt)
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(i, i) for i in range(6)])
        b = score_bill(result(spec(gt), preds), spec(gt))
        self.assertEqual((b["matched"], b["price_perfect"]), (6, 0))

    def test_clear_description_beats_numbers(self):
        # PEAR RED and PEAR GREEN are 0.93 alike; the reader named each row exactly but shifted the numbers
        red, green = item("PEAR RED SOUTH AFRICA - 12.5 KG", 2, 4500), item("PEAR GREEN SOUTH AFRICA - 12.5 KG", 3, 4400)
        preds = [row(red["description"], 3, 4400, 13200), row(green["description"], 1, 1, 1)]
        al = align_rows(preds, [red, green])
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(0, 0), (1, 1)])
        self.assertEqual(score_bill(result(spec([red, green]), preds), spec([red, green]))["price_perfect"], 0)

    def test_garbled_handwriting_still_paired_by_numbers(self):
        gt = [item("CARROT OOTY", 3, 60), item("CABBAGE", 4.25, 28), item("BEANS BUSH", 2.5, 96),
              item("CURRY LEAVES", 0.5, 60)]
        preds = [row(d, g["quantity"], g["rate"], g["amount"]) for d, g in zip(["Cabbot", "Cabage", "Beens", "Cury leves"], gt)]
        al = align_rows(preds, gt)
        self.assertEqual([(g, p) for g, p, _ in al["pairs"]], [(0, 0), (1, 1), (2, 2), (3, 3)])

    def test_merged_rows_are_not_price_perfect(self):
        s = spec()
        merged = [row("CARROT OOTY BEANS BUSH", 5.5, 76.36, 420), row("Cabbage", 4.25, 28, 119)]
        b = score_bill(result(s, merged), s)
        self.assertEqual(b["price_perfect"], 1)
        self.assertGreaterEqual(b["missed"], 1)
        self.assertFalse(b["items_perfect"])
        self.assertTrue(b["silent_error"])


class RowChecks(unittest.TestCase):
    def test_exact(self):
        c = check_row(row("x", 3, 60, 180), CARROT)
        self.assertTrue(c["price_perfect"] and c["price_perfect_strict"])

    def test_tax_inclusive_rate_and_amount_accepted_on_exclusive_bill(self):
        gt = item("CURD 500 G SACHET", 2, 100, tax=5)          # amount 200 pre-tax
        c = check_row(row("curd", 2, 105, 210), gt)
        self.assertTrue(c["rate"] and c["amount"] and c["price_perfect"])
        self.assertFalse(c["amount_strict"])
        self.assertFalse(c["price_perfect_strict"])

    def test_taxable_amount_accepted_on_inclusive_bill(self):
        gt = item("FROZEN CHICKEN BONELESS BREAST", 20, 365, tax=5, mode="inclusive")   # amount 7665
        self.assertEqual(gt["amount"], 7665)
        self.assertTrue(check_row(row("x", 20, 365, 7665), gt)["price_perfect_strict"])
        c = check_row(row("x", 20, 365, 7300), gt)
        self.assertTrue(c["price_perfect"])
        self.assertFalse(c["price_perfect_strict"])
        self.assertTrue(check_row(row("x", 20, 383.25, 7665), gt)["rate"])

    def test_wrong_tax_rate_not_accepted(self):
        gt = item("CURD", 2, 100, tax=5)
        self.assertFalse(check_row(row("x", 2, 112, 224), gt)["amount"])
        self.assertFalse(check_row(row("x", 2, 112, 224), gt)["rate"])

    def test_tolerances(self):
        self.assertTrue(check_row(row("x", 3, 60, 180.01), CARROT)["amount"])
        self.assertFalse(check_row(row("x", 3, 60, 180.02), CARROT)["amount"])
        self.assertFalse(check_row(row("x", 3, 60, 180.01), CARROT)["amount_strict"])
        self.assertTrue(check_row(row("x", 3.001, 60, 180), CARROT)["qty"])
        self.assertFalse(check_row(row("x", 3.002, 60, 180), CARROT)["qty"])
        self.assertFalse(check_row(row("x", 3, 60.02, 180), CARROT)["rate"])

    def test_missing_and_string_values(self):
        self.assertFalse(check_row(row("x", 3, 60, None), CARROT)["amount"])
        self.assertFalse(check_row(row("x", None, 60, 180), CARROT)["qty"])
        self.assertTrue(check_row(row("x", "3", "60.00", "180.00"), CARROT)["price_perfect"])
        big = item("KIWI CRATE CHILE - 10 KG", 2, 3600)
        self.assertTrue(check_row(row("x", 2, "3,600.00", "7,200.00"), big)["price_perfect"])
        self.assertTrue(check_row(row("x", "2 Boxes", "Rs. 3,600", "7,200.00/-"), big)["price_perfect"])

    def test_number_strings_take_the_first_number(self):
        # digits used to be glued together: 'Rs. 120' -> 0.12, '4 Boxes (5 KG)' -> 45, '1e3' -> 13
        cases = {"4 Boxes": 4, "4 Boxes (5 KG)": 4, "Rs. 120": 120, "Rs.120": 120, "1e3": 1000, "2.5kg.": 2.5,
                 ".5 kg": 0.5, "1,23,456.50": 123456.5, "12/-": 12, "-3": -3, " 7 ": 7}
        for text, want in cases.items():
            self.assertEqual(num(text), want, text)
        for bad in ("NaN", "inf", float("nan"), float("inf"), "-", "", ".", "Nos", True, None):
            self.assertIsNone(num(bad), repr(bad))

    def test_tax_inclusive_rate_needs_a_tax_inclusive_amount(self):
        gt = item("CURD 500 G SACHET", 2, 100, tax=5)      # 2 x 100 = 200, 210 with GST
        mixed = check_row(row("x", 2, 105, 200), gt)       # 2 x 105 is not 200
        self.assertTrue(mixed["rate"] and mixed["amount"])
        self.assertFalse(mixed["price_perfect"] or mixed["price_perfect_strict"])
        self.assertTrue(check_row(row("x", 2, 105, 210), gt)["price_perfect"])
        self.assertTrue(check_row(row("x", 2, 100, 210), gt)["price_perfect"])     # pre-tax rate, amount with GST
        b = score_bill(result(spec([gt]), [row("Curd", 2, 105, 200)]), spec([gt]))
        self.assertTrue(b["silent_error"])
        self.assertTrue(any("includes tax but amount 200 does not" in p for p in b["problems"]))


class Header(unittest.TestCase):
    def test_gstin_none_means_none_expected(self):
        s = spec(supplier={"name": "NKA FRUITS", "gstin": None})
        self.assertTrue(score_bill(result(s), s)["header"]["gstin"])
        invented = result(s, supplier={"name": "NKA FRUITS", "gstin": "32AAHCG9621M1ZC"})
        self.assertFalse(score_bill(invented, s)["header"]["gstin"])

    def test_gstin_none_empty_or_absent_mean_the_same(self):
        for gt_sup in ({"name": "NKA FRUITS", "gstin": None}, {"name": "NKA FRUITS", "gstin": ""}, {"name": "NKA FRUITS"}):
            s = spec(supplier=gt_sup)
            for pred_sup in ({"name": "NKA FRUITS", "gstin": None}, {"name": "NKA FRUITS", "gstin": " "},
                             {"name": "NKA FRUITS"}):
                self.assertTrue(score_bill(result(s, supplier=pred_sup), s)["header"]["gstin"], (gt_sup, pred_sup))
            self.assertIn("no_gstin", score_bill(result(s), s)["flags"])

    def test_gstin_must_be_found_when_printed(self):
        s = spec()
        self.assertFalse(score_bill(result(s, supplier={"name": s["supplier"]["name"], "gstin": None}), s)["header"]["gstin"])
        spaced = result(s, supplier={"name": s["supplier"]["name"], "gstin": " 32aaacm1234f1z5 "})
        self.assertTrue(score_bill(spaced, s)["header"]["gstin"])

    def test_invoice_number_normalised(self):
        s = spec()
        self.assertTrue(score_bill(result(s, invoice_number="26-27 / 1064"), s)["header"]["invoice_number"])
        self.assertFalse(score_bill(result(s, invoice_number="26-27/1046"), s)["header"]["invoice_number"])
        self.assertFalse(score_bill(result(s, invoice_number=None), s)["header"]["invoice_number"])

    def test_corrected_invoice_number_must_be_the_new_one(self):
        s = spec(invoice_number="26-27/2001", invoice_number_printed="26-27/1064",
                 corrections={"invoice_number": {"printed": "26-27/1064", "new": "26-27/2001"}, "quantity": None})
        self.assertFalse(score_bill(result(s, invoice_number="26-27/1064"), s)["header"]["invoice_number"])
        self.assertIn("has_correction", score_bill(result(s), s)["flags"])

    def test_date_and_total(self):
        s = spec()
        self.assertFalse(score_bill(result(s, invoice_date="2026-29-08"), s)["header"]["date"])
        off = result(s, totals={"grand_total": s["totals"]["grand_total"] + 1})
        b = score_bill(off, s)
        self.assertFalse(b["header"]["grand_total"])
        self.assertFalse(b["bill_perfect"])
        self.assertTrue(b["items_perfect"])

    def test_supplier_name_fuzzy(self):
        s = spec()
        ok = result(s, supplier={"name": "M/s Malabar Fresh Farms Private Limited", "gstin": s["supplier"]["gstin"]})
        self.assertTrue(score_bill(ok, s)["header"]["supplier_name"])
        self.assertEqual(name_similarity("M/S.MALABAR FRESH FARMS PVT. LTD.", s["supplier"]["name"]), 1.0)
        wrong = result(s, supplier={"name": "Periyar Vegetable Company", "gstin": s["supplier"]["gstin"]})
        self.assertFalse(score_bill(wrong, s)["header"]["supplier_name"])

    def test_continued_page_skips_total(self):
        s = spec(continued=True, totals={k: None for k in ("subtotal", "grand_total")},
                 expected_review=True, expected_review_reasons=["continued"])
        b = score_bill(result(s, totals={"grand_total": None}, status="needs_review"), s)
        self.assertIsNone(b["header"]["grand_total"])
        self.assertTrue(b["bill_perfect"])
        self.assertIn("continued", b["flags"])
        # a total read from a continued page is not scored either
        self.assertTrue(score_bill(result(s, totals={"grand_total": 999.0}, status="needs_review"), s)["bill_perfect"])


class Bill(unittest.TestCase):
    def test_perfect_bill(self):
        b = score_bill(result(spec()), spec())
        self.assertTrue(b["bill_perfect"] and b["items_perfect"] and b["items_perfect_strict"])
        self.assertFalse(b["silent_error"])
        self.assertEqual(b["problems"], [])

    def test_wrong_amount_on_auto_ok_is_silent_error(self):
        s = spec()
        rows = result(s)["line_items"]
        rows[1]["amount"] = 249.0
        b = score_bill(result(s, rows), s)
        self.assertTrue(b["silent_error"])
        self.assertEqual(b["problems"][0], "AUTO_OK BUT WRONG")
        self.assertTrue(any("row 2" in p and "amount 249" in p for p in b["problems"]))
        self.assertEqual((b["matched"], b["price_perfect"]), (3, 2))
        self.assertFalse(score_bill(result(s, rows, status="needs_review"), s)["silent_error"])

    def test_extra_row_breaks_items_perfect(self):
        s = spec()
        rows = result(s)["line_items"] + [row("Garlic (Indian)", 1, 200, 200)]
        b = score_bill(result(s, rows), s)
        self.assertEqual(b["extra"], 1)
        self.assertEqual(b["price_perfect"], 3)
        self.assertFalse(b["items_perfect"])
        self.assertTrue(b["silent_error"])

    def test_auto_ok_on_bill_needing_review(self):
        s = spec(handwritten_items=True, expected_review=True, expected_review_reasons=["handwritten"])
        b = score_bill(result(s), s)
        self.assertTrue(b["missed_review"])
        self.assertFalse(b["silent_error"])     # data is right; the miss is reported separately
        self.assertIn("handwritten", b["problems"][0])

    def test_unnecessary_review(self):
        s = spec()
        self.assertTrue(score_bill(result(s, status="needs_review"), s)["unnecessary_review"])
        s2 = spec(expected_review=True, expected_review_reasons=["handwritten"])
        self.assertFalse(score_bill(result(s2, status="needs_review"), s2)["unnecessary_review"])

    def test_missing_result_fails_everything(self):
        s = spec(supplier={"name": "NKA FRUITS", "gstin": None})
        b = score_bill(None, s)
        self.assertTrue(b["missing"])
        self.assertEqual((b["missed"], b["matched"], b["status"]), (3, 0, "missing"))
        self.assertFalse(b["header"]["gstin"])  # no result is not the same as "no GSTIN"
        self.assertFalse(b["bill_perfect"] or b["auto_ok"] or b["silent_error"] or b["unnecessary_review"])

    def test_error_payloads_count_as_failed(self):
        s = spec(supplier={"name": "NKA FRUITS", "gstin": None})
        meta = {"seconds": 30.5, "usage": {"cost_usd": 0.002}}
        payloads = {"scanner error: JSONDecodeError": {"_raw": "{\"supplier\": {", "error": "JSONDecodeError", "_meta": meta},
                    "scanner returned unparsed output (_raw)": {"_raw": "I cannot read this bill", "_meta": meta},
                    "scanner error: status error": {"line_items": [], "_meta": {**meta, "status": "error"}},
                    "result has no line_items": {"supplier": {"name": "NKA FRUITS"}, "_meta": meta},
                    "result is not a JSON object": ["not", "a", "dict"]}
        for reason, payload in payloads.items():
            b = score_bill(payload, s)
            self.assertTrue(b["missing"], reason)
            self.assertEqual(b["problems"][0], reason)
            self.assertFalse(b["header"]["gstin"])      # an error is not "no GSTIN printed"
            self.assertFalse(b["auto_ok"] or b["silent_error"] or b["bill_perfect"])
        b = score_bill(payloads["scanner error: JSONDecodeError"], s)
        self.assertEqual((b["status"], b["missed"], b["cost_usd"], b["seconds"]), ("error", 3, 0.002, 30.5))
        self.assertEqual(worst_bills([b]), [])         # listed with the missing results instead
        # a good result that also keeps the raw model text is still a result
        self.assertTrue(score_bill({**result(s), "_raw": "..."}, s)["bill_perfect"])

    def test_malformed_fields_do_not_crash(self):
        s = spec()
        b = score_bill(result(s, supplier="MALABAR"), s)
        self.assertFalse(b["header"]["gstin"] or b["header"]["supplier_name"])
        self.assertFalse(score_bill(result(s, totals=[1]), s)["header"]["grand_total"])
        b = score_bill(result(s, _meta="auto_ok"), s)
        self.assertEqual((b["status"], b["auto_ok"], b["cost_usd"]), ("unknown", False, None))
        b = score_bill(result(s, _meta={"status": "auto_ok", "usage": 5, "issues": "x"}), s)
        self.assertEqual((b["auto_ok"], b["cost_usd"], b["issues"]), (True, None, []))
        self.assertEqual(score_bill(result(s, line_items={"a": 1}), s)["pred_rows"], 0)
        b = score_bill(result(s, result(s)["line_items"] + [None, "row"]), s)
        self.assertEqual((b["price_perfect"], b["extra"]), (3, 2))

    def test_empty_line_items_on_auto_ok_is_silent_error(self):
        s = spec()
        b = score_bill(result(s, []), s)
        self.assertEqual((b["matched"], b["missed"], b["extra"]), (0, 3, 0))
        self.assertTrue(b["silent_error"])
        self.assertFalse(b["missing"])

    def test_silent_error_is_exactly_auto_ok_and_not_bill_perfect(self):
        s, hand = spec(), spec(handwritten_items=True, expected_review=True, expected_review_reasons=["handwritten"])
        wrong = result(s)
        wrong["line_items"][0]["amount"] = 1
        cases = [(result(s), s), (wrong, s), (result(s, invoice_date="2026-08-30"), s), (result(hand), hand),
                 (result(s, status="needs_review"), s), (None, s), ({"_raw": "x", "_meta": {"status": "auto_ok"}}, s)]
        bills = [score_bill(p, sp) for p, sp in cases]
        for b in bills:
            self.assertEqual(b["silent_error"], b["auto_ok"] and not b["bill_perfect"])
        self.assertEqual([b["silent_error"] for b in bills], [False, True, True, False, False, False, False])
        self.assertEqual([b["missed_review"] for b in bills], [False, False, False, True, False, False, False])
        a = aggregate(bills)["safety"]
        self.assertEqual((a["auto_ok"], a["silent_errors"], a["auto_ok_correct"]), (4, 2, 2))
        self.assertEqual(a["auto_ok_precision"], 0.5)

    def test_flags(self):
        s = spec(handwritten_items=True, tax_mode="inclusive",
                 corrections={"invoice_number": None, "quantity": {"row": 0, "printed": 4, "new": 3}},
                 photo={"difficulty": "hard", "rotate_deg": 90, "stamp": {"over_table": True}, "underlay": True})
        b = score_bill(result(s), s)
        self.assertEqual(b["flags"], ["handwritten", "stamp_over_table", "rotated", "underlay", "has_correction",
                                      "tax_inclusive"])
        self.assertEqual(b["difficulty"], "hard")
        plain = spec(photo={"rotate_deg": 360, "stamp": {"over_table": False}, "underlay": {"enabled": False}})
        self.assertEqual(score_bill(result(plain), plain)["flags"], [])
        self.assertEqual(score_bill(result(plain), plain)["difficulty"], "n/a")

    def test_flags_from_build_py_photo_keys(self):
        # bench/build.py's manifest reads photo["stamp_over_table"] and photo["underlay_gstin"]
        s = spec(photo={"difficulty": "medium", "rotate_deg": 0, "stamp_over_table": True, "underlay_gstin": True},
                 supplier={"name": "NKA FRUITS", "gstin": None})
        self.assertEqual(score_bill(result(s), s)["flags"], ["stamp_over_table", "underlay", "no_gstin"])
        off = spec(photo={"stamp_over_table": False, "underlay_gstin": None})
        self.assertEqual(score_bill(result(off), off)["flags"], [])


class Aggregate(unittest.TestCase):
    def bills(self):
        s = spec()
        wrong = result(s)
        wrong["line_items"][0]["quantity"] = 30
        hand = spec(id="syn003", template="handbook", handwritten_items=True, expected_review=True,
                    expected_review_reasons=["handwritten"])
        return [score_bill(result(s), s), score_bill(wrong, s),
                score_bill(None, spec(id="syn002")), score_bill(result(hand, status="needs_review"), hand)]

    def test_counts(self):
        a = aggregate(self.bills(), inr=88)
        self.assertEqual((a["bills"], a["missing"], a["bill_perfect"]), (4, 1, 2))
        self.assertEqual(a["rows"]["truth"], 12)
        self.assertEqual(a["rows"]["missed"], 3)
        self.assertEqual(a["rows"]["price_perfect"], 8)
        self.assertAlmostEqual(a["rows"]["price_accuracy"], 8 / 12, places=4)
        s = a["safety"]
        self.assertEqual((s["auto_ok"], s["silent_errors"], s["missed_review"]), (2, 1, 0))
        self.assertEqual(s["auto_ok_precision"], 0.5)
        self.assertEqual(s["automation_rate"], 0.5)
        self.assertEqual(s["automation_ceiling"], 0.75)
        self.assertEqual(a["header"]["gstin"], {"ok": 3, "n": 4, "accuracy": 0.75})
        self.assertEqual(a["cost"]["bills_with_cost"], 3)
        self.assertAlmostEqual(a["cost"]["inr_total"], 0.264)
        self.assertEqual(a["latency"]["avg"], 10.0)

    def test_breakdowns_and_worst(self):
        bills = self.bills()
        br = breakdowns(bills)
        self.assertEqual(list(br["by_template"]), ["gst_modern", "handbook"])
        self.assertEqual(br["by_flag"]["handwritten"]["bills"], 1)
        self.assertEqual(br["by_flag"]["no flags"]["bills"], 3)
        worst = worst_bills(bills)
        self.assertEqual(len(worst), 1)            # missing bills are listed separately
        self.assertTrue(worst[0]["silent_error"])

    def test_empty(self):
        a = aggregate([])
        self.assertIsNone(a["rows"]["price_accuracy"])
        self.assertIsNone(a["safety"]["auto_ok_precision"])

    def test_p90_latency_is_nearest_rank(self):
        # it used to report 12 s here: index round(0.9 * 6) = 5 skipped the slowest of 7 bills
        s = spec()
        bills = [score_bill(result(s, _meta={"status": "auto_ok", "seconds": t}), s) for t in [12] * 6 + [30.5]]
        self.assertEqual(aggregate(bills)["latency"]["p90"], 30.5)
        bills = [score_bill(result(s, _meta={"status": "auto_ok", "seconds": t}), s) for t in range(1, 101)]
        self.assertEqual(aggregate(bills)["latency"]["p90"], 90)


class CommandLine(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(args))
        return code, out.getvalue()

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            gt, res = Path(tmp, "gt"), Path(tmp, "res")
            gt.mkdir()
            res.mkdir()
            a, b = spec(id="syn001"), spec(id="syn002", template="tally")
            for s in (a, b):
                (gt / f"{s['id']}.json").write_text(json.dumps(s))
            (gt / "manifest.json").write_text(json.dumps({"bills": 2}))     # not a spec: ignored
            (res / "syn001.json").write_text(json.dumps(result(a)))
            js, md = Path(tmp, "score.json"), Path(tmp, "report.md")

            code, text = self.run_main("--results", str(res), "--gt", str(gt), "--json", str(js), "--md", str(md))
            self.assertEqual(code, 1)                                       # a result is missing
            self.assertIn("missing or failed results (1): syn002 (no result file)", text)
            report = json.loads(js.read_text())
            self.assertEqual(report["overall"]["bills"], 2)
            self.assertEqual([m["id"] for m in report["missing"]], ["syn002"])
            self.assertIn("Silent errors", md.read_text())

            (res / "syn002.json").write_text(json.dumps(result(b)))
            code, text = self.run_main("--results", str(res), "--gt", str(gt))
            self.assertEqual(code, 0)
            self.assertIn("silent errors (auto_ok but wrong; must be 0): 0", text)

            wrong = result(b)
            wrong["line_items"][2]["rate"] = 82
            (res / "syn002.json").write_text(json.dumps(wrong))
            code, _ = self.run_main("--results", str(res), "--gt", str(gt), "--md", str(md))
            self.assertEqual(code, 1)
            self.assertIn("rate 82 (truth 28)", md.read_text())

    def test_error_payload_and_unreadable_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            gt, res = Path(tmp, "gt"), Path(tmp, "res")
            gt.mkdir()
            res.mkdir()
            a = spec(id="syn001")
            (gt / "syn001.json").write_text(json.dumps(a))
            (res / "syn001.json").write_text(json.dumps({"_raw": "{\"supplier\"", "error": "JSONDecodeError"}))
            js, md = Path(tmp, "score.json"), Path(tmp, "report.md")
            code, text = self.run_main("--results", str(res), "--gt", str(gt), "--json", str(js), "--md", str(md))
            self.assertEqual(code, 1)
            self.assertIn("syn001 (scanner error: JSONDecodeError)", text)
            self.assertEqual(json.loads(js.read_text())["bills"][0]["status"], "error")
            self.assertIn("## Missing or failed results (1)", md.read_text())

            # a truncated truth file must not silently drop the bill from the benchmark
            (res / "syn001.json").write_text(json.dumps(result(a)))
            (gt / "syn002.json").write_text(json.dumps(spec(id="syn002"))[:40])
            code, text = self.run_main("--results", str(res), "--gt", str(gt))
            self.assertEqual(code, 1)
            self.assertIn("unreadable truth files, not scored: syn002.json", text)


if __name__ == "__main__":
    unittest.main()
