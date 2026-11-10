"""
Tests for the agent's tool layer (backend/app/agent/tools.py) — these
run against the real seeded database and need NO network access,
unlike the LLM orchestration loop itself (see tests/agent_live_smoke_test.py
for that, which requires ANTHROPIC_API_KEY and was not run in the
sandbox this was built in).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db
from app.agent import tools as agent_tools


class TestAgentTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import seed_gsi
        seed_gsi.run_default_seed(reset=True)

    def test_find_shelter_by_name(self):
        result = agent_tools.find_shelter_or_need("Shelter A")
        self.assertTrue(result["found"])
        self.assertEqual(result["matches"][0]["shelter_id"], "SHELTER_A")

    def test_find_shelter_by_resource_mention(self):
        result = agent_tools.find_shelter_or_need("power")
        self.assertTrue(result["found"])
        shelter_ids = [m["shelter_id"] for m in result["matches"]]
        self.assertIn("SHELTER_C", shelter_ids)

    def test_find_nothing_matching(self):
        result = agent_tools.find_shelter_or_need("nonexistent place xyz")
        self.assertFalse(result["found"])

    def test_get_shelter_state_known_shelter(self):
        state = agent_tools.get_shelter_state("SHELTER_A")
        self.assertEqual(state["shelter_id"], "SHELTER_A")
        self.assertIn("resources", state)
        self.assertTrue(any(r["resource_type"] == "WATER" for r in state["resources"]))

    def test_get_shelter_state_unknown_shelter(self):
        state = agent_tools.get_shelter_state("SHELTER_NOPE")
        self.assertEqual(state["error"], "NOT_FOUND")

    def test_calculate_urgency_tool_matches_engine(self):
        # cross-check the tool's output against the same engine used by
        # the REST API for the same need, so the agent can never see a
        # different number than a human coordinator would.
        from app.decision import urgency as U
        from app.decision import ranking
        conn = db.get_db()
        need = conn.execute("SELECT * FROM needs WHERE need_id='NEED_A_WATER'").fetchone()
        shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (need["shelter_id"],)).fetchone()
        resource = conn.execute(
            "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
            (need["shelter_id"], need["resource_type"]),
        ).fetchone()
        context = ranking.build_context(db.current_state_version())
        direct = U.calculate_urgency(need, shelter, resource, context)

        via_tool = agent_tools.calculate_urgency_tool("NEED_A_WATER")
        self.assertEqual(via_tool["urgency_score"], direct["score_display"])
        self.assertEqual(via_tool["band"], direct["band"])

    def test_calculate_urgency_tool_unknown_need(self):
        result = agent_tools.calculate_urgency_tool("NEED_DOES_NOT_EXIST")
        self.assertEqual(result["error"], "NOT_FOUND")

    def test_generate_recommendation_tool_returns_grounded_numbers(self):
        result = agent_tools.generate_recommendation_tool("NEED_A_WATER")
        self.assertNotIn("error", result)
        self.assertIn("recommended_candidate_id", result)
        self.assertTrue(result["requires_human_approval"])
        # never let the tool imply it already acted
        self.assertNotIn("dispatched", result["note"].lower().replace("before any vehicle is dispatched", ""))

    def test_dispatch_unknown_tool_name_is_safe(self):
        result = agent_tools.dispatch_tool("delete_everything", {})
        self.assertEqual(result["error"], "UNKNOWN_TOOL")

    def test_tool_schemas_are_well_formed(self):
        names = set()
        for schema in agent_tools.TOOL_SCHEMAS:
            self.assertIn("name", schema)
            self.assertIn("description", schema)
            self.assertIn("input_schema", schema)
            self.assertEqual(schema["input_schema"]["type"], "object")
            names.add(schema["name"])
        # every schema must have a matching dispatcher entry and vice versa
        self.assertEqual(names, set(agent_tools.TOOL_DISPATCH.keys()))


if __name__ == "__main__":
    unittest.main()
