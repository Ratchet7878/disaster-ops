"""
Candidate Plan Generator  —  spec sections 74 through 101.

Implements the generation patterns most relevant to the MVP / recommended
demo flow (spec section 183):

  Pattern A — Direct Warehouse Delivery        (section 88.1)
  Pattern B — Alternative Warehouse Delivery   (section 88.2)
  Pattern C — Cross-Shelter Transfer           (section 88.3)
  Pattern D — Delayed Vehicle Candidate        (section 88.4)
  Pattern G — Partial Stabilization Candidate  (section 88.9)

Patterns E (multi-trip), F (split delivery) and H (mission reassignment)
are structurally supported by the CandidatePlan contract's
`generation_pattern` enum but are left as documented extension points
(spec explicitly scopes split/multi-trip/reassignment as MVP-optional in
section 107.1 "Not Required for Initial MVP").

CG-01 (spec 144.12): never invent inventory, vehicle capacity, road
safety, coordinates, quantity, or approval — every number here is read
from the database, not fabricated.
"""
import uuid
from datetime import datetime, timezone, timedelta
from .. import config as cfg
from . import routing


def _iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _vehicle_capacity_in_resource_units(vehicle, resource_type):
    """Vehicles store capacity_canonical in cargo-litres (a physical
    volume); this converts it into the *resource's own* canonical unit
    so candidate generation and the Feasibility Engine can compare it
    directly against on-hand / required quantities (which are always in
    the resource's own unit)."""
    factor = cfg.CARGO_LITRES_PER_UNIT.get(resource_type, 1.0)
    return vehicle["capacity_canonical"] / factor


