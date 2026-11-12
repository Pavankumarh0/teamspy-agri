"""kiosk_text: Kannada/Hindi bitmaps for the TFT - geometry must match the firmware."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import kiosk_text as kt  # noqa: E402


@unittest.skipUnless(kt.available(), "uharfbuzz / freetype-py / Nirmala UI font not available")
class KioskTextTests(unittest.TestCase):
    Q = "ಟೊಮೆಟೊ ಬೆಳೆಗೆ ಯಾವ ಗೊಬ್ಬರ ಸೂಕ್ತ?"
    A = ("Tomato-ಗೆ leaf and vine growth-ಗೆ nitrogen ಬೇಕಾಗುತ್ತೆ, strong roots and flowering-ಗೆ phosphorus "
         "ಬೇಕಾಗುತ್ತೆ, and fruit size and quality-ಗೆ potassium ಬೇಕಾಗುತ್ತೆ.")

    def test_detects_kannada_and_hindi_only(self):
        self.assertTrue(kt.has_indic(self.Q))
        self.assertTrue(kt.has_indic("टमाटर"))
        self.assertFalse(kt.has_indic("Tomato needs nitrogen."))

    def test_rows_are_the_firmware_width(self):
        q = kt.render_question(self.Q)
        self.assertTrue(all(len(r) == (kt.TEXT_W + 7) // 8 for r in q))      # GFX_BPR = 21
        self.assertLessEqual(len(q), 60)                                       # GFX_Q_MAX_H

    def test_pages_fit_under_the_question(self):
        q = kt.render_question(self.Q)
        pages, page_h = kt.render_answer(self.A, len(q))
        self.assertEqual(page_h, kt.FOOT_Y - 2 - (kt.Q_TOP + len(q) + kt.ANSWER_GAP))
        self.assertLessEqual(page_h, 170)                                      # GFX_A_MAX_H
        self.assertTrue(1 <= len(pages) <= kt.MAX_PAGES)
        self.assertTrue(all(len(p) == page_h for p in pages))
        self.assertTrue(any(any(r) for r in pages[0]))                         # something was drawn

    def test_long_answers_are_capped_at_max_pages(self):
        pages, _ = kt.render_answer(self.A * 20, 46)
        self.assertEqual(len(pages), kt.MAX_PAGES)

    def test_shaping_combines_vowel_signs(self):
        # "ಕೆ" is one consonant + one vowel sign: shaped into fewer glyphs than
        # a naive one-glyph-per-character renderer would draw side by side.
        r = kt.Renderer(18)
        infos, _ = r._shape("ಬೆಳೆಗೆ")
        self.assertLess(len(infos), len("ಬೆಳೆಗೆ"))


if __name__ == "__main__":
    unittest.main()
