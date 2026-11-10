"""
Agent Tools  —  spec section 173 ("Agent Orchestration Layer").

    "The AI Agent should coordinate tools rather than directly
    calculate all variables."

Every tool here wraps an ALREADY-TESTED deterministic function from
`decision/`. The LLM never computes a score itself — it only ever sees
numbers that came out of these functions. This is the concrete
enforcement of spec invariant AI-01:

    "The LLM MAY parse, retrieve, orchestrate, and explain; it MUST
    NOT perform authoritative arithmetic or mutate operational state
    without validated tools."

Notably absent: any tool that approves, dispatches, or commits
anything. The agent can investigate and recommend; only a human
coordinator, through the normal /api/recommendations/:id/approve
endpoint, can create a mission. That split is deliberate (spec
section 68: "The AI itself must not have authority to mark a plan as
pre-authorized... That status must originate from... a human
authority.").
"""
import json
from .. import db
from ..decision import urgency as U
from ..decision import ranking


def find_shelter_or_need(query):
    """Resolves free text like 'Shelter A water' to concrete IDs, so the
    agent can turn a natural-language mention into tool-callable IDs."""
    conn = db.get_db()
    q = (query or "").lower()
    shelters = conn.execute("SELECT * FROM shelters").fetchall()
    matches = []
    for s in shelters:
        sid = s["shelter_id"].lower()
        if (q and q in s["name"].lower()) or s["name"].lower() in q or sid in q \
                or any(sid == "shelter_" + t for t in q.replace("shelter", " ").replace("_", " ").split()):
            needs = conn.execute(
                "SELECT * FROM needs WHERE shelter_id=? AND status='ACTIVE'", (s["shelter_id"],)
            ).fetchall()
            matches.append({
                "shelter_id": s["shelter_id"], "shelter_name": s["name"],
                "active_needs": [{"need_id": n["need_id"], "resource_type": n["resource_type"]} for n in needs],
            })
    # also try matching by resource type mentioned in the query, across all shelters
    for rtype in ["WATER", "FOOD", "BLANKET", "BATTERY", "POWER", "MEDICAL_SUPPLIES"]:
        if rtype.lower() in q:
            needs = conn.execute(
                "SELECT * FROM needs WHERE resource_type=? AND status='ACTIVE'", (rtype,)
            ).fetchall()
            for n in needs:
                s = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (n["shelter_id"],)).fetchone()
                entry = {"shelter_id": s["shelter_id"], "shelter_name": s["name"],
                         "active_needs": [{"need_id": n["need_id"], "resource_type": n["resource_type"]}]}
                if entry not in matches:
                    matches.append(entry)
    if not matches:
        return {"found": False, "message": "No shelter or need matched that description."}
    return {"found": True, "matches": matches}


def get_shelter_state(shelter_id):
    """spec section 173: Tool getShelterState()."""
    conn = db.get_db()
    shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchone()
    if shelter is None:
        return {"error": "NOT_FOUND", "shelter_id": shelter_id}
    resources = conn.execute("SELECT * FROM shelter_resources WHERE shelter_id=?", (shelter_id,)).fetchall()
    needs = conn.execute("SELECT * FROM needs WHERE shelter_id=? AND status='ACTIVE'", (shelter_id,)).fetchall()
    return {
        "shelter_id": shelter["shelter_id"], "name": shelter["name"],
        "population_total": shelter["population_total"],
        "vulnerable_total": (shelter["vulnerable_elderly"] + shelter["vulnerable_mobility"]
                              + shelter["vulnerable_pregnant"] + shelter["vulnerable_young_children"]),
        "infrastructure": {
            "electricity": shelter["electricity_status"], "water_supply": shelter["water_supply_status"],
            "sanitation": shelter["sanitation_status"], "mobile_network": shelter["mobile_network_status"],
        },
        "local_coping_situation": shelter["local_coping_situation"],
        "resources": [
            {"resource_type": r["resource_type"], "quantity_canonical": r["quantity_canonical"],
             "unit": r["unit"], "consumption_per_hour_canonical": r["consumption_per_hour_canonical"]}
            for r in resources
        ],
        "active_needs": [{"need_id": n["need_id"], "resource_type": n["resource_type"]} for n in needs],
    }


def calculate_urgency_tool(need_id):
    """spec section 173: Tool calculateUrgency(). Read-only -- identical
    engine call the REST API and dashboard use, so the agent can never
    see a different number than a human coordinator would."""
    conn = db.get_db()
    need = conn.execute("SELECT * FROM needs WHERE need_id=?", (need_id,)).fetchone()
    if need is None:
        return {"error": "NOT_FOUND", "need_id": need_id}
    shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (need["shelter_id"],)).fetchone()
    resource = conn.execute(
        "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
        (need["shelter_id"], need["resource_type"]),
    ).fetchone()
    context = ranking.build_context(db.current_state_version())
    result = U.calculate_urgency(need, shelter, resource, context)
    return {
        "need_id": need_id, "status": result["status"],
        "urgency_score": result["score_display"], "band": result["band"],
        "ttf_minutes": result["ttf_minutes"], "data_confidence": result["data_confidence"],
        "provisional": result["provisional"], "missing_fields": result["missing_fields"],
    }


