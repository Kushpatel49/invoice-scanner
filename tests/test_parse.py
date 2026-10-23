import unittest

from invoice_scanner.extract import parse_items, parse_num


class ParseNum(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_num("1,609.20"), 1609.2)
        self.assertEqual(parse_num("₹ 7,665.00"), 7665.0)
        self.assertEqual(parse_num("4 Boxes"), 4.0)
        self.assertIsNone(parse_num(""))
        self.assertIsNone(parse_num("-"))
        self.assertIsNone(parse_num("3,8?0.00"))   # unreadable digit


class ParseItems(unittest.TestCase):
    def test_basic_rows_with_serials(self):
        text = ("INK: printed\n"
                "COLUMNS: Sl | Description of Goods | Quantity | Rate | Amount\n"
                "sl | description | hsn | qty | unit | rate | tax% | amount\n"
                "1 | BLACK GRAPES_CHINA | | 4 | Boxes | 1,700.00 | | 6,800.00\n"
                "2 | Goosberry (Pack) | | 15 | PACK | 260 | | 3900\n"
                "END\n"
                "9 | garbage after END | | 1 | | 1 | | 1")
        items, info = parse_items(text)
        self.assertEqual([it["sl"] for it in items], [1, 2])
        self.assertEqual((items[0]["quantity"], items[0]["rate"], items[0]["amount"]), (4, 1700, 6800))
        self.assertIsNone(items[0]["hsn"])
        self.assertEqual(info["ink"], "printed")
        self.assertTrue(info["columns"].startswith("Sl"))

    def test_markdown_and_missing_serial(self):
        text = ("| 1 | BLACK GRAPES | 0806 | 4 | Boxes | 1,700.00 | | 6,800.00 |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "White Egg | | 10 | Pack | 48 | | 480\n"
                "Row 3: 3 | KIWI | | 3 | Box | 3800 | | 11400")
        items, _ = parse_items(text)
        self.assertEqual([it["description"] for it in items], ["BLACK GRAPES", "White Egg", "KIWI"])
        self.assertEqual([it["sl"] for it in items], [1, None, 3])

    def test_trailing_empty_field_does_not_shift_columns(self):
        items, _ = parse_items("4 | EMPTY ROW | 0407 | | | | |\n5 | Nadan Egg - 6 | 0407 | 10 | | 55 | | 550")
        self.assertEqual([i["description"] for i in items], ["Nadan Egg - 6"])   # blank template row skipped

    def test_unreadable_digit_marks_row(self):
        items, _ = parse_items("1 | KIWI | | 3 | Box | 3,8?0.00 | | 11,400.00")
        self.assertTrue(items[0]["unreadable"])
        self.assertIsNone(items[0]["rate"])

    def test_loop_is_cut(self):
        row = "1 | KUMBAYAH MANGO | 2202992 | 15 | Nos | 102.17 | 5 | 1609.20\n"
        items, info = parse_items(row * 50)
        self.assertEqual(len(items), 2)
        self.assertTrue(info["looped"])

    def test_malformed_rows_counted(self):
        items, info = parse_items("A | B\n1 | x | | 1 | | 2 | | 2 | extra | fields")
        self.assertEqual(items, [])
        self.assertEqual(info["malformed"], 2)


if __name__ == "__main__":
    unittest.main()


from invoice_scanner.extract import map_columns, merge_reads, pair_reads, parse_rate_cell, parse_table


def heads(line):
    hs = [h.strip() for h in line.split("|")]
    m = map_columns(hs)
    return {k: (hs[v] if isinstance(v, int) else [hs[i] for i in v]) for k, v in m.items() if v not in (None, [])}


class TableRead(unittest.TestCase):
    def test_column_mapping_on_real_layouts(self):
        m = heads("Sl | Description Of Goods | HSN | UOM | QTY | Rate | INCL Rate | Less Discount | Taxable Value | "
                  "GST % | CGST Amount | SGST Amount | Cess Amount | Total")          # Almova carbon copy
        self.assertEqual((m["qty"], m["rate"], m["amount"], m["tax_rate"]), ("QTY", "Rate", "Total", ["GST %"]))
        m = heads("No | Description of Goods | HSN Code (GST) | Qty | UOM | Rate | Total | CGST Rate | CGST Amount | "
                  "SGST Rate | SGST Amount")                                           # Muralya
        self.assertEqual((m["hsn"], m["amount"], m["tax_rate"]), ("HSN Code (GST)", "Total", ["CGST Rate", "SGST Rate"]))
        self.assertEqual(heads("Sl. No. | Description | Quantity Shipped | Billed | Rate | Per | Amount")["qty"], "Billed")
        m = heads("Item | Rate | Qty | Amount Rs. | Amount Ps.")
        self.assertEqual((m["amount"], m["paise"]), ("Amount Rs.", "Amount Ps."))
        self.assertEqual(heads("# | Item name | Quantity | Price/ unit | GST | Amount")["sl"], "#")
        self.assertIsNone(map_columns(["Particulars", "Remarks"]))

    def test_rate_cells(self):
        self.assertEqual([parse_rate_cell(x) for x in ["5%", "2.5", "365.00 (5%)", "1666.67", ""]],
                         [5.0, 2.5, 5.0, None, None])

    def test_parse_table_without_columns_prefix_and_with_paise(self):
        items, info = parse_table("INK: pen\nItem | Rate | Qty | Amount Rs. | Amount Ps.\n"
                                  "Lemon | 92 | 10.937 | 1,006 | 20\nDrumstick | 131 | 8 | 1,048 | -\nEND")
        self.assertEqual([(i["quantity"], i["rate"], i["amount"]) for i in items], [(10.937, 92, 1006.20), (8, 131, 1048)])
        self.assertEqual(info["ink"], "pen")

    def test_parse_table_skips_prose_and_maps_tax(self):
        text = ("Let me read the table.\nCOLUMNS: Sl | Description | Qty | Rate | CGST Rate | SGST Rate | Amount\n"
                "1 | CURD 500 G | 15 | 31.24 | 2.5% | 2.5% | 468.60\nEND")
        items, _ = parse_table(text)
        self.assertEqual((items[0]["sl"], items[0]["tax_percent"], items[0]["amount"]), (1, 5.0, 468.6))


