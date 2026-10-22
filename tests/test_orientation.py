"""Offline check of page orientation on the evaluation photos (needs the tesseract binary)."""
import json
import shutil
import unittest
from pathlib import Path

from PIL import Image, ImageOps

from invoice_scanner import config
from invoice_scanner.ocr import orientation

EVAL = Path(__file__).resolve().parent.parent / "eval"


@unittest.skipUnless(shutil.which("tesseract"), "tesseract not installed")
class Orientation(unittest.TestCase):
    def test_eval_samples(self):
        truth = json.loads((EVAL / "ground_truth.json").read_text())
        for name, t in truth.items():
            img = ImageOps.exif_transpose(Image.open(EVAL / "samples" / f"{name}.jpg"))
            img.thumbnail((config.MAX_SIDE, config.MAX_SIDE))
            with self.subTest(bill=name):
                self.assertEqual(orientation(img), t["rotate_deg"])


if __name__ == "__main__":
    unittest.main()