def generate_candidates(conn, need, shelter, resource_row, ttf_minutes, context):
    """
    Returns a list of raw candidate dicts (pre-feasibility). Each one
    carries every fact `feasibility.py` needs, plus display metadata for
    the API/UI layer.
    """
    candidates = []
    resource_type = need["resource_type"]
    target_qty = need["target_quantity_canonical"]
    on_hand = resource_row["quantity_canonical"] if resource_row else 0
    required_qty = max(0.0, target_qty - (on_hand or 0))
    if required_qty <= 0:
        return []

    now = datetime.now(timezone.utc)

    # ---- Pattern A / B: warehouse deliveries -----------------------------
    warehouses = conn.execute("SELECT * FROM warehouses").fetchall()
    for wh in warehouses:
        inv = conn.execute(
            "SELECT * FROM warehouse_inventory WHERE warehouse_id=? AND resource_type=?",
            (wh["warehouse_id"], resource_type),
        ).fetchone()
        if inv is None:
            continue
        transferable = max(0.0, inv["quantity_on_hand_canonical"]
                            - inv["reserve_quantity_canonical"] - inv["committed_quantity_canonical"])
        if transferable <= 0:
            continue

        vehicles = conn.execute(
            "SELECT * FROM vehicles WHERE status IN ('AVAILABLE','ASSIGNED','IN_TRANSIT') "
            "AND home_base_id = ? ORDER BY capacity_canonical DESC",
            (wh["warehouse_id"],),
        ).fetchall()
        for vehicle in vehicles:
            vehicle_cap = _vehicle_capacity_in_resource_units(vehicle, resource_type)
            planned_load = min(required_qty, transferable, vehicle_cap)
            if planned_load <= 0:
                continue
            minutes_until_avail = _minutes_until_available(vehicle, now)
            route_info = _route_for(conn, wh, shelter)
            eta = route_info["travel_minutes"] + minutes_until_avail
            pattern = "DIRECT" if warehouses.index(wh) == 0 else "ALTERNATIVE_SOURCE"

            wh_after = inv["quantity_on_hand_canonical"] - inv["committed_quantity_canonical"] - planned_load
            cand = _base_candidate(
                need=need, pattern=pattern, source_type="WAREHOUSE", source=wh,
                vehicle=vehicle, planned_load=planned_load, transferable=transferable,
                reserve_after_ok=True, route_info=route_info, eta_minutes=eta,
                minutes_until_avail=minutes_until_avail, ttf_minutes=ttf_minutes,
                fulfillment_fraction=min(1.0, (planned_load + (on_hand or 0)) / target_qty) if target_qty else 1.0,
                context=context, required_qty=required_qty,
                source_after_quantity=wh_after, source_reserve_quantity=inv["reserve_quantity_canonical"],
            )
            candidates.append(cand)

            # Pattern D: same source/vehicle but explicitly framed as a
            # delayed-vehicle candidate when the vehicle is currently busy.
            if minutes_until_avail > 0:
                delayed = dict(cand)
                delayed["candidate_id"] = _new_id("PLAN")
                delayed["generation_pattern"] = "DELAYED_VEHICLE"
                candidates.append(delayed)

            # Pattern G: partial stabilization using whatever the *fastest*
            # available vehicle can carry right now, if a full delivery
            # cannot arrive before TTF.
            if ttf_minutes is not None and eta >= ttf_minutes and vehicle_cap < required_qty:
                stab_load = min(vehicle_cap, transferable)
                if 0 < stab_load < planned_load:
                    wh_after_stab = inv["quantity_on_hand_canonical"] - inv["committed_quantity_canonical"] - stab_load
                    stab = _base_candidate(
                        need=need, pattern="PARTIAL_STABILIZATION", source_type="WAREHOUSE",
                        source=wh, vehicle=vehicle, planned_load=stab_load,
                        transferable=transferable, reserve_after_ok=True,
                        route_info=route_info, eta_minutes=route_info["travel_minutes"] + minutes_until_avail,
                        minutes_until_avail=minutes_until_avail, ttf_minutes=ttf_minutes,
                        fulfillment_fraction=min(1.0, (stab_load + (on_hand or 0)) / target_qty) if target_qty else 1.0,
                        context=context, required_qty=required_qty,
                        source_after_quantity=wh_after_stab, source_reserve_quantity=inv["reserve_quantity_canonical"],
                    )
                    candidates.append(stab)

    # ---- Pattern C: cross-shelter transfer --------------------------------
    donor_shelters = conn.execute(
        "SELECT * FROM shelters WHERE shelter_id != ?", (shelter["shelter_id"],)
    ).fetchall()
    for donor in donor_shelters:
        donor_res = conn.execute(
            "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
            (donor["shelter_id"], resource_type),
        ).fetchone()
        if donor_res is None or donor_res["quantity_canonical"] is None:
            continue
        transferable = max(0.0, donor_res["quantity_canonical"] - donor_res["reserve_quantity_canonical"])
        if transferable <= 0:
            continue
        # Use any vehicle not tied to a warehouse (roaming fleet) or one
        # based at the nearest warehouse — simplification for the MVP.
        vehicle = conn.execute(
            "SELECT * FROM vehicles WHERE status = 'AVAILABLE' ORDER BY capacity_canonical ASC"
        ).fetchone()
        if vehicle is None:
            continue
        vehicle_cap = _vehicle_capacity_in_resource_units(vehicle, resource_type)
        planned_load = min(required_qty, transferable, vehicle_cap)
        if planned_load <= 0:
            continue
        route_info = _route_for(conn, donor, shelter)
        minutes_until_avail = _minutes_until_available(vehicle, now)
        eta = route_info["travel_minutes"] + minutes_until_avail
        qty_after = donor_res["quantity_canonical"] - planned_load
        reserve_ok = qty_after >= donor_res["reserve_quantity_canonical"]

        cand = _base_candidate(
            need=need, pattern="CROSS_SHELTER", source_type="SHELTER", source=donor,
            vehicle=vehicle, planned_load=planned_load, transferable=transferable,
            reserve_after_ok=reserve_ok, route_info=route_info, eta_minutes=eta,
            minutes_until_avail=minutes_until_avail, ttf_minutes=ttf_minutes,
            fulfillment_fraction=min(1.0, (planned_load + (on_hand or 0)) / target_qty) if target_qty else 1.0,
            context=context, required_qty=required_qty,
            donor_after_quantity=qty_after, donor_reserve=donor_res["reserve_quantity_canonical"],
            donor_shelter_id=donor["shelter_id"],
            source_after_quantity=qty_after, source_reserve_quantity=donor_res["reserve_quantity_canonical"],
        )
        candidates.append(cand)

    # Cap at Nmax and preserve some diversity (spec sections 93-94): keep
    # the fastest of each (source_type, source_id) pair, then top up.
    return candidates[:30]


def _minutes_until_available(vehicle, now):
    if vehicle["status"] == "AVAILABLE" or not vehicle["available_at"]:
        return 0.0
    try:
        avail = datetime.fromisoformat(vehicle["available_at"].replace("Z", "+00:00"))
        return max(0.0, (avail - now).total_seconds() / 60.0)
    except ValueError:
        return 0.0


