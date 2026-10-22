import random
import string
import unittest

from invoice_scanner.gstin import gstin_candidates, gstin_ok, repair_gstin

# Real GSTINs printed on the sample bills
REAL = ["32AAHCG9621M1ZC", "32AAGCM9238D1ZL", "32AGVPR6347Q2ZA", "32BZNPV6872Q1Z5",
        "32AVQPJ5385G2Z9", "32AAPCA0115L1ZX", "32ADPFS4356R1Z8", "32CHKPM3220R1Z3",
        "32BFLPC3943R1Z3", "32AAQCA8177P1ZU"]


class GstinOk(unittest.TestCase):
    def test_real_gstins_pass(self):
        for g in REAL:
            self.assertTrue(gstin_ok(g), g)

    def test_single_character_error_fails(self):
        self.assertFalse(gstin_ok("32AAHCG9621M1ZD"))   # wrong check character
        self.assertFalse(gstin_ok("32AGYPR6347Q2ZA"))   # V misread as Y (seen in testing)

    def test_bad_state_code_fails(self):
        self.assertFalse(gstin_ok("00AAHCG9621M1ZC"))
        self.assertFalse(gstin_ok("45AAHCG9621M1ZC"))

    def test_empty_and_malformed(self):
        for g in (None, "", "32AAHCG9621M1Z", "not a gstin at all"):
            self.assertFalse(gstin_ok(g))


class Repair(unittest.TestCase):
    def test_lookalikes_fixed_by_position(self):
        self.assertEqual(repair_gstin("32AVQPJS385G2Z9"), "32AVQPJ5385G2Z9")   # S read for 5
        self.assertEqual(repair_gstin("32AAHCG962IM1ZC"), "32AAHCG9621M1ZC")   # I read for 1


class Candidates(unittest.TestCase):
    def test_finds_in_ocr_text(self):
        text = "i GSTIN:32AVQPJS385G2Z9 _\nGSTIN : 32AGVPR6347Q2ZA"
        self.assertEqual(gstin_candidates(text), ["32AVQPJ5385G2Z9", "32AGVPR6347Q2ZA"])

    def test_split_across_two_words(self):
        self.assertEqual(gstin_candidates("GSTIN: 32AAHCG9621 M1ZC"), ["32AAHCG9621M1ZC"])

    def test_not_stitched_across_three_words(self):
        self.assertEqual(gstin_candidates("32AAHCG 9621 M1ZC"), [])

    def test_too_many_repairs_rejected(self):
        # three look-alike substitutions needed -> not trusted
        self.assertEqual(gstin_candidates("32AVQPJS3BSG2Z9"), [])

    def test_random_noise_rarely_matches(self):
        # Guards the false-positive rate measured during development (~1 per 230 pages).
        rng = random.Random(1)
        chars = string.ascii_uppercase + string.digits * 3
        text = " ".join("".join(rng.choice(chars) for _ in range(rng.randint(2, 12))) for _ in range(50000))
        pages = len(text.replace(" ", "")) / 3000
        self.assertLess(len(gstin_candidates(text)) / pages, 0.02)


if __name__ == "__main__":
    unittest.main()