def generate_recommendation_tool(need_id):
    """spec section 173: bundles generateCandidates() -> calculateFeasibility()
    -> simulatePlan() -> calculateUtility() -> rankPlans() into one call.
    (See README for why these are one tool rather than five separate
    ones in this build.) Returns a trimmed summary -- the full
    plan_inputs/factor breakdown stays out of the LLM's context; it
    already ran through the deterministic engine and doesn't need the
    LLM to re-derive it."""
    result, status = ranking.plan_need(need_id)
    if status != 200:
        return {"error": result.get("error", "PLAN_FAILED")}
    rec = result.get("recommendation")
    if rec is None:
        return {"status": result["urgency"]["status"], "message": "Urgency could not be calculated; no plan generated."}
    if rec["no_acceptable_plan"]:
        return {"no_acceptable_plan": True, "reason_codes": rec["reason_codes"]}

    top = next((c for c in result["candidates"] if c["candidate"]["candidate_id"] == rec["recommended_candidate_id"]), None)
    alternatives = [
        {"candidate_id": c["candidate"]["candidate_id"], "source": c["candidate"]["source_name"],
         "vehicle": c["candidate"]["vehicle_name"], "utility_score": c["utility"]["score_display"] if c["utility"] else None}
        for c in result["candidates"]
        if c["candidate"]["candidate_id"] in rec["ranked_candidate_ids"] and c["candidate"]["candidate_id"] != rec["recommended_candidate_id"]
    ]
    return {
        "recommendation_id": rec["recommendation_id"],
        "recommended_candidate_id": rec["recommended_candidate_id"],
        "source": top["candidate"]["source_name"], "vehicle": top["candidate"]["vehicle_name"],
        "quantity_canonical": top["candidate"]["quantity_canonical"], "eta_minutes": round(top["candidate"]["eta_minutes"], 1),
        "fulfillment_fraction": top["candidate"]["fulfillment_fraction"],
        "feasibility_score": top["feasibility"]["score_display"], "feasibility_band": top["feasibility"]["band"],
        "utility_score": top["utility"]["score_display"], "utility_band": top["utility"]["band"],
        "explanation": rec["explanation"],
        "alternatives_considered": alternatives,
        "requires_human_approval": True,
        "note": "This is a recommendation only. A human coordinator must approve it in the DisasterOps dashboard before any vehicle is dispatched.",
    }


TOOL_SCHEMAS = [
    {
        "name": "find_shelter_or_need",
        "description": "Resolve a free-text mention of a shelter and/or resource (e.g. 'Shelter A water', 'the power situation at Northgate') into concrete shelter_id and need_id values. Always call this first if the user's message names a shelter or resource in plain language rather than an ID.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The shelter name and/or resource mentioned by the user."}},
            "required": ["query"],
        },
    },
    {
        "name": "get_shelter_state",
        "description": "Get the current reported state of one shelter: population, vulnerable groups, infrastructure status, on-hand resources, and active need IDs.",
        "input_schema": {
            "type": "object",
            "properties": {"shelter_id": {"type": "string"}},
            "required": ["shelter_id"],
        },
    },
    {
        "name": "calculate_urgency",
        "description": "Run the deterministic Urgency Engine for one need. Returns the authoritative urgency score (1-10), band, time-to-failure, and data confidence. You must call this rather than estimating urgency yourself.",
        "input_schema": {
            "type": "object",
            "properties": {"need_id": {"type": "string"}},
            "required": ["need_id"],
        },
    },
    {
        "name": "generate_recommendation",
        "description": "Run the full Candidate Generation -> Feasibility -> Utility -> Ranking pipeline for one need and return the top recommended plan plus the alternatives considered. This is expensive -- only call it once you know urgency is meaningfully high, or the user explicitly asked for a plan/recommendation.",
        "input_schema": {
            "type": "object",
            "properties": {"need_id": {"type": "string"}},
            "required": ["need_id"],
        },
    },
]

TOOL_DISPATCH = {
    "find_shelter_or_need": lambda args: find_shelter_or_need(args.get("query", "")),
    "get_shelter_state": lambda args: get_shelter_state(args["shelter_id"]),
    "calculate_urgency": lambda args: calculate_urgency_tool(args["need_id"]),
    "generate_recommendation": lambda args: generate_recommendation_tool(args["need_id"]),
}


def dispatch_tool(name, args):
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": "UNKNOWN_TOOL", "name": name}
    try:
        return fn(args)
    except Exception as exc:  # noqa: BLE001 -- surface to the LLM as a tool error, not a 500
        return {"error": "TOOL_EXECUTION_FAILED", "message": str(exc)}
