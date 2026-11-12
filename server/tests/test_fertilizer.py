"""Fertilizer engine: official doses, soil-card rule, product conversion, API."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fertilizer as f  # noqa: E402


def nutrients(stages):
    """N, P2O5, K2O actually delivered by the products in the stages."""
    urea = sum(s["urea_kg"] for s in stages)
    dap = sum(s["dap_kg"] for s in stages)
    mop = sum(s["mop_kg"] for s in stages)
    return urea * f.UREA_N + dap * f.DAP_N, dap * f.DAP_P, mop * f.MOP_K


class FertilizerTests(unittest.TestCase):
    def test_every_crop_has_a_source_and_complete_splits(self):
        for cid, c in f.CROPS.items():
            self.assertTrue(c.source and c.url.startswith("https://"), cid)
            for i, part in enumerate(("N", "P", "K")):
                self.assertAlmostEqual(sum((s.n, s.p, s.k)[i] for s in c.stages), 1.0, msg=f"{cid} {part}")

    def test_products_deliver_the_recommended_nutrients(self):
        for cid in f.CROPS:
            for acres in (0.5, 1, 4):
                r = f.recommend(cid, acres)
                n, p, k = nutrients(r["stages"])
                want = r["dose_for_area_kg"]
                tol = 0.03 * max(want.values()) + 0.6       # rounding to whole / half kg
                self.assertAlmostEqual(n, want["N"], delta=tol, msg=cid)
                self.assertAlmostEqual(p, want["P"], delta=tol, msg=cid)
                self.assertAlmostEqual(k, want["K"], delta=tol, msg=cid)

    def test_tomato_one_acre_worked_example(self):
        r = f.recommend("tomato", 1)
        self.assertEqual(r["base_kg_ha"], {"N": 150, "P": 100, "K": 50})
        self.assertEqual(r["totals"], {"urea_kg": 98, "dap_kg": 88, "mop_kg": 34})
        self.assertEqual(r["stages"][1]["dap_kg"], 0)          # all P at planting

    def test_soil_card_rule_is_plus_minus_25_percent(self):
        r = f.recommend("tomato", 1, n="low", p="high", k="medium")
        self.assertEqual(r["dose_kg_ha"], {"N": 187.5, "P": 75.0, "K": 50.0})
        self.assertTrue(any("25% above" in w for w in r["why"]))
        self.assertTrue(any("25% below" in w for w in r["why"]))

    def test_surplus_dap_nitrogen_is_taken_off_the_next_split(self):
        r = f.recommend("onion", 1)                          # DAP brings more N than the basal half
        self.assertEqual(r["stages"][0]["urea_kg"], 0)
        n, _, _ = nutrients(r["stages"])
        self.assertAlmostEqual(n, r["dose_for_area_kg"]["N"], delta=1.5)

    def test_regions_are_sourced_and_valid(self):
        for rid, r in f.REGIONS.items():
            self.assertTrue(r.source, rid)
            for v in (r.n, r.p, r.k):
                self.assertIn(v, (None, "low", "medium", "high"), rid)
            if rid != "other":
                self.assertTrue(r.url.startswith("https://"), rid)

    def test_district_fills_in_missing_soil_card_values(self):
        r = f.recommend("tomato", 1, region="bengaluru")               # N medium, P high, K medium
        self.assertEqual(r["rating_from"], {"N": "district", "P": "district", "K": "district"})
        self.assertEqual(r["dose_kg_ha"], {"N": 150.0, "P": 75.0, "K": 50.0})
        r = f.recommend("tomato", 1, region="tumakuru")                # N low
        self.assertEqual(r["dose_kg_ha"]["N"], 187.5)
        self.assertTrue(any("Tumakuru soil surveys (assumed)" in w for w in r["why"]))

    def test_soil_card_beats_the_district(self):
        r = f.recommend("tomato", 1, n="high", region="tumakuru")      # district says N low
        self.assertEqual(r["ratings"]["N"], "high")
        self.assertEqual(r["rating_from"]["N"], "soil card")
        self.assertEqual(r["dose_kg_ha"]["N"], 112.5)

    def test_unsettled_district_nutrient_gets_the_general_dose(self):
        r = f.recommend("tomato", 1, region="chikkaballapura")          # N not settled by the survey
        self.assertEqual(r["rating_from"]["N"], "general")
        self.assertEqual(r["dose_kg_ha"]["N"], 150.0)

    def test_screen_marks_assumed_values(self):
        _, pages = f.screen_pages(f.recommend("ragi", 1, region="kolar"))
        text = " ".join(t for _, t in pages[0])
        self.assertIn("N:low*", text)
        self.assertIn("assumed from Kolar", text)

    def test_unknown_region_rejected(self):
        with self.assertRaises(ValueError):
            f.recommend("tomato", 1, region="atlantis")

    def test_bad_rating_rejected(self):
        with self.assertRaises(ValueError):
            f.recommend("tomato", 1, n="very low")

    def test_sensors_never_change_the_dose(self):
        dry = f.recommend("maize", 1, sensor={"temperature_c": 40, "humidity_percent": 10,
                                               "soil_sensor_valid": True, "soil_moisture_percent": 5}, sensor_status="online")
        none = f.recommend("maize", 1)
        self.assertEqual(dry["totals"], none["totals"])
        self.assertIn("Soil moisture now: 5%", " ".join(dry["field"]))
        self.assertIn("offline", " ".join(none["field"]))

    def test_uncalibrated_soil_sensor_is_said_plainly(self):
        r = f.recommend("ragi", 1, sensor={"temperature_c": 29, "humidity_percent": 23, "soil_sensor_valid": False},
                        sensor_status="online")
        self.assertIn("not calibrated", " ".join(r["field"]))

    def test_screen_pages_are_ascii_and_short(self):
        for cid in f.CROPS:
            title, pages = f.screen_pages(f.recommend(cid, 2.5, n="low"))
            self.assertLessEqual(len(pages), 6)
            for pg in pages:
                self.assertLessEqual(len(pg), 12)
                for style, text in pg:
                    self.assertIn(style, "HVTWS")
                    self.assertTrue(text.isascii() and len(text) <= 95 and "|" not in text, text)


class FertilizerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        import dotenv
        dotenv.load_dotenv = lambda *a, **k: None
        os.environ.update({"EMBED_MODEL": "", "SENSOR_STORE": os.path.join(tempfile.mkdtemp(), "s.json")})
        from fastapi.testclient import TestClient
        import app
        cls.ctx = TestClient(app.app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_crops_endpoint(self):
        r = self.c.get("/api/krishi/fertilizer/crops").json()
        self.assertEqual([c["id"] for c in r["crops"]], list(f.CROPS))
        self.assertIn(1, r["areas_acres"])

    def test_recommend_endpoint(self):
        r = self.c.post("/api/krishi/fertilizer", json={"crop": "tomato", "area_acres": 1, "n": "low"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["dose_kg_ha"]["N"], 187.5)
        self.assertEqual(body["screen"]["title"], "Tomato - 1 acre")
        self.assertEqual(self.c.post("/api/krishi/fertilizer", json={"crop": "banana", "area_acres": 1}).status_code, 404)
        self.assertEqual(self.c.post("/api/krishi/fertilizer", json={"crop": "tomato", "area_acres": 0}).status_code, 422)
        self.assertEqual(self.c.post("/api/krishi/fertilizer", json={"crop": "tomato", "area_acres": 1, "n": "lots"}).status_code, 422)

    def test_region_through_the_api(self):
        crops = self.c.get("/api/krishi/fertilizer/crops").json()
        self.assertIn("bengaluru", [r["id"] for r in crops["regions"]])
        body = self.c.post("/api/krishi/fertilizer", json={"crop": "tomato", "area_acres": 1, "region": "bengaluru"}).json()
        self.assertEqual(body["region"]["name"], "Bengaluru")
        self.assertEqual(body["dose_kg_ha"]["P"], 75.0)
        self.assertEqual(self.c.post("/api/krishi/fertilizer",
                                     json={"crop": "tomato", "area_acres": 1, "region": "atlantis"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
