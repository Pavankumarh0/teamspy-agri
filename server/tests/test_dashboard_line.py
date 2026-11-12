"""krishi_client.DashboardPoller: the D: line the ESP32 dashboard parses."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import krishi_client  # noqa: E402

LATEST = {"status": "online", "age_seconds": 3.0, "reading": {
    "device_id": "unoq_soil_01", "temperature_c": 28.5, "humidity_percent": 31.0, "soil_moisture_raw": 16363,
    "soil_moisture_percent": None, "soil_sensor_valid": False, "mq135_raw": 1748, "mq135_valid": True}}


def poller_with(data, ok=True, fetched_ago=0.0):
    with mock.patch.object(krishi_client.threading, "Thread"):     # no background thread in tests
        p = krishi_client.DashboardPoller("http://x")
    p._data, p._ok, p._fetched, p._new = data, ok, time.time() - fetched_ago, True
    return p


def fields(line):
    assert line.startswith("D:")
    return dict(kv.split("=", 1) for kv in line[2:].split(";"))


class DashboardLineTests(unittest.TestCase):
    def test_spec_payload(self):
        f = fields(poller_with(LATEST).take_line())
        self.assertEqual(f["st"], "online")
        self.assertEqual(f["t"], "28.5")
        self.assertEqual(f["h"], "31")
        self.assertEqual(f["sr"], "16363")
        self.assertEqual(f["sv"], "0")
        self.assertEqual(f["sp"], "")              # no percentage: not calibrated
        self.assertEqual(f["mq"], "1748")
        self.assertEqual(f["srv"], "ok")
        self.assertEqual(f["dev"], "unoq_soil_01")

    def test_line_is_sent_once_per_poll(self):
        p = poller_with(LATEST)
        self.assertIsNotNone(p.take_line())
        self.assertIsNone(p.take_line())

    def test_null_values_are_empty(self):
        data = {"status": "online", "age_seconds": 1, "reading": {**LATEST["reading"], "temperature_c": None,
                                                                    "humidity_percent": None, "mq135_raw": None}}
        f = fields(poller_with(data).take_line())
        self.assertEqual((f["t"], f["h"], f["mq"]), ("", "", ""))

    def test_server_down_keeps_last_reading_marked_unknown_and_ageing(self):
        f = fields(poller_with(LATEST, ok=False, fetched_ago=60).take_line())
        self.assertEqual(f["srv"], "down")
        self.assertEqual(f["st"], "unknown")
        self.assertEqual(f["t"], "28.5")            # last known, shown dimmed as "last known"
        self.assertGreaterEqual(int(f["age"]), 63)

    def test_no_data_yet(self):
        f = fields(poller_with({"status": "no_data", "reading": None}).take_line())
        self.assertEqual(f, {"srv": "ok", "st": "no_data"})

    def test_line_fits_the_esp32_buffer(self):
        self.assertLess(len(poller_with(LATEST).take_line()), 200)


if __name__ == "__main__":
    unittest.main()
