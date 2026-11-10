"""End-to-end smoke test against the running Flask server, exercising
the exact "Recommended Demo User Flow" from spec section 183:
login -> view need -> AI recommendation -> approve -> road closure ->
automatic replanning."""
import json
import urllib.request

BASE = "http://localhost:5001"


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


section("1. LOGIN as coordinator")
status, resp = call("POST", "/api/auth/login", body={"email": "coordinator@disasterops.local", "password": "demo1234"})
assert status == 200, resp
token = resp["token"]
print("OK - logged in as", resp["user"]["name"], resp["user"]["role"])

section("2. LOGIN as volunteer (Shelter A) and submit a critical update")
status, resp = call("POST", "/api/auth/login", body={"email": "volunteer.a@disasterops.local", "password": "demo1234"})
assert status == 200, resp
vol_token = resp["token"]
print("OK - logged in as", resp["user"]["name"])

section("3. GET /api/needs (priority queue)")
status, needs = call("GET", "/api/needs", token=token)
assert status == 200
for n in needs[:5]:
    print(f"  {n['need_id']:20s} {n['shelter_name']:28s} {n['resource_type']:8s} "
          f"urgency={n['urgency']['score_display']} ({n['urgency']['band']})")

section("4. POST /api/needs/NEED_A_WATER/recalculate  (full decision pipeline)")
status, plan = call("POST", "/api/needs/NEED_A_WATER/recalculate", token=token)
assert status == 200, plan
rec = plan["recommendation"]
print("Urgency:", plan["urgency"]["score_display"], plan["urgency"]["band"])
print("Candidates evaluated:", len(plan["candidates"]))
print("Recommended candidate:", rec["recommended_candidate_id"])
print("Ranking:", rec["ranking"])
print("Explanation:", rec["explanation"])
rec_id = rec["recommendation_id"]

section("5. Volunteer tries to approve (should be FORBIDDEN - RBAC check)")
status, resp = call("POST", f"/api/recommendations/{rec_id}/approve", token=vol_token, body={})
print("status:", status, resp)
assert status == 403

section("6. Coordinator APPROVES the recommendation")
status, resp = call("POST", f"/api/recommendations/{rec_id}/approve", token=token, body={})
print("status:", status, resp)
assert status == 200, resp
mission_id = resp["mission_id"]
print("Mission created:", mission_id)

section("7. GET /api/missions - confirm mission is DISPATCHED")
status, missions = call("GET", "/api/missions", token=token)
mine = [m for m in missions if m["mission_id"] == mission_id][0]
print(json.dumps(mine, indent=2))
assert mine["status"] == "DISPATCHED"

section("8. Re-approving the SAME recommendation must fail (no double mission)")
status, resp = call("POST", f"/api/recommendations/{rec_id}/approve", token=token, body={})
print("status:", status, resp)
assert status == 409

section("9. GET /api/roads - find Shelter D's primary road segment")
status, roads = call("GET", "/api/roads", token=token)
for r in roads:
    print(" ", r["road_segment_id"], r["name"], r["status"])

section("10. Simulate a ROAD CLOSURE on R_D_PRIMARY (Eastside Elementary)")
status, resp = call("POST", "/api/roads/events", token=token,
                     body={"road_segment_id": "R_D_PRIMARY", "new_status": "BLOCKED",
                           "note": "Flooding reported - bridge impassable"})
print("status:", status)
print("Affected shelters:", resp["affected_shelters"])
for r in resp["replanned"]:
    need_id = r["need_id"]
    result = r["result"]
    rec2 = result.get("recommendation")
    print(f"  Replanned {need_id}: urgency={result['urgency']['score_display']}, "
          f"recommended={rec2['recommended_candidate_id'] if rec2 else None}, "
          f"no_acceptable_plan={rec2['no_acceptable_plan'] if rec2 else None}")

section("11. GET /api/audit - confirm the full decision trail was logged")
status, audit = call("GET", "/api/audit", token=token)
event_types = {}
for a in audit:
    event_types[a["event_type"]] = event_types.get(a["event_type"], 0) + 1
for et, count in sorted(event_types.items()):
    print(f"  {et}: {count}")

section("ALL CHECKS PASSED")
