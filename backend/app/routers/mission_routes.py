"""
Mission routes  —  spec section 153 (Volunteer Delivery Screen) and
section 164 API map.
"""
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from .. import db
from ..auth import require_auth, can_access_shelter, forbidden_shelter, STAFF_ROLES

bp = Blueprint("missions", __name__, url_prefix="/api/missions")


def _mission_to_dict(row):
    return {
        "mission_id": row["mission_id"], "candidate_id": row["candidate_id"], "need_id": row["need_id"],
        "vehicle_id": row["vehicle_id"], "source_type": row["source_type"], "source_id": row["source_id"],
        "destination_shelter_id": row["destination_shelter_id"], "resource_type": row["resource_type"],
        "quantity_canonical": row["quantity_canonical"], "unit": row["unit"], "depart_at": row["depart_at"],
        "eta_minutes": row["eta_minutes"], "status": row["status"], "created_at": row["created_at"],
        "delivered_at": row["delivered_at"], "actual_quantity_received": row["actual_quantity_received"],
        "damaged_or_missing": row["damaged_or_missing"],
    }


@bp.route("", methods=["GET"])
@require_auth
def list_missions():
    conn = db.get_db()
    role = g.current_user["role"]
    if role in ("VOLUNTEER", "SHELTER_MANAGER"):
        rows = conn.execute(
            "SELECT * FROM missions WHERE destination_shelter_id=? ORDER BY created_at DESC",
            (g.current_user.get("assigned_shelter_id"),),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM missions ORDER BY created_at DESC").fetchall()
    return jsonify([_mission_to_dict(r) for r in rows])


@bp.route("/<mission_id>", methods=["GET"])
@require_auth
def get_mission(mission_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM missions WHERE mission_id=?", (mission_id,)).fetchone()
    if row is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    if not can_access_shelter(row["destination_shelter_id"]):
        return forbidden_shelter()
    return jsonify(_mission_to_dict(row))


@bp.route("/<mission_id>/status", methods=["POST"])
@require_auth
def update_status(mission_id):
    conn = db.get_db()
    mission = conn.execute("SELECT * FROM missions WHERE mission_id=?", (mission_id,)).fetchone()
    if mission is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    if not can_access_shelter(mission["destination_shelter_id"]):
        return forbidden_shelter()
    body = request.get_json(force=True) or {}
    new_status = body.get("status")
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if new_status not in ("DELIVERED", "IN_TRANSIT", "DELAYED", "CANCELLED"):
        return jsonify({"error": "VALIDATION_ERROR", "message": "unsupported status"}), 422
    # A closed mission must not be changed again: re-delivering would add
    # the stock to the shelter twice and take it from the warehouse twice.
    if mission["status"] in ("DELIVERED", "CANCELLED"):
        return jsonify({"error": "MISSION_CLOSED", "status": mission["status"]}), 409
    if new_status == "CANCELLED" and g.current_user["role"] not in STAFF_ROLES:
        return jsonify({"error": "FORBIDDEN", "message": "Only coordinators can cancel a mission"}), 403

    if new_status == "DELIVERED":
        actual = body.get("actual_quantity_received", mission["quantity_canonical"])
        damaged = body.get("damaged_or_missing", 0)
        for v in (actual, damaged):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                return jsonify({"error": "VALIDATION_ERROR",
                                "message": "received/damaged quantities must be non-negative numbers"}), 422
        conn.execute(
            "UPDATE missions SET status='DELIVERED', delivered_at=?, actual_quantity_received=?, "
            "damaged_or_missing=? WHERE mission_id=?",
            (now_iso, actual, damaged, mission_id),
        )
        # Receiving shelter's on-hand increases; source warehouse's committed
        # quantity is released (it was already decremented from on-hand at
        # approval time for cross-shelter transfers, or held as `committed`
        # for warehouse sources).
        conn.execute(
            "UPDATE shelter_resources SET quantity_canonical = COALESCE(quantity_canonical,0) + ? "
            "WHERE shelter_id=? AND resource_type=?",
            (actual, mission["destination_shelter_id"], mission["resource_type"]),
        )
        if mission["source_type"] == "WAREHOUSE":
            conn.execute(
                "UPDATE warehouse_inventory SET quantity_on_hand_canonical = quantity_on_hand_canonical - ?, "
                "committed_quantity_canonical = committed_quantity_canonical - ? "
                "WHERE warehouse_id=? AND resource_type=?",
                (mission["quantity_canonical"], mission["quantity_canonical"], mission["source_id"], mission["resource_type"]),
            )
        conn.execute("UPDATE vehicles SET status='AVAILABLE', available_at=NULL WHERE vehicle_id=?",
                     (mission["vehicle_id"],))

        need = conn.execute("SELECT * FROM needs WHERE need_id=?", (mission["need_id"],)).fetchone()
        if need is not None:
            res = conn.execute(
                "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
                (need["shelter_id"], need["resource_type"]),
            ).fetchone()
            if res and res["quantity_canonical"] is not None and res["quantity_canonical"] >= need["target_quantity_canonical"]:
                conn.execute("UPDATE needs SET status='FULFILLED' WHERE need_id=?", (need["need_id"],))
            else:
                conn.execute("UPDATE needs SET status='ACTIVE' WHERE need_id=?", (need["need_id"],))
    elif new_status in ("IN_TRANSIT", "DELAYED", "CANCELLED"):
        conn.execute("UPDATE missions SET status=? WHERE mission_id=?", (new_status, mission_id))
        if new_status == "CANCELLED":
            conn.execute("UPDATE vehicles SET status='AVAILABLE', available_at=NULL WHERE vehicle_id=?",
                         (mission["vehicle_id"],))
            # Undo what approval reserved: warehouse stock is un-committed,
            # a donor shelter gets its stock back, and a need that was
            # marked STABILIZED by this mission becomes ACTIVE again.
            if mission["source_type"] == "WAREHOUSE":
                conn.execute(
                    "UPDATE warehouse_inventory SET committed_quantity_canonical = "
                    "MAX(committed_quantity_canonical - ?, 0) WHERE warehouse_id=? AND resource_type=?",
                    (mission["quantity_canonical"], mission["source_id"], mission["resource_type"]))
            else:
                conn.execute(
                    "UPDATE shelter_resources SET quantity_canonical = COALESCE(quantity_canonical,0) + ? "
                    "WHERE shelter_id=? AND resource_type=?",
                    (mission["quantity_canonical"], mission["source_id"], mission["resource_type"]))
            conn.execute("UPDATE needs SET status='ACTIVE' WHERE need_id=? AND status='STABILIZED'",
                         (mission["need_id"],))

    new_version = db.bump_state_version()
    conn.commit()
    db.write_audit("MISSION_STATUS_CHANGED", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=mission_id, state_after=new_version, reason_codes=[new_status])
    return jsonify({"mission_id": mission_id, "status": new_status, "state_version": new_version})
