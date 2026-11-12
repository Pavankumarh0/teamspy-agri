"""Market price lookup (AGMARKNET via data.gov.in), offline with a fake API,
and the fertilizer safety warning."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fertilizer  # noqa: E402
import prices  # noqa: E402

REC = [{"state": "Karnataka", "district": "Kolar", "market": "Kolar", "commodity": "Tomato", "variety": "Local",
        "arrival_date": "12/11/2026", "min_price": "800", "max_price": "1500", "modal_price": "1200"},
       {"state": "Karnataka", "district": "Bangalore", "market": "Binny Mill (F&V)", "commodity": "Tomato",
        "variety": "Hybrid", "arrival_date": "12/11/2026", "min_price": "1000", "max_price": "1800",
        "modal_price": "1400"},
       {"state": "Karnataka", "district": "Mysore", "market": "Mysore", "commodity": "Tomato", "variety": "",
        "arrival_date": "12/11/2026", "min_price": "", "max_price": "", "modal_price": "0"}]


class FindCropTests(unittest.TestCase):
    def test_price_questions(self):
        self.assertEqual(prices.find_crop("What is the current rate of tomato?"), "tomato")
        self.assertEqual(prices.find_crop("onions price in mandi today"), "onion")
        self.assertEqual(prices.find_crop("green chilli rate"), "green chilli")
        self.assertEqual(prices.find_crop("mirchi ka bhav"), "chilli")
        self.assertTrue(prices.is_price_question("What is the market price of ragi today?"))
        self.assertTrue(prices.is_price_question("tell me the market prize of tomatoes ?"))
        self.assertEqual(prices.find_crop("tell me the market prize of tomatoes ?"), "tomato")
        self.assertTrue(prices.is_price_question("tamatar ka bhav kya hai"))

    def test_not_price_questions(self):
        self.assertFalse(prices.is_price_question("How much urea for tomato?"))
        self.assertFalse(prices.is_price_question("What is the price of urea?"))
        self.assertFalse(prices.is_price_question("tomato leaves are yellow"))


class GetTests(unittest.TestCase):
    def setUp(self):
        prices._CACHE.clear()

    def test_no_key(self):
        with mock.patch.dict(os.environ, {"DATA_GOV_IN_API_KEY": ""}):
            p = prices.get("tomato")
        self.assertEqual(p, {"ok": False, "reason": "no_key"})
        self.assertIn("not set up", prices.unavailable_message(p))

    def test_prices_from_state_markets_prefers_district(self):
        with mock.patch.dict(os.environ, {"DATA_GOV_IN_API_KEY": "test"}), \
                mock.patch.object(prices, "_query", return_value=REC) as q:
            p = prices.get("tomato", "Karnataka", "Bangalore Urban")
        q.assert_called_once_with("test", "Tomato", "Karnataka")
        self.assertTrue(p["ok"])
        self.assertEqual(p["scope"], "state")
        self.assertEqual([m["market"] for m in p["markets"]], ["Binny Mill (F&V)", "Kolar"])   # zero price dropped
        text = prices.as_context(p)
        self.assertIn("usual (modal) price 1400 rupees, lowest 1000, highest 1800 rupees per quintal", text)
        self.assertIn("12/11/2026", text)
        self.assertIn("100 kilograms", text)

    def test_falls_back_to_india(self):
        calls = []

        def fake(key, commodity, state):
            calls.append(state)
            return [] if state else REC[:1]
        with mock.patch.dict(os.environ, {"DATA_GOV_IN_API_KEY": "test"}), mock.patch.object(prices, "_query", fake):
            p = prices.get("tomato")
        self.assertEqual(calls, ["Karnataka", None])
        self.assertEqual(p["scope"], "india")
        self.assertIn("in India", prices.as_context(p))

    def test_service_error(self):
        with mock.patch.dict(os.environ, {"DATA_GOV_IN_API_KEY": "test"}), \
                mock.patch.object(prices, "_query", side_effect=RuntimeError("quota")):
            p = prices.get("onion")
        self.assertEqual(p["reason"], "error")
        self.assertIn("could not reach", prices.unavailable_message(p))


class SafetyWarningTests(unittest.TestCase):
    def test_every_fertilizer_page_ends_with_the_safety_footer(self):
        _, pages = fertilizer.screen_pages(fertilizer.recommend("tomato", 1))
        for pg in pages:
            self.assertEqual(pg[-1], ("F", fertilizer.SAFETY_WARNING))

    def test_warning_is_one_short_sentence(self):
        w = fertilizer.SAFETY_WARNING
        self.assertLessEqual(len(w), 95)                       # fits one kiosk screen line buffer
        self.assertEqual(w.count("."), 1)
        for word in ("Pregnant", "children", "elderly"):
            self.assertIn(word, w)


if __name__ == "__main__":
    unittest.main()
