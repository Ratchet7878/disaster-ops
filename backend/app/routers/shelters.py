"""
Shelter routes  —  spec section 164 API map + sections 30-49 (report intake).
"""
import json
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from .. import db
from ..auth import require_auth, can_access_shelter, forbidden_shelter
from .. import config as cfg


def _bad(message):
    return jsonify({"error": "VALIDATION_ERROR", "message": message}), 422


def _num(v):
    """True for a real, non-negative number (bool excluded)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0

bp = Blueprint("shelters", __name__, url_prefix="/api/shelters")


def _shelter_to_dict(row, conn):
    resources = conn.execute(
        "SELECT * FROM shelter_resources WHERE shelter_id=?", (row["shelter_id"],)
    ).fetchall()
    needs = conn.execute(
        "SELECT * FROM needs WHERE shelter_id=? AND status='ACTIVE'", (row["shelter_id"],)
    ).fetchall()
    return {
        "shelter_id": row["shelter_id"],
        "name": row["name"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "population_total": row["population_total"],
        "vulnerable_total": (row["vulnerable_elderly"] + row["vulnerable_mobility"]
                              + row["vulnerable_pregnant"] + row["vulnerable_young_children"]),
        "vulnerable_breakdown": {
            "elderly": row["vulnerable_elderly"], "mobility_assistance": row["vulnerable_mobility"],
            "pregnant": row["vulnerable_pregnant"], "young_children": row["vulnerable_young_children"],
        },
        "infrastructure": {
            "electricity": row["electricity_status"], "water_supply": row["water_supply_status"],
            "sanitation": row["sanitation_status"], "mobile_network": row["mobile_network_status"],
        },
        "road_access": {
            "primary_segment_id": row["primary_road_segment_id"],
            "secondary_segment_id": row["secondary_road_segment_id"],
        },
        "local_coping_situation": row["local_coping_situation"],
        "last_report_at": row["last_report_at"],
        "last_report_source": row["last_report_source"],
        "resources": [dict(r) for r in resources],
        "active_need_ids": [n["need_id"] for n in needs],
    }


@bp.route("", methods=["GET"])
@require_auth
def list_shelters():
    conn = db.get_db()
    role = g.current_user["role"]
    if role in ("VOLUNTEER", "SHELTER_MANAGER"):
        shelter_id = g.current_user.get("assigned_shelter_id")
        rows = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM shelters").fetchall()
    return jsonify([_shelter_to_dict(r, conn) for r in rows])


@bp.route("/<shelter_id>", methods=["GET"])
@require_auth
def get_shelter(shelter_id):
    if not can_access_shelter(shelter_id):
        return forbidden_shelter()
    conn = db.get_db()
    row = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchone()
    if row is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    return jsonify(_shelter_to_dict(row, conn))


@bp.route("/<shelter_id>/reports", methods=["POST"])
@require_auth
def submit_report(shelter_id):
    """Spec section 165 Example Shelter Report JSON. Idempotent on
    idempotency_key (spec 144.10 / EVT-01)."""
    if not can_access_shelter(shelter_id):
        return forbidden_shelter()
    conn = db.get_db()
    body = request.get_json(force=True) or {}
    idem_key = body.get("idempotency_key") or request.headers.get("Idempotency-Key")

    if idem_key:
        existing = conn.execute(
            "SELECT * FROM shelter_reports WHERE idempotency_key=?", (idem_key,)
        ).fetchone()
        if existing is not None and existing["shelter_id"] == shelter_id:
            return jsonify({"report_id": existing["report_id"], "replayed": True,
                             "state_version": existing["state_version_after"]}), 200

    shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchone()
    if shelter is None:
        return jsonify({"error": "NOT_FOUND"}), 404

    report_id = f"REPORT_{uuid.uuid4().hex[:10]}"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Validate before touching the database so a bad report changes nothing.
    population = body.get("population") or {}
    if population.get("total") is not None and not _num(population["total"]):
        return _bad("population.total must be a non-negative number")
    for k, v in (body.get("vulnerable_groups") or {}).items():
        if not _num(v):
            return _bad(f"vulnerable_groups.{k} must be a non-negative number")
    for res in body.get("resources") or []:
        if not isinstance(res, dict) or not res.get("type"):
            return _bad("every resource needs a type")
        for key in ("quantity_canonical", "consumption_per_hour_canonical"):
            if res.get(key) is not None and not _num(res[key]):
                return _bad(f"resource {key} must be a non-negative number")
    road_status = (body.get("road_access") or {}).get("primary")
    if road_status and road_status not in cfg.ROAD_PASSABILITY:
        return _bad("road_access.primary must be one of " + ", ".join(cfg.ROAD_PASSABILITY))

    population = body.get("population") or {}
    if population.get("total") is not None:
        conn.execute("UPDATE shelters SET population_total=? WHERE shelter_id=?",
                     (population["total"], shelter_id))

    vulnerable = body.get("vulnerable_groups") or {}
    if vulnerable:
        conn.execute(
            "UPDATE shelters SET vulnerable_elderly=?, vulnerable_mobility=?, "
            "vulnerable_pregnant=?, vulnerable_young_children=? WHERE shelter_id=?",
            (vulnerable.get("elderly", shelter["vulnerable_elderly"]),
             vulnerable.get("mobility_assistance", shelter["vulnerable_mobility"]),
             vulnerable.get("pregnant", shelter["vulnerable_pregnant"]),
             vulnerable.get("young_children", shelter["vulnerable_young_children"]), shelter_id),
        )

    for res in body.get("resources", []):
        existing_res = conn.execute(
            "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
            (shelter_id, res["type"]),
        ).fetchone()
        if existing_res is None:
            conn.execute(
                "INSERT INTO shelter_resources (shelter_id,resource_type,quantity_canonical,unit,"
                "consumption_per_hour_canonical,measurement,last_checked_at,reserve_quantity_canonical) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (shelter_id, res["type"], res.get("quantity_canonical"), res.get("unit", "UNIT"),
                 res.get("consumption_per_hour_canonical"), res.get("measurement", "ESTIMATED"), now_iso),
            )
        else:
            conn.execute(
                "UPDATE shelter_resources SET quantity_canonical=?, measurement=?, last_checked_at=? "
                "WHERE shelter_id=? AND resource_type=?",
                (res.get("quantity_canonical"), res.get("measurement", "ESTIMATED"), now_iso,
                 shelter_id, res["type"]),
            )

    infra = body.get("infrastructure") or {}
    if infra:
        conn.execute(
            "UPDATE shelters SET electricity_status=?, water_supply_status=?, "
            "sanitation_status=?, mobile_network_status=? WHERE shelter_id=?",
            (infra.get("electricity", shelter["electricity_status"]),
             infra.get("water_supply", shelter["water_supply_status"]),
             infra.get("sanitation", shelter["sanitation_status"]),
             infra.get("mobile_network", shelter["mobile_network_status"]), shelter_id),
        )

    road = body.get("road_access") or {}
    if road.get("primary") and shelter["primary_road_segment_id"]:
        conn.execute("UPDATE road_segments SET status=?, last_updated_at=? WHERE road_segment_id=?",
                     (road["primary"], now_iso, shelter["primary_road_segment_id"]))

    conn.execute("UPDATE shelters SET last_report_at=?, last_report_source=? WHERE shelter_id=?",
                 (now_iso, body.get("source", "REGISTERED_VOLUNTEER"), shelter_id))

    new_version = db.bump_state_version()
    conn.execute(
        "INSERT INTO shelter_reports (report_id, idempotency_key, shelter_id, occurred_at, "
        "received_at, report_type, payload_json, state_version_after, source) VALUES (?,?,?,?,?,?,?,?,?)",
        (report_id, idem_key, shelter_id, body.get("occurred_at", now_iso), now_iso, "HOURLY",
         json.dumps(body), new_version, body.get("source", "REGISTERED_VOLUNTEER")),
    )
    conn.commit()
    db.write_audit("REPORT_SUBMITTED", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=shelter_id, state_after=new_version)

    return jsonify({"report_id": report_id, "state_version": new_version}), 201


@bp.route("/<shelter_id>/critical-updates", methods=["POST"])
@require_auth
def critical_update(shelter_id):
    """Spec section 151.1 — creates an event immediately, doesn't wait
    for the next hourly cycle."""
    if not can_access_shelter(shelter_id):
        return forbidden_shelter()
    conn = db.get_db()
    body = request.get_json(force=True) or {}
    shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchone()
    if shelter is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report_id = f"CRIT_{uuid.uuid4().hex[:10]}"

    category = body.get("category")
    if category == "ROAD_BLOCKED":
        seg_id = body.get("road_segment_id") or shelter["primary_road_segment_id"]
        if seg_id:
            conn.execute("UPDATE road_segments SET status='BLOCKED', last_updated_at=? WHERE road_segment_id=?",
                         (now_iso, seg_id))
            conn.execute("INSERT INTO road_events VALUES (?,?,?,?,?)",
                         (f"EVT_{uuid.uuid4().hex[:8]}", seg_id, "BLOCKED", now_iso, body.get("description")))
    elif category == "POWER_FAILURE":
        conn.execute("UPDATE shelters SET electricity_status='FAILED' WHERE shelter_id=?", (shelter_id,))

    new_version = db.bump_state_version()
    conn.execute(
        "INSERT INTO shelter_reports (report_id, idempotency_key, shelter_id, occurred_at, "
        "received_at, report_type, payload_json, state_version_after, source) VALUES (?,?,?,?,?,?,?,?,?)",
        (report_id, None, shelter_id, now_iso, now_iso, "CRITICAL_UPDATE", json.dumps(body),
         new_version, body.get("source", "REGISTERED_VOLUNTEER")),
    )
    conn.commit()
    db.write_audit("CRITICAL_UPDATE_SUBMITTED", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=shelter_id, state_after=new_version, reason_codes=[category] if category else None)
    return jsonify({"report_id": report_id, "state_version": new_version}), 201


@bp.route("/<shelter_id>/requests", methods=["POST"])
@require_auth
def create_request(shelter_id):
    """Spec section 152 — human-perceived urgency is stored but is NEVER
    substituted for the computed urgency score (explicit spec rule)."""
    if not can_access_shelter(shelter_id):
        return forbidden_shelter()
    conn = db.get_db()
    body = request.get_json(force=True) or {}
    if conn.execute("SELECT 1 FROM shelters WHERE shelter_id=?", (shelter_id,)).fetchone() is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    if not isinstance(body.get("resource_type"), str) or not body["resource_type"]:
        return _bad("resource_type is required")
    qty = body.get("quantity_requested_canonical")
    if not _num(qty) or qty <= 0:
        return _bad("quantity_requested_canonical must be a positive number")
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request_id = f"REQ_{uuid.uuid4().hex[:10]}"
    conn.execute(
        "INSERT INTO resource_requests (request_id, shelter_id, resource_type, "
        "quantity_requested_canonical, reason, human_perceived_urgency, created_at, status) "
        "VALUES (?,?,?,?,?,?,?, 'OPEN')",
        (request_id, shelter_id, body["resource_type"], body["quantity_requested_canonical"],
         body.get("reason"), body.get("human_perceived_urgency"), now_iso),
    )

    resource_type = body["resource_type"]
    existing_need = conn.execute(
        "SELECT * FROM needs WHERE shelter_id=? AND resource_type=? AND status='ACTIVE'",
        (shelter_id, resource_type),
    ).fetchone()
    if existing_need is None:
        need_id = f"NEED_{uuid.uuid4().hex[:8]}"
        res_row = conn.execute(
            "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
            (shelter_id, resource_type),
        ).fetchone()
        unit = res_row["unit"] if res_row else "UNIT"
        on_hand = (res_row["quantity_canonical"] if res_row and res_row["quantity_canonical"] else 0)
        target = on_hand + body["quantity_requested_canonical"]
        conn.execute(
            "INSERT INTO needs (need_id, shelter_id, resource_type, unit, target_quantity_canonical, "
            "status, created_at) VALUES (?,?,?,?,?, 'ACTIVE', ?)",
            (need_id, shelter_id, resource_type, unit, target, now_iso),
        )

    new_version = db.bump_state_version()
    conn.commit()
    db.write_audit("SUPPLY_REQUEST_CREATED", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=request_id, state_after=new_version)
    return jsonify({"request_id": request_id, "state_version": new_version}), 201
