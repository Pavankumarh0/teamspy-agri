"""Smart Krishi server tests. Gemma is mocked; retrieval runs for real on kb/
with TF-IDF only (no network)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

# Keep the developer's .env out of the tests: no network embeddings, temp store.
import dotenv  # noqa: E402
dotenv.load_dotenv = lambda *a, **k: None
_tmp = tempfile.mkdtemp()
os.environ.update({"EMBED_MODEL": "", "LLM_BACKEND": "gemini", "SOIL_MOCK": "1", "TTS_ENABLED": "1",
                   "TFIDF_MIN_SCORE": "0.10", "SOIL_STORE": os.path.join(_tmp, "soil.json"),
                   "KRISHI_SENSOR_KEY": "", "SARVAM_API_KEY": "", "STT_PROVIDER": "sarvam"})

from fastapi.testclient import TestClient  # noqa: E402
import app as krishi  # noqa: E402
import soil  # noqa: E402


def gemma(reply):
    return mock.patch.object(krishi.llm, "generate", mock.AsyncMock(return_value=reply))


class KrishiApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(krishi.app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        soil._latest.clear()
        krishi.LAST_Q.clear()

    def ask(self, q):
        r = self.c.post("/api/krishi/chat", json={"question": q, "session": self._testMethodName})
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_health(self):
        h = self.c.get("/api/krishi/health").json()
        self.assertTrue(h["ok"])
        self.assertEqual(h["app"], "Smart Krishi")
        self.assertGreater(h["chunks"], 20)

    def test_grounded_answer_is_returned_with_its_source(self):
        reply = ("Tomato needs nitrogen for leaf growth, phosphorus for roots and flowering, and potassium for fruit "
                 "quality. The exact fertilizer quantities depend on your soil test, so follow your Soil Health Card."
                 "\nSOURCES: 05_tomato_cultivation.md")
        with gemma(reply) as g:
            r = self.ask("Which fertilizer is suitable for tomato cultivation?")
        self.assertTrue(r["in_scope"])
        self.assertIn("05_tomato_cultivation.md", r["sources"])
        self.assertNotIn("SOURCES", r["answer"])
        self.assertIn("[05_tomato_cultivation.md]", g.call_args.args[0])   # retrieved into the prompt
        self.assertTrue(r["audio_id"])

    def test_invented_fertilizer_quantity_is_rejected(self):
        with gemma("Apply 120 kg of urea per acre to tomato.\nSOURCES: 05_tomato_cultivation.md"):
            r = self.ask("How much urea should I give tomato?")
        self.assertFalse(r["in_scope"])
        self.assertEqual(r["answer"], krishi.DONT_KNOW)
        self.assertEqual(r["via"], "ungrounded")

    def test_not_in_kb_gives_the_not_enough_information_reply(self):
        with gemma("NOT_IN_KB"):
            r = self.ask("What is the market price of tomato today?")
        self.assertEqual(r["answer"], krishi.DONT_KNOW)
        self.assertIn("enough verified information", r["answer"])

    def test_off_topic_question_never_reaches_gemma(self):
        with gemma("should not be called") as g:
            r = self.ask("Who won the cricket world cup?")
        g.assert_not_called()
        self.assertEqual(r["answer"], krishi.DONT_KNOW)

    def test_gemma_down_falls_back_to_verbatim_kb_text(self):
        with mock.patch.object(krishi.llm, "generate", mock.AsyncMock(side_effect=RuntimeError("down"))):
            r = self.ask("What causes blossom end rot in tomato?")
        self.assertEqual(r["via"], "kb-direct")
        self.assertIn("blossom end rot", r["answer"].lower())
        self.assertIn("06_tomato_leaf_problems.md", r["sources"] + ["05_tomato_cultivation.md"])

    def test_soil_question_gets_a_labelled_mock_reading(self):
        with gemma("NOT_IN_KB") as g:
            r = self.ask("When should I water my crops? Is the soil dry?")
        prompt = g.call_args.args[0]
        self.assertIn("[soil_sensor.md]", prompt)
        self.assertIn("MOCK READING (simulated, not a real measurement)", prompt)
        self.assertEqual(r["sensor"]["source"], "mock")

    def test_real_reading_replaces_the_mock_and_is_labelled_real(self):
        body = {"device_id": "krishi_sensor_01", "soil_moisture": 31, "crop": "tomato", "temperature": 29, "humidity": 60}
        self.assertEqual(self.c.post("/api/krishi/soil-data", json=body).status_code, 200)
        latest = self.c.get("/api/krishi/soil-data/latest").json()
        self.assertFalse(latest["is_mock"])
        self.assertEqual(latest["reading"]["soil_moisture"], 31)
        with gemma("NOT_IN_KB") as g:
            self.ask("What is the soil moisture now?")
        context = g.call_args.args[0].split("CONTEXT:", 1)[1]
        self.assertIn("REAL SENSOR READING", context)
        self.assertIn("Soil moisture: 31 percent", context)
        self.assertNotIn("MOCK READING", context)

    def test_mock_reading_is_flagged_when_nothing_real_arrived(self):
        latest = self.c.get("/api/krishi/soil-data/latest").json()
        self.assertTrue(latest["is_mock"])
        self.assertEqual(latest["reading"]["source"], "mock")

    def test_no_mock_and_no_reading_is_404(self):
        with mock.patch.dict(os.environ, {"SOIL_MOCK": "0"}):
            self.assertEqual(self.c.get("/api/krishi/soil-data/latest").status_code, 404)

    def test_soil_data_validation_and_device_key(self):
        bad = {"device_id": "x y", "soil_moisture": 140}
        self.assertEqual(self.c.post("/api/krishi/soil-data", json=bad).status_code, 422)
        good = {"device_id": "krishi_sensor_01", "soil_moisture": 40}
        with mock.patch.dict(os.environ, {"KRISHI_SENSOR_KEY": "s3cret"}):
            self.assertEqual(self.c.post("/api/krishi/soil-data", json=good).status_code, 401)
            ok = self.c.post("/api/krishi/soil-data", json=good, headers={"X-Device-Key": "s3cret"})
            self.assertEqual(ok.status_code, 200)

    def test_stale_reading_is_marked(self):
        rec = soil.save({"device_id": "krishi_sensor_01", "soil_moisture": 40})
        rec["received_at"] = "2020-01-01T00:00:00+00:00"
        self.assertIn("STALE", soil.as_context(rec)["text"])

    def test_greeting(self):
        self.assertEqual(self.ask("Namaskara")["answer"], krishi.META["greeting"])

    def test_spoken_units(self):
        self.assertIn("kilograms per hectare", krishi.for_speech("50 kg/ha"))


class KnowledgeBaseSeparationTests(unittest.TestCase):
    def test_kb_holds_no_campus_documents(self):
        kb = SERVER.parent / "kb"
        text = " ".join(p.read_text(encoding="utf-8").lower() for p in kb.glob("*.md"))
        for word in ("oxford", "hostel", "admission", "placement", "campus"):
            self.assertNotIn(word, text)

    def test_kb_states_no_fertilizer_doses(self):
        import re
        kb = SERVER.parent / "kb"
        for p in kb.glob("*.md"):
            self.assertIsNone(re.search(r"\d+\s*(kg|g|ml|l|t|tonnes?)\b", p.read_text(encoding="utf-8"), re.I), p.name)


if __name__ == "__main__":
    unittest.main()
