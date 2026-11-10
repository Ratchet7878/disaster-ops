"""
Urgency Engine  —  spec sections 7 through 18.

    U = 1 + 9 * (0.40 T + 0.20 S + 0.15 V + 0.15 P + 0.10 A)

Normative invariants honored here (spec 144.12):
  URG-01  Urgency depends ONLY on need state, evaluation time, and
          versioned policy configuration.
  URG-02  Source / vehicle / route / candidate ETA are never inputs here.
  URG-03  If TTF <= 0, Time Pressure = 1 and a life-safety escalation fires.
  DATA-01 Unknown operational values remain None; never coerced to 0.
"""
import math
from .. import config as cfg


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def calculate_ttf(quantity, reserve, consumption_per_hour):
    """Time To Failure, in minutes. Spec section 8.1.

    Returns (ttf_minutes | None, reason_code | None).
    """
    if quantity is None or consumption_per_hour is None:
        return None, "TTF_UNKNOWN_MISSING_DATA"
    reserve = reserve or 0
    if consumption_per_hour < 0:
        return None, "INVALID_INPUT_NEGATIVE_CONSUMPTION"
    if consumption_per_hour == 0:
        return (math.inf, None) if quantity > reserve else (0.0, None)
    ttf_hours = (quantity - reserve) / consumption_per_hour
    return ttf_hours * 60.0, None


def time_pressure(ttf_minutes, resource_type):
    """T factor, spec section 8. ttf_minutes may be math.inf (no pressure)."""
    if ttf_minutes is None:
        return None
    if ttf_minutes <= 0:
        return 1.0
    if ttf_minutes == math.inf:
        return 0.0
    tau = cfg.RESOURCE_TIME_SCALES_MINUTES.get(resource_type, 240)
    kappa = cfg.RESOURCE_TIME_EXPONENTS.get(resource_type, 2.0)
    return 1.0 / (1.0 + (ttf_minutes / tau) ** kappa)


def resource_severity(resource_type):
    """S factor, spec section 9 — a policy table lookup, never invented."""
    return cfg.SEVERITY_TABLE.get(resource_type, 0.50)


def vulnerability(n_total, n_vulnerable):
    """V factor, spec section 10."""
    if n_total is None or n_vulnerable is None:
        return None
    if n_total == 0 and n_vulnerable == 0:
        return 0.0
    if n_vulnerable > n_total or n_total < 0 or n_vulnerable < 0:
        return None  # INVALID_INPUT
    return clamp(n_vulnerable / (cfg.VULNERABILITY_REFERENCE * n_total))


def population_factor(n_total):
    """P factor, spec section 11 — logarithmic, prevents large-shelter dominance."""
    if n_total is None or n_total < 0:
        return None
    return clamp(math.log(1 + n_total) / math.log(1 + cfg.POPULATION_REFERENCE))


def local_coping_alt(local_coping_situation):
    """A factor, spec section 12 — qualitative table lookup."""
    return cfg.LOCAL_COPING_A.get(local_coping_situation, cfg.LOCAL_COPING_A["NONE"])


def data_completeness(present_fields, required_fields):
    if not required_fields:
        return 1.0
    have = sum(1 for f in required_fields if present_fields.get(f) is not None)
    return have / len(required_fields)


def data_freshness(age_minutes):
    if age_minutes is None:
        return 0.0
    return math.exp(-age_minutes / cfg.URGENCY_FRESHNESS_TAU_MINUTES)


def data_confidence(m, f, r):
    w = cfg.URGENCY_CONFIDENCE_WEIGHTS
    return w["completeness"] * m + w["freshness"] * f + w["reliability"] * r


BAND_TABLE = [
    (1.0, 2.9, "LOW"),
    (3.0, 4.9, "MODERATE"),
    (5.0, 6.9, "HIGH"),
    (7.0, 8.9, "VERY_HIGH"),
    (9.0, 10.0, "CRITICAL"),
]


def band_for(score):
    if score is None:
        return None
    for lo, hi, name in BAND_TABLE:
        if lo - 1e-9 <= score <= hi + 1e-9:
            return name
    return "CRITICAL" if score > 10 else "LOW"


