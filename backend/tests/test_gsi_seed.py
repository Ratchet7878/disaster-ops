"""Runs the decision engine on the GSI real-geography seed (Fukuoka City).
Skipped automatically if the GSI files are not in <repo>/data.
    python3 -m unittest tests.test_gsi_seed -v"""
import csv
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, seed_gsi
from app.decision import ranking, routing

HAVE_DATA = bool(glob.glob(os.path.join(seed_gsi.DATA_DIR, "*_1", "*_1.csv"))
                 and glob.glob(os.path.join(seed_gsi.DATA_DIR, "*_2", "*_2.csv")))


@unittest.skipUnless(HAVE_DATA, "GSI data not found in data/")
class TestGsiSeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.picks = seed_gsi.run_seed_gsi(reset=True)
        from app.main import create_app
        cls.app = create_app()
        cls.c = cls.app.test_client()
        r = cls.c.post("/api/auth/login", json={"email": "coordinator@disasterops.local", "password": "demo1234"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["token"]}

    def test_shelters_are_real_gsi_rows(self):
        path = glob.glob(os.path.join(seed_gsi.DATA_DIR, "*_1", "*_1.csv"))[0]
        real = {(r["施設・場所名"], round(float(r["緯度"]), 6), round(float(r["経度"]), 6))
                for r in seed_gsi._read_csv(path)}
        rows = db.get_db().execute("SELECT name, latitude, longitude FROM shelters").fetchall()
        self.assertEqual(len(rows), 5)
        for r in rows:
            self.assertIn((r["name"], round(r["latitude"], 6), round(r["longitude"], 6)), real)
            self.assertTrue(33.4 < r["latitude"] < 33.8 and 130.2 < r["longitude"] < 130.6, "not in Fukuoka City")

    def test_plan_every_need(self):
        needs = db.get_db().execute("SELECT need_id FROM needs WHERE status='ACTIVE'").fetchall()
        self.assertGreaterEqual(len(needs), 10)
        planned = 0
        for n in needs:
            result, status = ranking.plan_need(n["need_id"])
            self.assertEqual(status, 200, n["need_id"])
            if result["urgency"]["status"] != "CALCULATED":
                continue
            planned += 1
            for cand in result["candidates"]:
                p = cand["candidate"]
                self.assertGreater(p["distance_km"], 0)
                self.assertLess(p["distance_km"], 40, "implausible distance inside one city")
                self.assertGreater(p["eta_minutes"], 0)
                self.assertLess(p["eta_minutes"], 240)
                # ETA must equal real haversine travel time (+ any vehicle wait)
                self.assertGreaterEqual(p["eta_minutes"] + 1e-6, p["distance_km"] / 40 * 60)
            rec = result["recommendation"]
            self.assertTrue(rec["no_acceptable_plan"] or rec["recommended_candidate_id"])
        self.assertGreaterEqual(planned, 10)

    def test_spec_example_still_reproduced(self):
        r, _ = ranking.plan_need("NEED_A_WATER")
        self.assertAlmostEqual(r["urgency"]["ttf_minutes"], 157.5, places=1)

    def test_distance_matches_haversine(self):
        conn = db.get_db()
        a = conn.execute("SELECT latitude, longitude FROM shelters WHERE shelter_id='SHELTER_A'").fetchone()
        e = conn.execute("SELECT latitude, longitude FROM shelters WHERE shelter_id='SHELTER_E'").fetchone()
        d = routing.haversine_km(a["latitude"], a["longitude"], e["latitude"], e["longitude"])
        self.assertTrue(5 < d < 30, d)  # East ward to West ward of Fukuoka City

    def test_demo_flow_approve_then_road_closure(self):
        r = self.c.post("/api/needs/NEED_A_WATER/recalculate", headers=self.h).get_json()["recommendation"]
        ap = self.c.post(f"/api/recommendations/{r['recommendation_id']}/approve", json={}, headers=self.h)
        self.assertEqual(ap.status_code, 200)
        ev = self.c.post("/api/roads/events", json={"road_segment_id": "R_D_PRIMARY"}, headers=self.h)
        self.assertEqual(ev.status_code, 200)
        body = ev.get_json()
        self.assertEqual(body["affected_shelters"], ["SHELTER_D"])
        self.assertTrue(body["replanned"])
        for rp in body["replanned"]:
            cands = rp["result"].get("candidates", [])
            for c in cands:  # no accepted plan may still route over the blocked primary road
                if c["feasibility"]["status"] == "SCOREABLE":
                    self.assertGreater(c["feasibility"]["factors"]["route"], 0)


if __name__ == "__main__":
    unittest.main()