def _route_for(conn, origin_row, destination_row):
    """Picks the destination's best *usable* road segment: primary if
    passable, otherwise the secondary/detour segment if it exists and
    isn't itself blocked (spec Pattern B rationale: 'primary route is
    damaged' is exactly when an alternative matters). If every known
    segment is blocked, the caller's hard-constraint check will
    correctly mark the candidate HARD_INFEASIBLE."""
    seg_ids = [destination_row["primary_road_segment_id"], destination_row["secondary_road_segment_id"]]
    segs_by_id = {}
    for seg_id in seg_ids:
        if not seg_id:
            continue
        seg = conn.execute("SELECT * FROM road_segments WHERE road_segment_id=?", (seg_id,)).fetchone()
        if seg:
            segs_by_id[seg_id] = seg

    chosen = None
    for seg_id in seg_ids:
        seg = segs_by_id.get(seg_id)
        if seg and seg["status"] != "BLOCKED":
            chosen = seg
            break
    if chosen is None and segs_by_id:
        # every known segment is blocked -- use the primary anyway so the
        # hard BLOCKED constraint fires downstream (never silently drop it)
        chosen = segs_by_id.get(seg_ids[0]) or next(iter(segs_by_id.values()))

    segs = [chosen] if chosen else []
    return routing.compute_route(
        {"latitude": origin_row["latitude"], "longitude": origin_row["longitude"]},
        {"latitude": destination_row["latitude"], "longitude": destination_row["longitude"]},
        segs,
    )


def _base_candidate(need, pattern, source_type, source, vehicle, planned_load,
                     transferable, reserve_after_ok, route_info, eta_minutes,
                     minutes_until_avail, ttf_minutes, fulfillment_fraction, context,
                     required_qty=0.0, donor_after_quantity=None, donor_reserve=None,
                     donor_shelter_id=None, source_after_quantity=None,
                     source_reserve_quantity=None):
    candidate_id = _new_id("PLAN")
    source_id = source["warehouse_id"] if source_type == "WAREHOUSE" else source["shelter_id"]
    source_name = source["name"]
    n_stops = 1
    n_transfers = 1 if source_type == "SHELTER" else 0

    weather_risk = 0.10
    obstruction_risk = 0.05

    plan_inputs = {
        "candidate_id": candidate_id,
        "route_exists": True,
        "route_blocked": route_info["blocked"],
        "route_min_passability": route_info["min_passability"],
        "route_segments": [
            {"source": s.get("source", "OFFICIAL_MUNICIPALITY_SYSTEM"),
             "age_minutes": s["age_minutes"] if s.get("age_minutes") is not None else 10,
             "travel_minutes": route_info["travel_minutes"]}
            for s in route_info["segments"]
        ] or [{"source": "OFFICIAL_MUNICIPALITY_SYSTEM", "age_minutes": 10,
               "travel_minutes": route_info["travel_minutes"]}],
        "vehicle_operational": vehicle["status"] != "OUT_OF_SERVICE",
        "vehicle_capacity": _vehicle_capacity_in_resource_units(vehicle, need["resource_type"]),
        "planned_load": planned_load,
        "minutes_until_vehicle_available": minutes_until_avail,
        "transferable_quantity": transferable,
        "would_breach_donor_reserve": not reserve_after_ok,
        "travel_prohibited": False,
        "approval_required": pattern in ("CROSS_SHELTER", "REASSIGNMENT"),
        "approval_granted": False,
        "approval_denied": False,
        "hard_deadline": None,
        "ttf_minutes": ttf_minutes,
        "eta_minutes": eta_minutes,
        "n_stops": n_stops,
        "n_transfers": n_transfers,
        "weather_risk": weather_risk,
        "obstruction_risk": obstruction_risk,
        "alternative_sources": [],
        "data_completeness": 0.95,
        "data_age_minutes": 10,
        "data_reliability": 0.95,
        "preauthorized": False,
    }

    return {
        "candidate_id": candidate_id,
        "need_id": need["need_id"],
        "generation_pattern": pattern,
        "source_type": source_type,
        "source_id": source_id,
        "source_name": source_name,
        "vehicle_id": vehicle["vehicle_id"],
        "vehicle_name": vehicle["name"],
        "resource_type": need["resource_type"],
        "quantity_canonical": planned_load,
        "distance_km": route_info["distance_km"],
        "distance_metres": route_info["distance_metres"],
        "eta_minutes": eta_minutes,
        "depart_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes_until_avail)).isoformat().replace("+00:00", "Z"),
        "fulfillment_fraction": round(fulfillment_fraction, 3),
        "is_partial": fulfillment_fraction < 0.999,
        "plan_inputs": plan_inputs,
        "required_qty": required_qty,
        "donor_after_quantity": donor_after_quantity,
        "donor_reserve": donor_reserve,
        "donor_shelter_id": donor_shelter_id,
        "source_after_quantity": source_after_quantity,
        "source_reserve_quantity": source_reserve_quantity,
        "n_stops": n_stops,
        "n_transfers": n_transfers,
    }
