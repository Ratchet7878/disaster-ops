"""
Decision Engine orchestration  —  spec section 172 ("Decision Engine API")
and section 129 ("Utility Ranking Algorithm").

This is the single function the API layer calls to go from "a need" to
"a ranked, explained recommendation": exactly the POST /api/needs/:id/plan
pipeline described in spec section 172.
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from .. import config as cfg
from .. import db
from . import urgency as U
from . import feasibility as F
from . import candidates as C
from . import utility as UT


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def build_context(state_version):
    return {
        "planning_run_id": f"RUN_{uuid.uuid4().hex[:10]}",
        "as_of": _iso(datetime.now(timezone.utc)),
        "state_version": state_version,
        "config_version": cfg.CONFIG_VERSION,
        "algorithm_version": cfg.ALGORITHM_VERSION,
        "sop_snapshot_ids": [],
    }


def _get_shelter_resource(conn, shelter_id, resource_type):
    return conn.execute(
        "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
        (shelter_id, resource_type),
    ).fetchone()


def _active_need_cohort_burden(conn, context, exclude_need_id=None):
    """Computes B0 over every ACTIVE need with a CALCULATED urgency result.
    Returns (b0, need_states) where need_states is reusable for candidate
    simulation (spec 117.4, UTIL-02 common baseline)."""
    needs = conn.execute("SELECT * FROM needs WHERE status='ACTIVE'").fetchall()
    need_states = []
    for n in needs:
        shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (n["shelter_id"],)).fetchone()
        res = _get_shelter_resource(conn, n["shelter_id"], n["resource_type"])
        ur = U.calculate_urgency(n, shelter, res, context)
        if ur["status"] != "CALCULATED":
            continue
        on_hand = res["quantity_canonical"] if res else 0
        need_states.append({
            "need_id": n["need_id"],
            "shelter_id": n["shelter_id"],
            "resource_type": n["resource_type"],
            "u0": UT.normalized_urgency(ur["score_internal"]),
            "target_qty": n["target_quantity_canonical"],
            "projected_qty": on_hand or 0,
            "urgency_score": ur["score_internal"],
        })
    b0 = UT.system_burden(need_states)
    return b0, need_states


def _simulate_burden_after(need_states, target_need_id, delivered_qty,
                            donor_shelter_id=None, donor_resource_type=None, donor_after_qty=None):
    """Projects need_states forward under candidate p (spec 117.5) and
    returns Bp. Only the target need (delivery received) and, if the
    donor happens to also carry an active need for the same resource,
    the donor's need are updated — every other need is held at baseline,
    per the frozen active-need cohort rule (UTIL-02)."""
    projected = []
    for n in need_states:
        row = dict(n)
        if row["need_id"] == target_need_id:
            row["projected_qty"] = row["projected_qty"] + delivered_qty
        elif (donor_shelter_id and row["shelter_id"] == donor_shelter_id
              and row["resource_type"] == donor_resource_type):
            row["projected_qty"] = donor_after_qty
        projected.append(row)
    return UT.system_burden(projected)


def plan_need(need_id):
    """Full Urgency -> Candidates -> Feasibility -> Utility -> Ranking
    pipeline for one need. Returns a JSON-serializable dict and persists
    candidate_plans / recommendations / audit_logs."""
    conn = db.get_db()
    state_version = db.current_state_version()
    context = build_context(state_version)

    need = conn.execute("SELECT * FROM needs WHERE need_id=?", (need_id,)).fetchone()
    if need is None:
        return {"error": "NOT_FOUND"}, 404

    shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (need["shelter_id"],)).fetchone()
    resource_row = _get_shelter_resource(conn, need["shelter_id"], need["resource_type"])

    urgency_result = U.calculate_urgency(need, shelter, resource_row, context)
    conn.execute(
        "UPDATE needs SET last_urgency_json=?, last_urgency_state_version=? WHERE need_id=?",
        (json.dumps(urgency_result), state_version, need_id),
    )
    conn.commit()
    db.write_audit("URGENCY_CALCULATED", object_id=need_id, state_after=state_version,
                    explanation=f"status={urgency_result['status']}")

    if urgency_result["status"] != "CALCULATED":
        return {
            "urgency": urgency_result,
            "candidates": [],
            "recommendation": None,
        }, 200

    ttf_internal = urgency_result["ttf_minutes"]
    if ttf_internal is None:
        ttf_internal = float("inf")

    raw_candidates = C.generate_candidates(conn, need, shelter, resource_row, ttf_internal, context)

    evaluated = []
    for rc in raw_candidates:
        feas = F.calculate_feasibility(rc["plan_inputs"], context)
        evaluated.append({**rc, "feasibility": feas})
        db.write_audit("FEASIBILITY_CALCULATED", object_id=rc["candidate_id"], state_after=state_version,
                        explanation=f"status={feas['status']}")

    scoreable = [c for c in evaluated if c["feasibility"]["status"] == "SCOREABLE"]
    excluded = [c for c in evaluated if c["feasibility"]["status"] != "SCOREABLE"]

    b0, need_states = _active_need_cohort_burden(conn, context)

    for c in scoreable:
        bp = _simulate_burden_after(
            need_states, need_id, c["quantity_canonical"],
            donor_shelter_id=c.get("donor_shelter_id"),
            donor_resource_type=need["resource_type"] if c.get("donor_shelter_id") else None,
            donor_after_qty=c.get("donor_after_quantity"),
        )
        i_p = UT.system_impact(b0, bp)
        c_p = UT.effective_coverage(
            [(c["quantity_canonical"], c["eta_minutes"])], c["required_qty"], ttf_internal
        )

        affected_sources = []
        if c["source_after_quantity"] is not None:
            reserve = c["source_reserve_quantity"] or 0
            buffer = max(reserve, 1.0)
            affected_sources.append({
                "after_qty": c["source_after_quantity"], "reserve_qty": reserve, "buffer_qty": buffer,
            })
        d_p = UT.downstream_safety(affected_sources)

        m_p = UT.mission_continuity([])  # no existing-mission disruption modeled in MVP

        vehicle_minutes = (c["distance_km"] / cfg.MOCK_AVERAGE_SPEED_KMH) * 60.0
        vehicle_row = conn.execute("SELECT * FROM vehicles WHERE vehicle_id=?", (c["vehicle_id"],)).fetchone()
        vehicle_cap_units = C._vehicle_capacity_in_resource_units(vehicle_row, need["resource_type"])
        load_util = c["quantity_canonical"] / vehicle_cap_units if vehicle_cap_units else 0
        e_p = UT.operational_efficiency(vehicle_minutes, c["distance_km"], 1, load_util)

        vehicles = conn.execute("SELECT * FROM vehicles").fetchall()
        operational = [v for v in vehicles if v["status"] != "OUT_OF_SERVICE"]
        available_after = sum(1 for v in operational if v["vehicle_id"] != c["vehicle_id"] and v["status"] == "AVAILABLE")
        surplus_ratios = []
        if c["source_after_quantity"] is not None:
            reserve = c["source_reserve_quantity"] or 0
            surplus_ratios.append((c["source_after_quantity"] - reserve) / max(reserve, 1.0))
        o_p = UT.future_optionality(available_after, len(operational), surplus_ratios)

        util = UT.calculate_utility(
            {"I": i_p, "C": c_p, "D": d_p, "M": m_p, "E": e_p, "O": o_p},
            context, c["candidate_id"], state_version,
        )
        c["utility"] = util
        db.write_audit("UTILITY_CALCULATED", object_id=c["candidate_id"], state_after=state_version,
                        explanation=f"utility={util['score_display']}")

    ranked = rank_plans(scoreable)

    recommendation_id = f"REC_{uuid.uuid4().hex[:10]}"
    no_acceptable = len(ranked) == 0
    recommended_id = ranked[0]["candidate_id"] if ranked else None
    ranking_payload = [
        {"candidate_id": c["candidate_id"],
         "utility_display": c["utility"]["score_display"],
         "feasibility_display": c["feasibility"]["score_display"]}
        for c in ranked[:5]
    ]
    expires_at = _iso(datetime.now(timezone.utc) + timedelta(minutes=10))

    explanation = _build_explanation(ranked[0] if ranked else None, need, urgency_result)

    # Only one live recommendation per need: older pending ones are stale.
    conn.execute(
        "UPDATE recommendations SET status='SUPERSEDED' WHERE need_id=? AND status='PENDING_APPROVAL'",
        (need_id,),
    )
    conn.execute(
        """INSERT INTO recommendations
           (recommendation_id, planning_run_id, need_id, state_version,
            recommended_candidate_id, no_acceptable_plan, ranking_json,
            explanation_json, created_at, expires_at, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (recommendation_id, context["planning_run_id"], need_id, state_version,
         recommended_id, int(no_acceptable), json.dumps(ranking_payload),
         json.dumps(explanation), _iso(datetime.now(timezone.utc)), expires_at, "PENDING_APPROVAL"),
    )

    for c in evaluated:
        conn.execute(
            """INSERT INTO candidate_plans
               (candidate_id, planning_run_id, need_id, state_version, generation_pattern,
                plan_json, feasibility_json, utility_json, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (c["candidate_id"], context["planning_run_id"], need_id, state_version,
             c["generation_pattern"], json.dumps(_public_candidate(c)),
             json.dumps(c["feasibility"]), json.dumps(c.get("utility")),
             c["feasibility"]["status"] if c["feasibility"]["status"] != "SCOREABLE" else
             ("PENDING_APPROVAL" if c["candidate_id"] == recommended_id else "SCOREABLE"),
             _iso(datetime.now(timezone.utc))),
        )
    conn.commit()
    db.write_audit("RECOMMENDATION_CREATED", object_id=recommendation_id, state_after=state_version,
                    explanation=f"recommended={recommended_id}, no_acceptable_plan={no_acceptable}")

    return {
        "urgency": urgency_result,
        "candidates": [
            {"candidate": _public_candidate(c), "feasibility": c["feasibility"], "utility": c.get("utility")}
            for c in evaluated
        ],
        "recommendation": {
            "schema_version": "1.0",
            "context": context,
            "recommendation_id": recommendation_id,
            "need_id": need_id,
            "ranked_candidate_ids": [c["candidate_id"] for c in ranked],
            "recommended_candidate_id": recommended_id,
            "no_acceptable_plan": no_acceptable,
            "reason_codes": [] if not no_acceptable else ["NO_SCOREABLE_CANDIDATE"],
            "expires_at": expires_at,
            "ranking": ranking_payload,
            "explanation": explanation,
            "status": "PENDING_APPROVAL",
        },
    }, 200


def _public_candidate(c):
    """Strips internal plan_inputs (used only by the Feasibility Engine)
    before a candidate is stored/serialized, per the CandidatePlan
    contract (spec 144.6)."""
    return {k: v for k, v in c.items() if k not in ("plan_inputs", "feasibility", "utility")}


def _build_explanation(top, need, urgency_result):
    if top is None:
        return {
            "full_coverage": False, "arrives_before_failure": False,
            "downstream_risk": "UNKNOWN", "mission_disruption": "UNKNOWN",
            "route_status": "UNKNOWN", "weather_risk": "UNKNOWN", "uncertainty_codes": ["NO_ACCEPTABLE_PLAN"],
        }
    d = top["utility"]["factors"]["downstream_safety"]
    return {
        "full_coverage": top["fulfillment_fraction"] >= 0.999,
        "arrives_before_failure": (urgency_result["ttf_minutes"] is None
                                    or top["eta_minutes"] <= urgency_result["ttf_minutes"]),
        "downstream_risk": "LOW" if d >= 0.7 else ("MODERATE" if d >= 0.4 else "HIGH"),
        "mission_disruption": "NONE",
        "route_status": "OPEN" if top["feasibility"]["factors"]["route"] >= 0.99 else "DEGRADED",
        "weather_risk": "LOW" if top["plan_inputs"]["weather_risk"] < 0.3 else "MODERATE",
        "uncertainty_codes": top["feasibility"]["uncertainty_codes"],
    }


# ---------------------------------------------------------------------------
# Pareto dominance filter + ranking (spec sections 128-130)
# ---------------------------------------------------------------------------
def _dominates(a, b):
    fa, fb = a["utility"]["factors"], b["utility"]["factors"]
    keys = ["system_impact", "effective_coverage", "downstream_safety",
            "mission_continuity", "operational_efficiency", "future_optionality"]
    at_least_as_good = all(fa[k] >= fb[k] for k in keys)
    strictly_better = any(fa[k] > fb[k] for k in keys)
    return at_least_as_good and strictly_better


def pareto_filter(cands):
    keep = []
    for c in cands:
        dominated = any(_dominates(other, c) for other in cands if other is not c)
        if not dominated:
            keep.append(c)
    return keep


def rank_plans(scoreable_candidates):
    """spec section 129 FUNCTION RankPlans (adapted: feasibility/utility are
    already attached upstream by plan_need)."""
    normal = [c for c in scoreable_candidates if c["feasibility"]["score_internal"] >= cfg.MINIMUM_NORMAL_RANKING_SCORE]
    fallback = [c for c in scoreable_candidates if c["feasibility"]["score_internal"] < cfg.MINIMUM_NORMAL_RANKING_SCORE]

    pool = pareto_filter(normal) if normal else pareto_filter(fallback)

    def sort_key(c):
        return c["utility"]["score_internal"]

    pool.sort(key=sort_key, reverse=True)

    # Tie-break (spec 130): if top candidates are within 0.2 utility,
    # reorder by I desc, D desc, F desc, M desc, ETA asc.
    def tie_break(c):
        u = c["utility"]["factors"]
        return (-u["system_impact"], -u["downstream_safety"],
                -c["feasibility"]["score_internal"], -u["mission_continuity"], c["eta_minutes"])

    if len(pool) >= 2 and abs(pool[0]["utility"]["score_internal"] - pool[1]["utility"]["score_internal"]) < cfg.TIE_BREAK_EPSILON:
        pool.sort(key=tie_break)

    return pool
