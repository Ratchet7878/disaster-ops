"""Regression tests for bugs found in the review of the first build:
access control, double dispatch, mission status handling, and engine edge
cases. Run:  python3 -m unittest tests.test_regressions -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, seed_gsi, config as cfg
from app.decision import feasibility


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_gsi.run_default_seed(reset=True)
        from app.main import create_app
        cls.app = create_app()

    def setUp(self):
        seed_gsi.run_default_seed(reset=True)
        self.c = self.app.test_client()
        self.coord = self.login("coordinator@disasterops.local")
        self.vol_a = self.login("volunteer.a@disasterops.local")

    def login(self, email):
        r = self.c.post("/api/auth/login", json={"email": email, "password": "demo1234"})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def plan(self, need_id):
        r = self.c.post(f"/api/needs/{need_id}/recalculate", headers=self.coord)
        self.assertEqual(r.status_code, 200)
        return r.get_json()["recommendation"]

    def approve(self, rec):
        return self.c.post(f"/api/recommendations/{rec['recommendation_id']}/approve", json={}, headers=self.coord)


class TestAccessControl(Base):
    def test_volunteer_cannot_read_other_shelter(self):
        self.assertEqual(self.c.get("/api/shelters/SHELTER_B", headers=self.vol_a).status_code, 403)
        self.assertEqual(self.c.get("/api/shelters/SHELTER_A", headers=self.vol_a).status_code, 200)

    def test_volunteer_cannot_write_other_shelter(self):
        body = {"category": "POWER_FAILURE"}
        self.assertEqual(self.c.post("/api/shelters/SHELTER_B/critical-updates", json=body, headers=self.vol_a).status_code, 403)
        req = {"resource_type": "WATER", "quantity_requested_canonical": 100}
        self.assertEqual(self.c.post("/api/shelters/SHELTER_B/requests", json=req, headers=self.vol_a).status_code, 403)

    def test_volunteer_cannot_replan_or_use_agent(self):
        self.assertEqual(self.c.post("/api/needs/NEED_A_WATER/recalculate", headers=self.vol_a).status_code, 403)
        self.assertEqual(self.c.post("/api/agent/chat", json={"message": "hi"}, headers=self.vol_a).status_code, 403)

    def test_volunteer_cannot_touch_other_shelters_mission(self):
        rec = self.plan("NEED_A_WATER")
        mid = self.approve(rec).get_json()["mission_id"]
        vol_b = self.login("volunteer.b@disasterops.local")
        self.assertEqual(self.c.get(f"/api/missions/{mid}", headers=vol_b).status_code, 403)
        r = self.c.post(f"/api/missions/{mid}/status", json={"status": "DELIVERED"}, headers=vol_b)
        self.assertEqual(r.status_code, 403)


class TestValidation(Base):
    def test_bad_input_is_422_or_404_not_500(self):
        h = self.coord
        self.assertEqual(self.c.post("/api/shelters/NOPE/critical-updates", json={"category": "ROAD_BLOCKED"}, headers=h).status_code, 404)
        self.assertEqual(self.c.post("/api/shelters/SHELTER_A/requests", json={}, headers=h).status_code, 422)
        self.assertEqual(self.c.post("/api/roads/events", json={}, headers=h).status_code, 422)
        self.assertEqual(self.c.post("/api/roads/events", json={"road_segment_id": "R_A_PRIMARY", "new_status": "PURPLE"}, headers=h).status_code, 422)
        bad = {"resources": [{"quantity_canonical": 5}]}
        self.assertEqual(self.c.post("/api/shelters/SHELTER_A/reports", json=bad, headers=h).status_code, 422)


class TestDoubleDispatch(Base):
    def test_older_pending_recommendation_is_superseded(self):
        rec1 = self.plan("NEED_A_WATER")
        rec2 = self.plan("NEED_A_WATER")
        self.assertEqual(self.approve(rec1).status_code, 409)  # stale, superseded by rec2
        self.assertEqual(self.approve(rec2).status_code, 200)

    def test_approving_one_supersedes_other_pending(self):
        rec1 = self.plan("NEED_A_WATER")
        conn = db.get_db()
        conn.execute("UPDATE recommendations SET status='PENDING_APPROVAL' WHERE recommendation_id=?", (rec1["recommendation_id"],))
        conn.commit()
        self.assertEqual(self.approve(rec1).status_code, 200)
        conn = db.get_db()  # requests close the thread's connection
        n = conn.execute("SELECT COUNT(*) FROM missions WHERE need_id='NEED_A_WATER'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_candidate_from_another_need_is_rejected(self):
        rec_a = self.plan("NEED_A_WATER")
        rec_d = self.plan("NEED_D_FOOD")
        r = self.c.post(f"/api/recommendations/{rec_a['recommendation_id']}/approve",
                        json={"candidate_id": rec_d["recommended_candidate_id"]}, headers=self.coord)
        self.assertEqual(r.status_code, 422)

    def test_cannot_reject_approved_recommendation(self):
        rec = self.plan("NEED_A_WATER")
        self.assertEqual(self.approve(rec).status_code, 200)
        r = self.c.post(f"/api/recommendations/{rec['recommendation_id']}/reject", json={"reason": "x"}, headers=self.coord)
        self.assertEqual(r.status_code, 409)


class TestMissionStatus(Base):
    def _mission(self):
        rec = self.plan("NEED_A_WATER")
        r = self.approve(rec)
        self.assertEqual(r.status_code, 200)
        conn = db.get_db()
        m = conn.execute("SELECT * FROM missions").fetchone()
        return dict(m)

    def _stock(self, m):
        conn = db.get_db()
        dest = conn.execute("SELECT quantity_canonical FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
                            (m["destination_shelter_id"], m["resource_type"])).fetchone()[0]
        return dest

    def test_delivering_twice_does_not_double_count(self):
        m = self._mission()
        before = self._stock(m)
        r1 = self.c.post(f"/api/missions/{m['mission_id']}/status", json={"status": "DELIVERED"}, headers=self.coord)
        self.assertEqual(r1.status_code, 200)
        after_first = self._stock(m)
        self.assertAlmostEqual(after_first, before + m["quantity_canonical"])
        r2 = self.c.post(f"/api/missions/{m['mission_id']}/status", json={"status": "DELIVERED"}, headers=self.coord)
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(self._stock(m), after_first)

    def test_negative_received_quantity_rejected(self):
        m = self._mission()
        r = self.c.post(f"/api/missions/{m['mission_id']}/status",
                        json={"status": "DELIVERED", "actual_quantity_received": -5}, headers=self.coord)
        self.assertEqual(r.status_code, 422)

    def test_cancel_releases_commitment_and_reactivates_need(self):
        m = self._mission()
        if m["source_type"] == "WAREHOUSE":
            committed = lambda: db.get_db().execute(
                "SELECT committed_quantity_canonical FROM warehouse_inventory WHERE warehouse_id=? AND resource_type=?",
                (m["source_id"], m["resource_type"])).fetchone()[0]
            during = committed()  # seed already has stock committed elsewhere
            self.assertGreater(during, m["quantity_canonical"] - 1e-9)
        r = self.c.post(f"/api/missions/{m['mission_id']}/status", json={"status": "CANCELLED"}, headers=self.coord)
        self.assertEqual(r.status_code, 200)
        if m["source_type"] == "WAREHOUSE":
            self.assertAlmostEqual(committed(), during - m["quantity_canonical"])
        status = db.get_db().execute("SELECT status FROM needs WHERE need_id='NEED_A_WATER'").fetchone()[0]
        self.assertEqual(status, "ACTIVE")
        self.assertEqual(self.c.post(f"/api/missions/{m['mission_id']}/status", json={"status": "CANCELLED"},
                                     headers=self.coord).status_code, 409)


class TestBusyVehicles(Base):
    def test_in_transit_vehicle_becomes_delayed_candidate(self):
        """Approving a mission sets its van IN_TRANSIT; later plans must still
        be able to use it as a delayed-vehicle candidate (spec 88.4)."""
        self.assertEqual(self.approve(self.plan("NEED_A_WATER")).status_code, 200)
        conn = db.get_db()
        busy = conn.execute("SELECT vehicle_id FROM vehicles WHERE status='IN_TRANSIT'").fetchone()
        self.assertIsNotNone(busy)
        r = self.c.post("/api/needs/NEED_A_FOOD/recalculate", headers=self.coord)
        used = {c["candidate"]["vehicle_id"] for c in r.get_json()["candidates"]}
        self.assertIn(busy["vehicle_id"], used)


class TestEngineEdges(unittest.TestCase):
    def test_missing_vehicle_capacity_is_needs_data(self):
        inputs = {"candidate_id": "P", "planned_load": 10, "eta_minutes": 5, "vehicle_capacity": None,
                  "transferable_quantity": 100, "route_exists": True}
        res = feasibility.calculate_feasibility(inputs, {})
        self.assertEqual(res["status"], "NEEDS_DATA")

    def test_power_severity_matches_spec(self):
        from app.decision import urgency
        self.assertEqual(urgency.resource_severity("POWER"), 1.0)


if __name__ == "__main__":
    unittest.main()