def calculate_urgency(need, shelter_row, resource_row, context):
    """
    need: dict with need_id, resource_type, target_quantity_canonical
    shelter_row: sqlite Row for the shelter
    resource_row: sqlite Row for shelter_resources (may be None -> NEEDS_DATA)
    context: DecisionContext dict (state_version, config_version, as_of, ...)

    Returns a dict following the UrgencyResult contract (spec 144.5).
    """
    reason_codes = []
    missing_fields = []
    resource_type = need["resource_type"]

    quantity = resource_row["quantity_canonical"] if resource_row else None
    consumption = resource_row["consumption_per_hour_canonical"] if resource_row else None
    reserve = resource_row["reserve_quantity_canonical"] if resource_row else 0
    last_checked = resource_row["last_checked_at"] if resource_row else None

    n_total = shelter_row["population_total"]
    n_vulnerable = (
        (shelter_row["vulnerable_elderly"] or 0)
        + (shelter_row["vulnerable_mobility"] or 0)
        + (shelter_row["vulnerable_pregnant"] or 0)
        + (shelter_row["vulnerable_young_children"] or 0)
    )

    if quantity is None:
        missing_fields.append("quantity_canonical")
    if consumption is None:
        missing_fields.append("consumption_per_hour_canonical")

    ttf_minutes, ttf_reason = calculate_ttf(quantity, reserve, consumption)
    if ttf_reason:
        reason_codes.append(ttf_reason)

    T = time_pressure(ttf_minutes, resource_type)
    S = resource_severity(resource_type)
    V = vulnerability(n_total, n_vulnerable)
    P = population_factor(n_total)
    A = local_coping_alt(shelter_row["local_coping_situation"])

    factors = {
        "time_pressure": T,
        "resource_severity": S,
        "vulnerability": V,
        "population": P,
        "lack_of_local_coping": A,
    }

    if T is None or V is None or P is None:
        return {
            "schema_version": "1.0",
            "context": context,
            "need_id": need["need_id"],
            "status": "NEEDS_DATA",
            "score_internal": None,
            "score_display": None,
            "band": None,
            "factors": factors,
            "ttf_minutes": ttf_minutes if ttf_minutes != math.inf else None,
            "data_confidence": 0.0,
            "provisional": True,
            "missing_fields": missing_fields,
            "reason_codes": reason_codes or ["NEEDS_DATA"],
        }

    w = cfg.URGENCY_WEIGHTS
    raw = (
        w["time_pressure"] * T
        + w["resource_severity"] * S
        + w["vulnerability"] * V
        + w["population"] * P
        + w["local_coping"] * A
    )
    score = 1 + 9 * raw

    # Hard safety override (spec section 18): TTF <= 0 forces U >= 9.
    if ttf_minutes is not None and ttf_minutes <= 0:
        score = max(score, 9.0)
        reason_codes.append("HARD_SAFETY_OVERRIDE_TTF_REACHED")

    score = clamp(score, 1.0, 10.0)

    # Data confidence
    required = ["quantity_canonical", "consumption_per_hour_canonical", "population_total"]
    present = {
        "quantity_canonical": quantity,
        "consumption_per_hour_canonical": consumption,
        "population_total": n_total,
    }
    m = data_completeness(present, required)
    age = None
    if last_checked:
        from datetime import datetime, timezone
        try:
            checked = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age = max(0.0, (now - checked).total_seconds() / 60.0)
        except ValueError:
            age = None
    f_fresh = data_freshness(age)
    r_rel = cfg.SOURCE_RELIABILITY.get(shelter_row["last_report_source"], 0.5)
    cd = data_confidence(m, f_fresh, r_rel)

    provisional = cd < cfg.LOW_CONFIDENCE_THRESHOLD

    return {
        "schema_version": "1.0",
        "context": context,
        "need_id": need["need_id"],
        "status": "CALCULATED",
        "score_internal": score,
        "score_display": round(score, 1),
        "band": band_for(score),
        "factors": factors,
        "ttf_minutes": (None if ttf_minutes == math.inf else ttf_minutes),
        "data_confidence": round(cd, 3),
        "provisional": provisional,
        "missing_fields": missing_fields,
        "reason_codes": reason_codes,
    }
