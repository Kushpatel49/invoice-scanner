import unittest

from invoice_scanner.validate import words_to_number


class WordsToNumber(unittest.TestCase):
    CASES = {
        "INR Rupees Twenty Six Thousand Seven Hundred Sixty Six Only": 26766,
        "INR Fifty One Thousand Only": 51000,
        "Nine Thousand Nine Hundred Ten INDIAN RUPEES Only": 9910,
        "Rupees One thousand Eight hundred and fifty nine only": 1859,
        "INR Four thousand, three hundred and thirty only": 4330,
        "Rupees Two Thousand and Ninety Four only": 2094,
        "One Lakh Three Thousand Eight Hundred and Fifty Rupees and Twenty Paise": 103850,
        "Two Crore Five Lakh Only": 20500000,
        "Seven Thousand Six Hundred Sixty Five Rupees only": 7665,
    }

    def test_cases(self):
        for text, expected in self.CASES.items():
            self.assertEqual(words_to_number(text), expected, text)

    def test_nothing_numeric(self):
        self.assertIsNone(words_to_number(None))
        self.assertIsNone(words_to_number(""))
        self.assertIsNone(words_to_number("Rupees only"))


if __name__ == "__main__":
    unittest.main()
