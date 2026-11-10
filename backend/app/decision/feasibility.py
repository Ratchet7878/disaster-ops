"""
Feasibility Engine  —  spec sections 50 through 64.

    F = 1 + 9 * (0.16R + 0.17E + 0.11V + 0.13S + 0.09D + 0.07C
                 + 0.05A + 0.06W + 0.04B + 0.12Q)

Hard constraints (spec section 51) are checked FIRST. Any violation short
circuits to HARD_INFEASIBLE / NEEDS_DATA / INVALID_INPUT with score=None
(never 0.0 or 1.0 — spec section 50.2 is explicit that null must never be
confused with a valid-but-weak score).
"""
import math
from .. import config as cfg
from .urgency import clamp, data_freshness


def eta_margin(ttf_minutes, eta_minutes):
    """E factor, spec section 54."""
    if ttf_minutes is None or eta_minutes is None:
        return None
    if eta_minutes < 0:
        return None  # INVALID_INPUT
    if ttf_minutes <= 0:
        return 0.0
    if ttf_minutes == math.inf:
        return 1.0  # no failure horizon -> any timely arrival is comfortable
    return clamp((ttf_minutes - eta_minutes) / (0.5 * ttf_minutes))


def vehicle_factor(minutes_until_available, capacity, planned_load):
    """V factor, spec section 55. Returns None if capacity < load (caller
    must treat that as a HARD_INFEASIBLE before ever calling this)."""
    if capacity < planned_load:
        return None
    v_avail = math.exp(-minutes_until_available / cfg.VEHICLE_AVAILABILITY_TAU_MINUTES)
    margin = clamp((capacity - planned_load) / (cfg.VEHICLE_HEADROOM_REFERENCE * max(planned_load, cfg.EPSILON)))
    return v_avail * margin


def resource_factor(transferable, planned_load):
    """S factor, spec section 56. Caller enforces the hard constraint
    (transferable >= planned_load) separately."""
    if transferable < planned_load:
        return None
    return clamp((transferable - planned_load) / (cfg.RESOURCE_HEADROOM_REFERENCE * max(planned_load, cfg.EPSILON)))


def road_reliability(segments, travel_minutes_per_segment=None):
    """D factor, spec section 57. `segments` each need age_minutes and a
    source-reliability label; for the prototype we treat every segment's
    freshness as recorded on the road_segments table."""
    if not segments:
        return 1.0
    qualities = []
    weights = []
    for seg in segments:
        r_source = cfg.SOURCE_RELIABILITY.get(seg.get("source", "UNKNOWN_SOURCE"), 0.5)
        age = seg.get("age_minutes", 0) or 0
        f_i = math.exp(-age / cfg.ROAD_FRESHNESS_TAU_MINUTES)
        qualities.append(r_source * f_i)
        weights.append(seg.get("travel_minutes", 1.0) or 1.0)
    weighted_avg = sum(q * t for q, t in zip(qualities, weights)) / max(sum(weights), cfg.EPSILON)
    return 0.70 * min(qualities) + 0.30 * weighted_avg


def mission_complexity(n_stops, n_transfers):
    """C factor, spec section 58."""
    extra_stops = max(0, n_stops - 1)
    return math.exp(-0.25 * extra_stops - 0.45 * n_transfers)


def approval_readiness(approval_required, approval_granted):
    """A factor, spec section 59. Denial is handled as a hard constraint
    by the caller, not here."""
    if not approval_required or approval_granted:
        return 1.0
    return 0.0


def weather_obstruction_factor(weather_risk, obstruction_risk):
    """W factor, spec section 60."""
    wr = weather_risk if weather_risk is not None else 0.0
    orr = obstruction_risk if obstruction_risk is not None else 0.0
    return (1 - wr) * (1 - orr)


def alternative_source_factor(alternatives):
    """B factor, spec section 61. alternatives: list of dicts with
    coverage_fraction, reliability, delay_minutes."""
    if not alternatives:
        return 0.0
    best = 0.0
    for alt in alternatives:
        b_cov = clamp(alt["coverage_fraction"])
        b_delay = math.exp(-max(0, alt["delay_minutes"]) / cfg.ALT_SOURCE_DELAY_TAU_MINUTES)
        b = b_cov * alt["reliability"] * b_delay
        best = max(best, b)
    return best


def feasibility_data_confidence(completeness, freshness_minutes, reliability):
    """Q factor, spec section 62: Q = 0.40M + 0.30Fd + 0.30Rs."""
    w = cfg.FEASIBILITY_CONFIDENCE_WEIGHTS
    fd = data_freshness(freshness_minutes) if freshness_minutes is not None else 1.0
    return w["completeness"] * completeness + w["freshness"] * fd + w["reliability"] * reliability


BAND_TABLE = [
    (1.0, 3.9, "VERY_LOW"),
    (4.0, 5.9, "LOW"),
    (6.0, 7.4, "MODERATE"),
    (7.5, 8.9, "HIGH"),
    (9.0, 10.0, "VERY_HIGH"),
]


def band_for(score):
    if score is None:
        return None
    for lo, hi, name in BAND_TABLE:
        if lo - 1e-9 <= score <= hi + 1e-9:
            return name
    return "VERY_HIGH" if score > 10 else "VERY_LOW"


