from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class Python312CompatibilityTests(unittest.TestCase):
    def test_pillow_pin_has_python312_wheels(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("Pillow==12.3.0", requirements)

    def test_drawing_does_not_use_removed_font_getsize(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("font.getsize(", source)
        self.assertNotIn("Image.ANTIALIAS", source)
        self.assertIn("draw.textbbox(", source)
        self.assertIn("Image.Resampling.LANCZOS", source)


if __name__ == "__main__":
    unittest.main()
