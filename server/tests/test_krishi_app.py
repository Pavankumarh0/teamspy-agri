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
TOKEN = "test-device-token"
os.environ.update({"EMBED_MODEL": "", "LLM_BACKEND": "gemini", "TTS_ENABLED": "1", "KRISHI_SENSOR_TOKEN": TOKEN,
                   "TFIDF_MIN_SCORE": "0.10", "SENSOR_STORE": os.path.join(_tmp, "sensors.json"),
                   "SENSOR_STALE_S": "30", "SENSOR_OFFLINE_S": "120",
                   "KRISHI_SENSOR_KEY": "", "SARVAM_API_KEY": "", "STT_PROVIDER": "sarvam", "WEATHER_API_KEY": ""})

from fastapi.testclient import TestClient  # noqa: E402
import app as krishi  # noqa: E402
import sensors  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402


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
        sensors.reset()
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
            r = self.ask("Which tractor brand is the best to buy?")
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

    # --- sensors -------------------------------------------------------------

    PAYLOAD = {"device_id": "unoq_soil_01", "temperature_c": 28.5, "humidity_percent": 31,
               "soil_moisture_raw": 16363, "soil_moisture_percent": None, "mq135_raw": 1748,
               "soil_sensor_valid": False}
    AUTH = {"Authorization": f"Bearer {TOKEN}"}

    def post(self, body=None, headers=None):
        return self.c.post("/api/krishi/sensors", json=body or self.PAYLOAD,
                           headers=self.AUTH if headers is None else headers)

    def test_sensor_payload_from_the_spec_is_accepted_and_returned(self):
        self.assertEqual(self.post().status_code, 200)
        r = self.c.get("/api/krishi/sensors/latest").json()
        self.assertEqual(r["status"], "online")
        self.assertEqual(r["reading"]["temperature_c"], 28.5)
        self.assertEqual(r["reading"]["mq135_raw"], 1748)
        self.assertFalse(r["valid"]["soil_moisture"])
        self.assertTrue(r["valid"]["temperature"])
        self.assertIn("server_time", r)
        self.assertLess(r["age_seconds"], 5)

    def test_sensor_auth(self):
        self.assertEqual(self.post(headers={}).status_code, 401)
        self.assertEqual(self.post(headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.post(headers={"X-Device-Token": TOKEN}).status_code, 200)
        with mock.patch.dict(os.environ, {"KRISHI_SENSOR_TOKEN": ""}):
            self.assertEqual(self.post().status_code, 503)       # never open when unconfigured

    def test_sensor_validation(self):
        for bad in ({"humidity_percent": 140}, {"device_id": "bad id"}, {"soil_moisture_raw": -1},
                    {"temperature_c": 200}, {"unknown_field": 1}):
            self.assertEqual(self.post({**self.PAYLOAD, **bad}).status_code, 422, bad)

    def test_nulls_are_allowed_and_percent_needs_a_valid_sensor(self):
        body = {"device_id": "unoq_soil_01", "temperature_c": None, "humidity_percent": None,
                "soil_moisture_raw": None, "mq135_raw": None, "soil_moisture_percent": 55, "soil_sensor_valid": False}
        self.assertEqual(self.post(body).status_code, 200)
        r = self.c.get("/api/krishi/sensors/latest").json()
        self.assertIsNone(r["reading"]["soil_moisture_percent"])  # dropped: sensor not valid
        self.assertFalse(any(r["valid"].values()))

    def test_no_data_status(self):
        r = self.c.get("/api/krishi/sensors/latest").json()
        self.assertEqual(r["status"], "no_data")
        self.assertIsNone(r["reading"])

    def test_stale_and_offline_status_and_context(self):
        now = datetime.now(timezone.utc)
        for secs, want, word in ((10, "online", None), (60, "stale", "STALE"), (600, "offline", "OFFLINE")):
            sensors.reset()
            rec = sensors.save(dict(self.PAYLOAD), now=now - timedelta(seconds=secs))
            self.assertEqual(sensors.status(rec, now), want)
            if word:
                self.assertIn(word, sensors.as_context(rec, now))

    def test_reading_survives_a_restart(self):
        self.post()
        sensors._latest.clear()
        sensors._loaded = False                                   # as after a restart
        self.assertEqual(sensors.latest()["mq135_raw"], 1748)

    def test_farm_question_gets_sensor_section_separate_from_documents(self):
        self.post()
        reply = ("The air temperature is 28.5 degrees Celsius and humidity is 31 percent. The soil moisture "
                 "sensor is not calibrated yet, so the soil water level cannot be assessed reliably."
                 "\nSOURCES: live_sensors")
        with gemma(reply) as g:
            r = self.ask("How is my farm today?")
        prompt = g.call_args.args[0]
        live = prompt.split("LIVE SENSOR READINGS:\n", 1)[1].split("KNOWLEDGE DOCUMENTS:\n")[0]
        docs = prompt.split("KNOWLEDGE DOCUMENTS:\n", 1)[1]
        self.assertIn("Air temperature: 28.5 degrees Celsius", live)
        self.assertIn("not calibrated", live)
        self.assertNotIn("1748", live)                          # raw MQ-135 is never offered as a value
        self.assertNotIn("Air temperature", docs)
        self.assertEqual(r["via"], "gemma")
        self.assertIn("live_sensors", r["sources"])
        self.assertIn("28.5", r["answer"])

    def test_invented_sensor_value_is_rejected(self):
        self.post()
        with gemma("The soil moisture is 42 percent, so your soil is fine.\nSOURCES: live_sensors"):
            r = self.ask("What is the soil moisture now?")
        self.assertEqual(r["via"], "ungrounded")

    def test_farm_question_without_any_reading_says_so(self):
        with gemma("should not be called") as g:
            r = self.ask("How is my farm today?")
        g.assert_not_called()
        self.assertEqual(r["answer"], krishi.NO_SENSOR_DATA)

    def test_test_data_is_labelled(self):
        self.post({**self.PAYLOAD, "is_test_data": True})
        self.assertIn("TEST DATA", sensors.as_context(sensors.latest()))
        self.assertTrue(self.c.get("/api/krishi/sensors/latest").json()["is_test_data"])

    def test_greeting(self):
        self.assertEqual(self.ask("Namaskara")["answer"], krishi.META["greeting"])

    def test_kiosk_loudness_raises_level_and_keeps_headroom_for_firmware_gain(self):
        import numpy as np
        t = np.arange(16000) / 16000
        x = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
        with mock.patch.dict(os.environ, {"KIOSK_LOUDNESS": "6"}):
            y = np.frombuffer(krishi.kiosk_loud(x.tobytes()), dtype="<i2").astype(np.float32)
        rms = lambda a: float(np.sqrt(np.mean(np.asarray(a, np.float32) ** 2)))
        after_fw = np.clip(y * 2, -32768, 32767)                    # firmware SPEAKER_GAIN 2
        before_fw = np.clip(x.astype(np.float32) * 2, -32768, 32767)
        self.assertGreater(rms(after_fw), rms(before_fw))
        self.assertLessEqual(np.abs(y).max(), 16384)                # half scale: x2 never hard-clips
        with mock.patch.dict(os.environ, {"KIOSK_LOUDNESS": "0"}):
            self.assertEqual(krishi.kiosk_loud(x.tobytes()), x.tobytes())

    def test_spoken_units(self):
        self.assertIn("kilograms per hectare", krishi.for_speech("50 kg/ha"))


class KnowledgeBaseSeparationTests(unittest.TestCase):
    def test_kb_holds_no_campus_documents(self):
        kb = SERVER.parent / "kb"
        text = " ".join(p.read_text(encoding="utf-8").lower() for p in kb.glob("*.md"))
        for word in ("oxford", "hostel", "admission", "placement", "campus"):
            self.assertNotIn(word, text)

    DOSE_FILE = "09_recommended_fertilizer_doses.md"     # the only file allowed to state doses (sourced)

    def test_kb_states_doses_only_in_the_sourced_file(self):
        import re
        kb = SERVER.parent / "kb"
        for p in kb.glob("*.md"):
            if p.name != self.DOSE_FILE:
                self.assertIsNone(re.search(r"\d+\s*(kg|g|ml|l|t|tonnes?)\b", p.read_text(encoding="utf-8"), re.I), p.name)
        self.assertIn("Source: TNAU Agritech", (kb / self.DOSE_FILE).read_text(encoding="utf-8"))

    def test_kb_doses_match_the_fertilizer_screen(self):
        """What the voice assistant can quote = what the touch screen computes from."""
        import re
        import fertilizer
        text = (SERVER.parent / "kb" / self.DOSE_FILE).read_text(encoding="utf-8")
        sections = dict(re.findall(r"^## (\w+) fertilizer dose\n(.+?)(?=\n## |\Z)", text, re.M | re.S))
        for cid, crop in fertilizer.CROPS.items():
            body = sections[crop.name]
            n, p, k = crop.npk
            if cid in ("tomato", "onion"):                  # stated as basal + top dressing, then the total
                self.assertTrue(f"{n:g} kg nitrogen" in body or str(int(n / 2)) in body, cid)
            else:
                self.assertIn(f"{n:g} kg nitrogen", body, cid)
            self.assertIn(f"{p:g} kg phosphorus", body, cid) if cid != "onion" else self.assertIn("phosphorus 150 kg", body)


if __name__ == "__main__":
    unittest.main()
