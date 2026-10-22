import unittest

from invoice_scanner.extract import item_problems, parse_items, parse_num


class ParseNum(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_num("1,609.20"), 1609.2)
        self.assertEqual(parse_num("₹ 7,665.00"), 7665.0)
        self.assertEqual(parse_num("4 Boxes"), 4.0)
        self.assertIsNone(parse_num(""))
        self.assertIsNone(parse_num("-"))


class ParseItems(unittest.TestCase):
    def test_basic_rows(self):
        text = ("description | hsn | qty | unit | rate | tax% | amount\n"
                "1. BLACK GRAPES_CHINA | | 4 | Boxes | 1,700.00 | | 6,800.00\n"
                "Goosberry (Pack) | | 15 | PACK | 260 | | 3900\n"
                "END\n"
                "garbage after END | | 1 | | 1 | | 1")
        items = parse_items(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["description"], "BLACK GRAPES_CHINA")   # serial number stripped
        self.assertEqual((items[0]["quantity"], items[0]["rate"], items[0]["amount"]), (4, 1700, 6800))
        self.assertIsNone(items[0]["hsn"])

    def test_blank_template_rows_skipped(self):
        text = ("White Chicken Eggs - 6 | 0407 | 10 | | 48 | | 480\n"
                "White Chicken Eggs - 30 | 0407 | | | | | \n"
                "Nadan Egg - 6 | 0407 | 10 | | 55 | | 550")
        self.assertEqual([i["description"] for i in parse_items(text)], ["White Chicken Eggs - 6", "Nadan Egg - 6"])

    def test_loop_is_cut(self):
        row = "KUMBAYAH MANGO | 2202992 | 15 | Nos | 102.17 | 5 | 1609.20\n"
        self.assertEqual(len(parse_items(row * 50)), 2)

    def test_short_lines_ignored(self):
        self.assertEqual(parse_items("Here is the table:\nA | B\n"), [])


class ItemProblems(unittest.TestCase):
    def item(self, q, r, a, t=None):
        return {"description": "x", "quantity": q, "rate": r, "amount": a, "tax_percent": t}

    def test_consistent_bill(self):
        items = [self.item(20, 365, 7665, 5)]   # GST-inclusive amount
        self.assertEqual(item_problems(items, {"grand_total": 7665}), [])

    def test_bad_row_and_sum(self):
        items = [self.item(4, 1500, 18000), self.item(1, 100, 100)]
        probs = item_problems(items, {"grand_total": 30000})
        self.assertTrue(any("row 1" in p for p in probs))
        self.assertTrue(any("sum to" in p for p in probs))

    def test_continued_page_skips_sum_check(self):
        items = [self.item(1, 100, 100)]
        self.assertEqual(item_problems(items, {"grand_total": 999, "continued_on_next_page": True}), [])


if __name__ == "__main__":
    unittest.main()
