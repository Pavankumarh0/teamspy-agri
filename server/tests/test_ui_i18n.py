"""Screen-text translation (ui_i18n) and the fertilizer explanations."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["UI_TRANSLATION_CACHE"] = os.path.join(tempfile.mkdtemp(), "ui.json")
import fertilizer  # noqa: E402
import ui_i18n  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class UiI18nTests(unittest.TestCase):
    def setUp(self):
        ui_i18n._cache = None

    def test_numbers_become_placeholders_and_come_back(self):
        tpl, nums = ui_i18n.template("Urea 98 kg, DAP 44.5 kg")
        self.assertEqual(tpl, "Urea {0} kg, DAP {1} kg")
        self.assertEqual(ui_i18n.fill("ಯೂರಿಯಾ {0} ಕೆ.ಜಿ, ಡಿಎಪಿ {1} ಕೆ.ಜಿ", nums), "ಯೂರಿಯಾ 98 ಕೆ.ಜಿ, ಡಿಎಪಿ 44.5 ಕೆ.ಜಿ")
        self.assertIsNone(ui_i18n.fill("ಯೂರಿಯಾ ಕೆ.ಜಿ", nums))      # a lost number -> not used

    def test_overrides_win_and_take_numbers(self):
        fake = mock.AsyncMock(side_effect=RuntimeError("offline"))
        with mock.patch.object(ui_i18n.language, "from_english", fake):
            out = run(ui_i18n.translate(["Sensor online", "raw 16363 - probe in air / dry?"], "kn"))
        self.assertEqual(out[0], "ಸೆನ್ಸಾರ್ ಆನ್‌ಲೈನ್")
        self.assertIn("16363", out[1])
        self.assertTrue(out[1].startswith("ಕಚ್ಚಾ"))
        fake.assert_not_called()

    def test_machine_translation_is_cached_per_template(self):
        fake = mock.AsyncMock(return_value=("ಯೂರಿಯಾ {0} ಕೆ.ಜಿ", ""))
        with mock.patch.object(ui_i18n.language, "from_english", fake):
            a = run(ui_i18n.translate(["Urea 98 kg"], "kn"))
            b = run(ui_i18n.translate(["Urea 12 kg"], "kn"))
        self.assertEqual((a[0], b[0]), ("ಯೂರಿಯಾ 98 ಕೆ.ಜಿ", "ಯೂರಿಯಾ 12 ಕೆ.ಜಿ"))
        self.assertEqual(fake.await_count, 1)

    def test_failure_falls_back_to_english(self):
        with mock.patch.object(ui_i18n.language, "from_english", mock.AsyncMock(side_effect=RuntimeError("x"))):
            self.assertEqual(run(ui_i18n.translate(["Choose a crop first"], "hi")), ["Choose a crop first"])

    def test_english_and_numbers_pass_through(self):
        self.assertEqual(run(ui_i18n.translate(["Humidity"], "en")), ["Humidity"])
        with mock.patch.object(ui_i18n.language, "from_english", mock.AsyncMock()) as f:
            self.assertEqual(run(ui_i18n.translate(["28.5"], "kn")), ["28.5"])
            f.assert_not_called()

    def test_overrides_file_is_valid_and_complete(self):
        o = ui_i18n.overrides()
        self.assertEqual(set(o), {"kn", "hi"})
        self.assertEqual(set(o["kn"]), set(o["hi"]))


class FertilizerWhyTests(unittest.TestCase):
    def test_each_used_product_is_explained(self):
        r = fertilizer.recommend("tomato", 1)
        self.assertEqual([p["product"] for p in r["product_why"]], ["urea", "dap", "mop"])
        self.assertIn("nitrogen", r["product_why"][0]["what"].lower())

    def test_unused_product_is_not_explained(self):
        r = fertilizer.recommend("tomato", 1, n="high", region="other")
        r["totals"]["mop_kg"] = 0                       # e.g. a crop without potash
        title, pages = fertilizer.screen_pages(r)
        self.assertEqual(pages[1][0], ("H", "Why these fertilizers"))

    def test_explanations_match_the_knowledge_base_roles(self):
        kb = (Path(__file__).resolve().parents[2] / "kb" / "03_fertilizers_and_nutrients.md").read_text(encoding="utf-8")
        self.assertIn("Nitrogen (N) supports leaf and stem growth", kb)
        self.assertIn("Phosphorus (P) supports root growth, flowering", kb)
        self.assertIn("Potassium (K) supports fruit quality and size, water regulation and resistance to stress", kb)


if __name__ == "__main__":
    unittest.main()
