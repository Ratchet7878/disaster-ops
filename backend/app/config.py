"""
DisasterOps Decision Configuration
===================================
Per spec section 144.9 ("Configuration Source of Truth"):
  "Every coefficient, threshold, reserve, time scale, display band, hard
  deadline, and factor weight MUST come from one versioned configuration
  snapshot. Production code MUST NOT duplicate numeric policy values
  across modules."

Every number used by the Urgency / Feasibility / Utility engines lives
HERE and only here. Engines import this module; they never hard-code a
coefficient inline. This is what let the spec's own worked examples
(sections 15, 65, 126) be reproduced by the live engine instead of typed
in as fixtures.
"""

CONFIG_VERSION = "prototype-2026-09-13.1"
ALGORITHM_VERSION = "disasterops-decision-brain-1.0"

# ---------------------------------------------------------------------------
# Urgency Engine  (spec section 7-18)
#   U = 1 + 9*(0.40 T + 0.20 S + 0.15 V + 0.15 P + 0.10 A)
# ---------------------------------------------------------------------------
URGENCY_WEIGHTS = {
    "time_pressure": 0.40,
    "resource_severity": 0.20,
    "vulnerability": 0.15,
    "population": 0.15,
    "local_coping": 0.10,
}

# tau_r (critical-time scale, minutes) and kappa_r (curve sharpness) per resource.
# tau_water = 3h, kappa_water = 2 are the spec's own worked-example values
# (section 8.1); the rest are prototype extrapolations of the same policy.
RESOURCE_TIME_SCALES_MINUTES = {
    "WATER": 180,
    "FOOD": 360,
    "MEDICAL_SUPPLIES": 60,
    "BATTERY": 480,
    "BLANKET": 720,
    "HYGIENE_KIT": 1440,
}
RESOURCE_TIME_EXPONENTS = {
    "WATER": 2.0,
    "FOOD": 2.0,
    "MEDICAL_SUPPLIES": 2.0,
    "BATTERY": 2.0,
    "BLANKET": 2.0,
    "HYGIENE_KIT": 2.0,
}

# Resource / Condition severity table S in [0,1] (spec section 9).
SEVERITY_TABLE = {
    "HYGIENE_KIT": 0.20,
    "BLANKET": 0.30,
    "BATTERY": 0.50,
    "FOOD": 0.60,
    "WATER": 0.80,
    "POWER": 1.00,              # spec section 9: critical essential power
    "MEDICAL_SUPPLIES": 1.00,
}

POPULATION_REFERENCE = 500          # N_ref (spec section 11)
VULNERABILITY_REFERENCE = 0.30      # q_ref (spec section 10)

# Local-coping scale A (spec section 12) keyed by a qualitative situation
# label a shelter report can select from a dropdown.
LOCAL_COPING_A = {
    "SEVERAL_VERIFIED_SUBSTITUTES": 0.10,
    "ONE_STRONG_FALLBACK": 0.30,
    "PARTIAL_FALLBACK": 0.60,
    "WEAK_UNVERIFIED_FALLBACK": 0.80,
    "NONE": 1.00,
}

# Data-confidence sub-model for Urgency (spec section 17):
#   CD = 0.50 M + 0.30 F + 0.20 R
URGENCY_CONFIDENCE_WEIGHTS = {"completeness": 0.50, "freshness": 0.30, "reliability": 0.20}
URGENCY_FRESHNESS_TAU_MINUTES = 120

# Source reliability table R (spec section 17.3)
SOURCE_RELIABILITY = {
    "OFFICIAL_MUNICIPALITY_SYSTEM": 1.00,
    "VERIFIED_SHELTER_MANAGER": 0.90,
    "EMERGENCY_RESPONDER": 0.90,
    "REGISTERED_VOLUNTEER": 0.70,
    "UNVERIFIED_PUBLIC_REPORT": 0.40,
    "UNKNOWN_SOURCE": 0.20,
}

LOW_CONFIDENCE_THRESHOLD = 0.50     # below this, urgency is shown "Provisional"

