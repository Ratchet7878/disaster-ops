"""
Utility Engine  —  spec sections 112 through 134.

    J = 0.40 I + 0.20 C + 0.15 D + 0.10 M + 0.10 E + 0.05 O
    Utility = 1 + 9J

System Impact (I) requires a *common baseline*: every candidate for a
ranking run is compared against the same B0 computed from the same
active-need cohort (spec 144.2 DecisionContext / UTIL-02). Mission
continuity is scoped to missions this prototype actually models — since
the MVP candidate generator never reassigns a vehicle away from an
active mission (Pattern H "Mission Reassignment" is out of MVP scope per
spec 107.1), M is always 1 here; the formula is still implemented in
full so a future REASSIGNMENT candidate slots in without changes.
"""
import math
from .. import config as cfg
from .urgency import clamp


def normalized_urgency(score_1_to_10):
    return (score_1_to_10 - 1) / 9.0


def unmet_fraction(target_qty, projected_qty):
    if not target_qty or target_qty <= 0:
        return 0.0
    return clamp((target_qty - (projected_qty or 0)) / target_qty)


def system_burden(need_states):
    """need_states: list of {u0, target_qty, projected_qty}. Spec 117.4."""
    num = sum(n["u0"] * unmet_fraction(n["target_qty"], n["projected_qty"]) for n in need_states)
    den = sum(n["u0"] for n in need_states) + cfg.EPSILON
    return num / den


def system_impact(b_before, b_after):
    """I factor, spec 117.5."""
    return clamp((b_before - b_after) / (b_before + cfg.EPSILON))


def effective_coverage(deliveries, required_qty, ttf_minutes):
    """C factor, spec 119. deliveries: list of (quantity, eta_minutes)."""
    if not required_qty or required_qty <= 0:
        return 1.0
    if ttf_minutes is None or ttf_minutes == math.inf:
        ttf_minutes = float("inf")
    q_effective = 0.0
    for qty, eta in deliveries:
        lateness = max(0.0, eta - ttf_minutes) if ttf_minutes != float("inf") else 0.0
        discount = math.exp(-lateness / cfg.LATENESS_DECAY_MINUTES)
        q_effective += qty * discount
    return clamp(q_effective / required_qty)


def downstream_safety(affected_sources):
    """D factor, spec 120. affected_sources: list of
    {after_qty, reserve_qty, buffer_qty}. Empty -> Dp = 1 (no donor)."""
    if not affected_sources:
        return 1.0
    values = []
    for s in affected_sources:
        buffer = max(s["buffer_qty"], cfg.EPSILON)
        values.append(clamp((s["after_qty"] - s["reserve_qty"]) / buffer))
    return min(values)


def mission_continuity(affected_missions):
    """M factor, spec 121. affected_missions: list of
    {delay_minutes, slack_minutes, urgency_score}. Empty -> Mp = 1."""
    if not affected_missions:
        return 1.0
    num = 0.0
    den = 0.0
    for m in affected_missions:
        slack_plus = max(m["slack_minutes"], 1.0)
        r_j = clamp(m["delay_minutes"] / slack_plus)
        u_j = normalized_urgency(m["urgency_score"])
        num += u_j * r_j
        den += u_j
    return 1 - (num / (den + cfg.EPSILON))


def operational_efficiency(vehicle_minutes, distance_km, n_trips, avg_load_utilization):
    """E factor, spec 122."""
    w = cfg.EFFICIENCY_SUBWEIGHTS
    e_t = clamp(vehicle_minutes / cfg.VEHICLE_TIME_REFERENCE_MINUTES)
    e_d = clamp(distance_km / cfg.DISTANCE_REFERENCE_KM)
    e_n = clamp((n_trips - 1) / max(cfg.TRIP_COUNT_REFERENCE - 1, 1))
    score = 1 - (w["vehicle_time"] * e_t + w["distance"] * e_d + w["trips"] * e_n
                 + w["load"] * (1 - avg_load_utilization))
    return clamp(score)


def future_optionality(vehicles_available_after, vehicles_operational, resource_surplus_ratios):
    """O factor, spec 123."""
    o_v = vehicles_available_after / (vehicles_operational + cfg.EPSILON)
    o_r = (sum(clamp(r) for r in resource_surplus_ratios) / len(resource_surplus_ratios)
           if resource_surplus_ratios else 1.0)
    sw = cfg.OPTIONALITY_SUBWEIGHTS
    return clamp(sw["vehicle_reserve"] * o_v + sw["resource_reserve"] * o_r)


BAND_TABLE = [
    (1.0, 2.9, "VERY_POOR"),
    (3.0, 4.9, "POOR"),
    (5.0, 6.4, "ACCEPTABLE"),
    (6.5, 7.9, "GOOD"),
    (8.0, 8.9, "VERY_GOOD"),
    (9.0, 10.0, "EXCELLENT"),
]


def band_for(score):
    if score is None:
        return None
    for lo, hi, name in BAND_TABLE:
        if lo - 1e-9 <= score <= hi + 1e-9:
            return name
    return "EXCELLENT" if score > 10 else "VERY_POOR"


def calculate_utility(components, context, candidate_id, baseline_state_version):
    """components: dict with I, C, D, M, E, O already computed."""
    w = cfg.UTILITY_WEIGHTS
    j = (
        w["system_impact"] * components["I"]
        + w["coverage"] * components["C"]
        + w["downstream_safety"] * components["D"]
        + w["mission_continuity"] * components["M"]
        + w["efficiency"] * components["E"]
        + w["optionality"] * components["O"]
    )
    score = clamp(1 + 9 * j, 1.0, 10.0)
    return {
        "schema_version": "1.0",
        "context": context,
        "candidate_id": candidate_id,
        "status": "CALCULATED",
        "score_internal": score,
        "score_display": round(score, 1),
        "band": band_for(score),
        "factors": {
            "system_impact": round(components["I"], 3),
            "effective_coverage": round(components["C"], 3),
            "downstream_safety": round(components["D"], 3),
            "mission_continuity": round(components["M"], 3),
            "operational_efficiency": round(components["E"], 3),
            "future_optionality": round(components["O"], 3),
        },
        "baseline_state_version": baseline_state_version,
        "projected_state_hash": None,
        "assumptions": components.get("assumptions", []),
        "uncertainty_codes": [],
    }