def calculate_feasibility(plan_inputs, context):
    """
    plan_inputs: dict assembled by candidates.py containing every physical
    fact the formulas need (see keys accessed below). This function is the
    single authority on HARD_INFEASIBLE / NEEDS_DATA / SCOREABLE status.

    Returns a dict following the FeasibilityResult contract (spec 144.7).
    """
    failed = []
    missing = []
    uncertainty = []
    facts = []

    # --- structural validity -------------------------------------------------
    if plan_inputs["planned_load"] <= 0:
        return _terminal(context, plan_inputs, "INVALID_INPUT", ["ZERO_OR_NEGATIVE_QUANTITY"])
    if plan_inputs["eta_minutes"] is not None and plan_inputs["eta_minutes"] < 0:
        return _terminal(context, plan_inputs, "INVALID_INPUT", ["NEGATIVE_ETA"])
    if plan_inputs["vehicle_capacity"] is not None and plan_inputs["vehicle_capacity"] < 0:
        return _terminal(context, plan_inputs, "INVALID_INPUT", ["NEGATIVE_VEHICLE_CAPACITY"])

    # --- essential data -------------------------------------------------------
    if plan_inputs.get("route_exists") is False:
        return _terminal(context, plan_inputs, "HARD_INFEASIBLE", ["NO_VALID_ROUTE"])
    if plan_inputs["transferable_quantity"] is None:
        missing.append("transferable_quantity")
    if plan_inputs["vehicle_capacity"] is None:
        missing.append("vehicle_capacity")
    if missing:
        return _terminal(context, plan_inputs, "NEEDS_DATA", ["NEEDS_DATA"], missing=missing)

    # --- hard constraints (spec section 51) -----------------------------------
    if plan_inputs["route_blocked"]:
        failed.append("BLOCKED_ROUTE_SEGMENT")
    if not plan_inputs["vehicle_operational"]:
        failed.append("VEHICLE_NOT_OPERATIONAL")
    if plan_inputs["vehicle_capacity"] < plan_inputs["planned_load"]:
        failed.append("VEHICLE_CAPACITY_EXCEEDED")
    if plan_inputs["transferable_quantity"] < plan_inputs["planned_load"]:
        failed.append("INSUFFICIENT_TRANSFERABLE_SOURCE")
    if plan_inputs.get("would_breach_donor_reserve"):
        failed.append("DONOR_RESERVE_BREACH")
    if plan_inputs.get("travel_prohibited"):
        failed.append("TRAVEL_PROHIBITED")
    if plan_inputs.get("approval_denied"):
        failed.append("APPROVAL_DENIED")
    if plan_inputs.get("hard_deadline") is not None and plan_inputs["eta_minutes"] is not None:
        if plan_inputs["eta_minutes"] > plan_inputs["hard_deadline"]:
            failed.append("HARD_DEADLINE_EXCEEDED")

    if failed:
        return _terminal(context, plan_inputs, "HARD_INFEASIBLE", failed)

    # --- weighted factors -------------------------------------------------
    R = plan_inputs["route_min_passability"]
    if plan_inputs["route_min_passability"] < 1.0:
        uncertainty.append("ROUTE_DATA_UNCERTAIN")

    E = eta_margin(plan_inputs["ttf_minutes"], plan_inputs["eta_minutes"])
    if E is None:
        E = 0.5
        uncertainty.append("TTF_UNKNOWN")

    V = vehicle_factor(plan_inputs["minutes_until_vehicle_available"],
                        plan_inputs["vehicle_capacity"], plan_inputs["planned_load"])
    S = resource_factor(plan_inputs["transferable_quantity"], plan_inputs["planned_load"])
    D = road_reliability(plan_inputs["route_segments"])
    C = mission_complexity(plan_inputs["n_stops"], plan_inputs["n_transfers"])
    A = approval_readiness(plan_inputs["approval_required"], plan_inputs["approval_granted"])
    W = weather_obstruction_factor(plan_inputs["weather_risk"], plan_inputs["obstruction_risk"])
    B = alternative_source_factor(plan_inputs.get("alternative_sources", []))
    Q = feasibility_data_confidence(plan_inputs["data_completeness"],
                                     plan_inputs.get("data_age_minutes"),
                                     plan_inputs["data_reliability"])

    w = cfg.FEASIBILITY_WEIGHTS
    f_raw = (
        w["route"] * R + w["eta_margin"] * E + w["vehicle"] * V + w["resource"] * S
        + w["road_reliability"] * D + w["complexity"] * C + w["approval"] * A
        + w["weather"] * W + w["alt_source"] * B + w["data_confidence"] * Q
    )
    score = clamp(1 + 9 * f_raw, 1.0, 10.0)

    factors = {"route": R, "eta_margin": E, "vehicle": V, "resource": S,
               "road_reliability": D, "complexity": C, "approval": A,
               "weather": W, "alt_source": B, "data_confidence": Q}

    if plan_inputs.get("preauthorized"):
        facts.append("Plan is pre-authorized under existing SOP/policy scope.")

    return {
        "schema_version": "1.0",
        "context": context,
        "candidate_id": plan_inputs["candidate_id"],
        "status": "SCOREABLE",
        "score_internal": score,
        "score_display": round(score, 1),
        "band": band_for(score),
        "factors": factors,
        "failed_constraints": [],
        "missing_fields": [],
        "uncertainty_codes": uncertainty,
        "explanation_facts": facts,
    }


def _terminal(context, plan_inputs, status, reason_codes, missing=None):
    return {
        "schema_version": "1.0",
        "context": context,
        "candidate_id": plan_inputs["candidate_id"],
        "status": status,
        "score_internal": None,
        "score_display": None,
        "band": None,
        "factors": None,
        "failed_constraints": reason_codes if status == "HARD_INFEASIBLE" else [],
        "missing_fields": missing or [],
        "uncertainty_codes": [],
        "explanation_facts": [],
    }