# ---------------------------------------------------------------------------
# Feasibility Engine  (spec sections 50-64)
#   F = 1 + 9*(0.16R+0.17E+0.11V+0.13S+0.09D+0.07C+0.05A+0.06W+0.04B+0.12Q)
# ---------------------------------------------------------------------------
FEASIBILITY_WEIGHTS = {
    "route": 0.16,          # R
    "eta_margin": 0.17,     # E
    "vehicle": 0.11,        # V
    "resource": 0.13,       # S
    "road_reliability": 0.09,  # D
    "complexity": 0.07,     # C
    "approval": 0.05,       # A
    "weather": 0.06,        # W
    "alt_source": 0.04,     # B
    "data_confidence": 0.12,  # Q
}
MINIMUM_NORMAL_RANKING_SCORE = 6.0    # F_min (spec section 114)
VEHICLE_HEADROOM_REFERENCE = 0.25     # h_v   (spec section 55)
RESOURCE_HEADROOM_REFERENCE = 0.50    # h_s   (spec section 56)
VEHICLE_AVAILABILITY_TAU_MINUTES = 30  # tau_v (spec section 55)
ROAD_FRESHNESS_TAU_MINUTES = 60        # tau_r (spec section 57)
ALT_SOURCE_DELAY_TAU_MINUTES = 60      # tau_B (spec section 61)

# Road passability table (spec section 53)
ROAD_PASSABILITY = {
    "OPEN": 1.00,
    "RESTRICTED": 0.65,
    "UNKNOWN": 0.35,
    "BLOCKED": 0.00,
}

# Data-confidence sub-model for Feasibility (spec section 62):
#   Q = 0.40 M + 0.30 Fd + 0.30 Rs
FEASIBILITY_CONFIDENCE_WEIGHTS = {"completeness": 0.40, "freshness": 0.30, "reliability": 0.30}
FEASIBILITY_FRESHNESS_TAU_MINUTES = 60

# ---------------------------------------------------------------------------
# Utility Engine  (spec sections 112-134)
#   J = 0.40 I + 0.20 C + 0.15 D + 0.10 M + 0.10 E + 0.05 O
# ---------------------------------------------------------------------------
UTILITY_WEIGHTS = {
    "system_impact": 0.40,      # I
    "coverage": 0.20,           # C
    "downstream_safety": 0.15,  # D
    "mission_continuity": 0.10,  # M
    "efficiency": 0.10,         # E
    "optionality": 0.05,        # O
}
EVALUATION_HORIZON_MINUTES = 240      # H_eval (spec section 118)
LATENESS_DECAY_MINUTES = 60           # tau_L  (spec section 119.2)
EFFICIENCY_SUBWEIGHTS = {"vehicle_time": 0.45, "distance": 0.25, "trips": 0.15, "load": 0.15}
VEHICLE_TIME_REFERENCE_MINUTES = 180  # T_ref (spec section 122.1)
DISTANCE_REFERENCE_KM = 100           # D_ref (spec section 122.2)
TRIP_COUNT_REFERENCE = 4              # N_ref (spec section 122.3)
OPTIONALITY_SUBWEIGHTS = {"vehicle_reserve": 0.50, "resource_reserve": 0.50}
TIE_BREAK_EPSILON = 0.2               # spec section 130

# Minimum safety reserve fraction kept back at every warehouse/shelter for
# each resource type unless a report specifies otherwise.
DEFAULT_RESERVE_FRACTION = 0.15

# Average vehicle travel speed used by the mock routing engine (km/h), since
# no live Google Maps integration is available in this prototype (spec
# section 174 treats Maps as a pluggable external service).
MOCK_AVERAGE_SPEED_KMH = 40

# Vehicle capacity is stored in one physical unit (cargo-litres of cargo
# volume) so a single vehicle fleet can be compared across resource types
# that each keep their own canonical unit (ml, portions, items, hours).
# This factor converts 1 canonical unit of a resource into cargo-litres.
# Candidate generation (not the Feasibility Engine, which stays
# unit-agnostic) uses this to compute how much of a resource a given
# vehicle can actually carry.
CARGO_LITRES_PER_UNIT = {
    "WATER": 0.001,             # 1 ml
    "FOOD": 0.5,                # 1 meal portion
    "BLANKET": 3.0,             # 1 blanket (bulky)
    "BATTERY": 0.15,            # 1 battery
    "MEDICAL_SUPPLIES": 1.0,    # 1 supply unit
    "HYGIENE_KIT": 2.0,         # 1 kit
    "POWER": 5.0,               # 1 hour-equivalent of generator fuel/capacity
}

EPSILON = 1e-6
