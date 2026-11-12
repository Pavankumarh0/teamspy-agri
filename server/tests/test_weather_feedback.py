"""Rain alert logic (offline) and the star feedback endpoint."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import weather  # noqa: E402

NOW = 1_800_000_000


def cur(main, rain=False):
    c = {"weather": [{"main": main, "description": main.lower()}], "main": {"temp": 27.6}}
    if rain:
        c["rain"] = {"1h": 0.5}
    return c


def fc(*pops):
    return [{"dt": NOW + 3600 * 3 * (i + 1), "pop": p, "weather": [{"main": "Rain" if p >= 0.5 else "Clouds"}]}
            for i, p in enumerate(pops)]


class RainAlertTests(unittest.TestCase):
    def test_raining_now(self):
        w = weather.summarize(cur("Rain", rain=True), fc(0.9, 0.2), NOW)
        self.assertEqual((w["alert"], w["message"]), (3, "Raining now"))

    def test_rain_likely_says_when(self):
        w = weather.summarize(cur("Clouds"), fc(0.1, 0.7, 0.2, 0), NOW)
        self.assertEqual(w["alert"], 2)
        self.assertIn("about 6 h (70%)", w["message"])

    def test_rain_possible(self):
        self.assertEqual(weather.summarize(cur("Clouds"), fc(0.35, 0, 0, 0), NOW)["alert"], 1)

    def test_no_rain(self):
        w = weather.summarize(cur("Clear"), fc(0, 0.1, 0, 0), NOW)
        self.assertEqual((w["alert"], w["rain_chance_12h"]), (0, 10))

    def test_rain_delays_urea_in_the_advice(self):
        w = {"ok": True, "alert": 2, "message": "Rain likely in about 3 h (70%)"}
        self.assertIn("Wait to apply urea", weather.advice(w)[0])
        self.assertEqual(weather.advice({"ok": False}), [])

    def test_no_key_no_call(self):
        os.environ["WEATHER_API_KEY"] = ""
        self.assertFalse(weather.get("bengaluru")["ok"])


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import dotenv
        dotenv.load_dotenv = lambda *a, **k: None
        os.environ.update({"EMBED_MODEL": "", "WEATHER_API_KEY": ""})
        import app
        app.FEEDBACK_FILE = Path(tempfile.mkdtemp()) / "fb.jsonl"
        from fastapi.testclient import TestClient
        cls.ctx = TestClient(app.app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_stars_are_stored_and_summarised(self):
        for stars, crop in ((5, "tomato"), (3, "tomato"), (4, "ragi")):
            r = self.c.post("/api/krishi/feedback", json={"stars": stars, "crop": crop, "area_acres": 1})
            self.assertEqual(r.status_code, 200)
        s = self.c.get("/api/krishi/feedback/summary").json()
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["by_crop"]["tomato"]["average_stars"], 4.0)

    def test_stars_must_be_1_to_5(self):
        for bad in (0, 6):
            self.assertEqual(self.c.post("/api/krishi/feedback", json={"stars": bad}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