def row(sl, desc, q, r, a, t=None):
    return {"sl": sl, "description": desc, "quantity": q, "rate": r, "amount": a, "tax_percent": t}


class MergeReads(unittest.TestCase):
    def test_pairing(self):
        a = [row(None, "CARROT OOTY", 1, 1, 1), row(None, "BEETROOT", 1, 1, 1), row(None, "CABBAGE", 1, 1, 1)]
        b = [row(None, "Carrot Ooty", 1, 1, 1), row(None, "Cabbage", 1, 1, 1)]
        self.assertEqual(pair_reads(a, b), {0: 0, 2: 1})
        self.assertEqual(pair_reads([row(2, "x", 1, 1, 1)], [row(1, "y", 1, 1, 1), row(2, "z", 1, 1, 1)]), {0: 1})

    def test_failing_row_fixed_by_other_read(self):
        ok1, ok2 = row(1, "KALE", 9, 20, 180), row(3, "LEEKS", 1.5, 210, 315)
        a = [ok1, row(2, "TAPIOCA", 21, 30, 840), ok2]      # 8 read as 1: fails qty x rate = amount
        b = [ok1, row(2, "TAPIOCA", 28, 30, 840), ok2]
        rows, conflicts, fixed, agreed, swapped = merge_reads(a, b)
        self.assertEqual((rows[1]["quantity"], conflicts, fixed, agreed, swapped), (28, [], [2], [1, 3], False))

    def test_two_consistent_reads_that_disagree_are_a_conflict(self):
        a = [row(1, "CARROT", 12, 57, 684)]       # self-consistent but wrong
        b = [row(1, "CARROT", 27, 57, 1539)]
        self.assertEqual(merge_reads(a, b)[1], [1])

    def test_one_dissenting_read_does_not_overrule_two_agreeing(self):
        a = [row(1, "CARROT", 27, 57, 1539)]
        z = [row(1, "CARROT", 21, 57, 1197)]      # a third (zoomed) read misreads 7 as 1
        self.assertEqual(merge_reads(a, z, confirmed={1})[1], [])

    def test_better_read_becomes_primary(self):
        a = [row(None, "junk", 1, 2, 9), row(None, "junk2", 1, 2, 9)]
        b = [row(1, "PLUM CAKE", 41, 165, 6765), row(2, "RUSK", 33, 37, 1221)]
        rows, _, _, _, swapped = merge_reads(a, b)
        self.assertTrue(swapped)
        self.assertEqual([r["description"] for r in rows], ["PLUM CAKE", "RUSK"])


class IndianNumberForms(unittest.TestCase):
    def test_rupees_only_mark_and_prefixes(self):
        self.assertEqual([parse_num(x) for x in ["1892/-", "4,922/-", "Rs.230/-", "₹ 1,609.20", "230=", "-0.47"]],
                         [1892.0, 4922.0, 230.0, 1609.2, 230.0, -0.47])

    def test_quantity_with_decimal_comma(self):
        from invoice_scanner.extract import decimal_qty
        self.assertEqual(decimal_qty("9,000", "184.00", "1854.72", "12"), 9.0)   # printed 9.000
        self.assertEqual(decimal_qty("1,200", "5", "6000"), 1200.0)              # a real thousands comma


from invoice_scanner.extract import final_block


class ThinkingAloud(unittest.TestCase):
    def test_only_the_final_answer_is_parsed(self):
        reply = ("The user wants me to extract the table.\n**1. Draft:**\n1 | CARROT | | 27 | KG | 57 | | 1539\n"
                 "Let me double check row 1.\nINK: printed\n1 | CARROT | | 27 | KG | 57 | | 1539\n"
                 "2 | BEANS | | 7 | KG | 90 | | 630\nEND")
        items, _ = parse_items(reply)
        self.assertEqual([i["description"] for i in items], ["CARROT", "BEANS"])

    def test_last_run_of_rows_without_ink_line(self):
        reply = "Draft:\n1 | A | | 1 | | 2 | | 2\nOK, final:\n1 | A | | 1 | | 2 | | 2\n2 | B | | 1 | | 3 | | 3\nEND"
        self.assertEqual(final_block(reply).count("|"), 14)
