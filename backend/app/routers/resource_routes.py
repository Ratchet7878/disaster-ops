"""
Resource / vehicle / road / weather / audit routes  —  spec section 164
API map (GET /api/vehicles, /api/resources, /api/roads, POST
/api/roads/events, GET /api/weather, GET /api/audit).
"""
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from .. import db
from ..auth import require_auth, require_role

bp = Blueprint("resources", __name__, url_prefix="/api")


@bp.route("/vehicles", methods=["GET"])
@require_auth
def list_vehicles():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM vehicles").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/resources", methods=["GET"])
@require_auth
def list_resources():
    """Warehouses + their inventory — the coordinator's system-wide
    resource picture (spec section 154 dashboard requirement)."""
    conn = db.get_db()
    warehouses = conn.execute("SELECT * FROM warehouses").fetchall()
    out = []
    for wh in warehouses:
        inv = conn.execute("SELECT * FROM warehouse_inventory WHERE warehouse_id=?", (wh["warehouse_id"],)).fetchall()
        out.append({
            "warehouse_id": wh["warehouse_id"], "name": wh["name"],
            "latitude": wh["latitude"], "longitude": wh["longitude"],
            "inventory": [dict(i) for i in inv],
        })
    return jsonify(out)


@bp.route("/roads", methods=["GET"])
@require_auth
def list_roads():
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM road_segments").fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/roads/events", methods=["POST"])
@require_role("COORDINATOR", "ADMIN")
def road_event():
    """Spec section 175 (Event-Driven Replanning): a ROAD_BLOCKED event
    must invalidate every active candidate/mission whose required route
    intersects the closed segment (REP-01), and the UI-visible effect is
    that affected needs get a fresh recommendation with the closure
    already accounted for. This endpoint is also what the demo's
    'Simulate Road Closure' button calls (spec section 183)."""
    conn = db.get_db()
    body = request.get_json(force=True) or {}
    segment_id = body.get("road_segment_id")
    new_status = body.get("new_status", "BLOCKED")
    from .. import config as cfg
    if not segment_id:
        return jsonify({"error": "VALIDATION_ERROR", "message": "road_segment_id is required"}), 422
    if new_status not in cfg.ROAD_PASSABILITY:
        return jsonify({"error": "VALIDATION_ERROR",
                        "message": "new_status must be one of " + ", ".join(cfg.ROAD_PASSABILITY)}), 422
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    seg = conn.execute("SELECT * FROM road_segments WHERE road_segment_id=?", (segment_id,)).fetchone()
    if seg is None:
        return jsonify({"error": "NOT_FOUND"}), 404

    conn.execute("UPDATE road_segments SET status=?, last_updated_at=? WHERE road_segment_id=?",
                 (new_status, now_iso, segment_id))
    conn.execute("INSERT INTO road_events VALUES (?,?,?,?,?)",
                 (f"EVT_{uuid.uuid4().hex[:8]}", segment_id, new_status, now_iso, body.get("note")))

    affected_shelters = conn.execute(
        "SELECT * FROM shelters WHERE primary_road_segment_id=? OR secondary_road_segment_id=?",
        (segment_id, segment_id),
    ).fetchall()

    # REP-01: invalidate every active/pending candidate whose route used
    # this shelter (our routing model binds one segment per shelter).
    affected_need_ids = []
    for shelter in affected_shelters:
        needs = conn.execute(
            "SELECT * FROM needs WHERE shelter_id=? AND status='ACTIVE'", (shelter["shelter_id"],)
        ).fetchall()
        affected_need_ids.extend(n["need_id"] for n in needs)
        conn.execute(
            "UPDATE recommendations SET status='SUPERSEDED' WHERE need_id IN "
            "(SELECT need_id FROM needs WHERE shelter_id=?) AND status='PENDING_APPROVAL'",
            (shelter["shelter_id"],),
        )

    new_version = db.bump_state_version()
    conn.commit()
    db.write_audit("ROAD_EVENT", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=segment_id, state_after=new_version, reason_codes=[new_status])

    # Auto-replan every need the closure touched, so the coordinator
    # dashboard can show a fresh recommendation immediately (spec 183's
    # recommended demo flow: closure -> invalidate -> regenerate ->
    # recalc feasibility/utility -> new recommendation).
    from ..decision import ranking
    replanned = []
    for need_id in set(affected_need_ids):
        result, _ = ranking.plan_need(need_id)
        replanned.append({"need_id": need_id, "result": result})

    return jsonify({
        "road_segment_id": segment_id, "new_status": new_status, "state_version": new_version,
        "affected_shelters": [s["shelter_id"] for s in affected_shelters],
        "replanned": replanned,
    })


@bp.route("/weather", methods=["GET"])
@require_auth
def get_weather():
    conn = db.get_db()
    row = conn.execute("SELECT * FROM weather_snapshots ORDER BY recorded_at DESC LIMIT 1").fetchone()
    return jsonify(dict(row) if row else None)


@bp.route("/audit", methods=["GET"])
@require_role("COORDINATOR", "ADMIN")
def audit_log():
    conn = db.get_db()
    limit = request.args.get("limit", 100, type=int)
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY occurred_at DESC LIMIT ?", (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])
