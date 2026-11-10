"""
Recommendation routes  --  spec sections 138 (Human Approval), 157
(Approval Workflow state machine), 158 (Modify Plan), and 144.11
(Atomic Reservation and Approval Commit).
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, g
from .. import db
from ..auth import require_auth, require_role, can_access_shelter, forbidden_shelter
from ..decision import ranking

bp = Blueprint("recommendations", __name__, url_prefix="/api/recommendations")


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _get_rec(conn, rec_id):
    return conn.execute("SELECT * FROM recommendations WHERE recommendation_id=?", (rec_id,)).fetchone()


def _get_candidate(conn, candidate_id):
    row = conn.execute("SELECT * FROM candidate_plans WHERE candidate_id=?", (candidate_id,)).fetchone()
    if row is None:
        return None
    return {
        "row": row,
        "plan": json.loads(row["plan_json"]),
        "feasibility": json.loads(row["feasibility_json"]) if row["feasibility_json"] else None,
        "utility": json.loads(row["utility_json"]) if row["utility_json"] else None,
    }


def _rec_to_dict(row):
    return {
        "recommendation_id": row["recommendation_id"], "need_id": row["need_id"],
        "state_version": row["state_version"], "recommended_candidate_id": row["recommended_candidate_id"],
        "no_acceptable_plan": bool(row["no_acceptable_plan"]),
        "ranking": json.loads(row["ranking_json"]),
        "explanation": json.loads(row["explanation_json"]) if row["explanation_json"] else None,
        "created_at": row["created_at"], "expires_at": row["expires_at"], "status": row["status"],
    }


@bp.route("/need/<need_id>", methods=["GET"])
@require_auth
def get_for_need(need_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM recommendations WHERE need_id=? ORDER BY created_at DESC LIMIT 1", (need_id,)
    ).fetchone()
    if row is None:
        return jsonify(None)
    need = conn.execute("SELECT shelter_id FROM needs WHERE need_id=?", (need_id,)).fetchone()
    if need is not None and not can_access_shelter(need["shelter_id"]):
        return forbidden_shelter()
    return jsonify(_rec_to_dict(row))


def _revalidate_candidate(conn, candidate_bundle):
    """Cheap re-check against the CURRENT (possibly changed) state before
    ever committing a reservation, per spec 144.11 step 4 ("rerun all
    hard constraints against the current transaction snapshot")."""
    plan = candidate_bundle["plan"]
    reasons = []
    vehicle = conn.execute("SELECT * FROM vehicles WHERE vehicle_id=?", (plan["vehicle_id"],)).fetchone()
    if vehicle is None or vehicle["status"] == "OUT_OF_SERVICE":
        reasons.append("VEHICLE_NO_LONGER_OPERATIONAL")

    if plan["source_type"] == "WAREHOUSE":
        inv = conn.execute(
            "SELECT * FROM warehouse_inventory WHERE warehouse_id=? AND resource_type=?",
            (plan["source_id"], plan["resource_type"]),
        ).fetchone()
        if inv is None:
            reasons.append("SOURCE_NO_LONGER_EXISTS")
        else:
            transferable = (inv["quantity_on_hand_canonical"] - inv["reserve_quantity_canonical"]
                             - inv["committed_quantity_canonical"])
            if transferable < plan["quantity_canonical"]:
                reasons.append("INSUFFICIENT_TRANSFERABLE_SOURCE")
    else:
        res = conn.execute(
            "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
            (plan["source_id"], plan["resource_type"]),
        ).fetchone()
        if res is None or (res["quantity_canonical"] or 0) - res["reserve_quantity_canonical"] < plan["quantity_canonical"]:
            reasons.append("INSUFFICIENT_TRANSFERABLE_SOURCE")

    need_row = conn.execute("SELECT * FROM needs WHERE need_id=?", (plan["need_id"],)).fetchone()
    if need_row is not None:
        shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (need_row["shelter_id"],)).fetchone()
        if shelter and shelter["primary_road_segment_id"]:
            seg = conn.execute("SELECT * FROM road_segments WHERE road_segment_id=?",
                                (shelter["primary_road_segment_id"],)).fetchone()
            if seg and seg["status"] == "BLOCKED":
                reasons.append("ROUTE_NOW_BLOCKED")
    return reasons


def _commit_approval(rec_id, candidate_id, actor_id, reason=None):
    """The atomic-ish commit shared by /approve and /modify (spec
    144.11): reserve inventory + vehicle, create the mission, close out
    the recommendation and every sibling candidate. Returns
    (response_dict, http_status)."""
    conn = db.get_db()
    rec = _get_rec(conn, rec_id)
    if rec is None:
        return {"error": "NOT_FOUND"}, 404
    if rec["status"] != "PENDING_APPROVAL":
        return {"error": "NOT_PENDING", "status": rec["status"]}, 409

    now = datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(rec["expires_at"].replace("Z", "+00:00"))
    if now > expires_at:
        conn.execute("UPDATE recommendations SET status='EXPIRED' WHERE recommendation_id=?", (rec_id,))
        conn.commit()
        db.write_audit("APPROVAL_FAILED_STALE", actor_type="HUMAN", actor_id=actor_id,
                        object_id=rec_id, reason_codes=["STALE_RECOMMENDATION"])
        return {"error": "STALE_RECOMMENDATION", "message": "Recommendation expired; replanning required."}, 409

    bundle = _get_candidate(conn, candidate_id)
    if bundle is not None and bundle["plan"]["need_id"] != rec["need_id"]:
        return {"error": "VALIDATION_ERROR", "message": "candidate does not belong to this recommendation's need"}, 422
    if bundle is None or bundle["feasibility"] is None or bundle["feasibility"]["status"] != "SCOREABLE":
        return {"error": "CANDIDATE_NOT_SCOREABLE"}, 422
    if bundle["row"]["status"] in ("APPROVED", "SUPERSEDED", "REJECTED"):
        return {"error": "CANDIDATE_NOT_AVAILABLE", "status": bundle["row"]["status"]}, 409

    problems = _revalidate_candidate(conn, bundle)
    if problems:
        db.write_audit("APPROVAL_FAILED_REVALIDATION", actor_type="HUMAN", actor_id=actor_id,
                        object_id=rec_id, reason_codes=problems)
        return {"error": "STALE_STATE", "reasons": problems,
                "message": "Plan no longer valid against current state; replanning required."}, 409

    plan = bundle["plan"]
    try:
        if plan["source_type"] == "WAREHOUSE":
            conn.execute(
                "UPDATE warehouse_inventory SET committed_quantity_canonical = committed_quantity_canonical + ? "
                "WHERE warehouse_id=? AND resource_type=?",
                (plan["quantity_canonical"], plan["source_id"], plan["resource_type"]),
            )
        else:
            conn.execute(
                "UPDATE shelter_resources SET quantity_canonical = quantity_canonical - ? "
                "WHERE shelter_id=? AND resource_type=?",
                (plan["quantity_canonical"], plan["source_id"], plan["resource_type"]),
            )

        conn.execute("UPDATE vehicles SET status='IN_TRANSIT', available_at=? WHERE vehicle_id=?",
                     (_iso(now + timedelta(minutes=plan["eta_minutes"])), plan["vehicle_id"]))

        need_row = conn.execute("SELECT * FROM needs WHERE need_id=?", (plan["need_id"],)).fetchone()
        mission_id = f"MISSION_{uuid.uuid4().hex[:10]}"
        conn.execute(
            """INSERT INTO missions
               (mission_id, candidate_id, need_id, vehicle_id, source_type, source_id,
                destination_shelter_id, resource_type, quantity_canonical, unit,
                depart_at, eta_minutes, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'DISPATCHED', ?)""",
            (mission_id, candidate_id, plan["need_id"], plan["vehicle_id"], plan["source_type"],
             plan["source_id"], need_row["shelter_id"], plan["resource_type"], plan["quantity_canonical"],
             need_row["unit"], plan["depart_at"], plan["eta_minutes"], _iso(now)),
        )

        if plan["fulfillment_fraction"] >= 0.999:
            conn.execute("UPDATE needs SET status='STABILIZED' WHERE need_id=?", (plan["need_id"],))

        conn.execute(
            "INSERT INTO approvals (approval_id, recommendation_id, decision, actor_id, reason, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (f"APPR_{uuid.uuid4().hex[:8]}", rec_id, "APPROVE", actor_id, reason, _iso(now)),
        )
        conn.execute("UPDATE recommendations SET status='APPROVED' WHERE recommendation_id=?", (rec_id,))
        conn.execute(
            "UPDATE recommendations SET status='SUPERSEDED' WHERE need_id=? AND recommendation_id!=? "
            "AND status='PENDING_APPROVAL'", (plan["need_id"], rec_id))
        conn.execute("UPDATE candidate_plans SET status='APPROVED' WHERE candidate_id=?", (candidate_id,))
        conn.execute(
            "UPDATE candidate_plans SET status='SUPERSEDED' WHERE need_id=? AND candidate_id!=? "
            "AND status NOT IN ('HARD_INFEASIBLE','NEEDS_DATA','INVALID_INPUT')",
            (plan["need_id"], candidate_id),
        )
        new_version = db.bump_state_version()
        conn.commit()
    except Exception as exc:  # pragma: no cover - defensive rollback
        conn.rollback()
        return {"error": "COMMIT_FAILED", "message": str(exc)}, 500

    db.write_audit("COORDINATOR_APPROVED", actor_type="HUMAN", actor_id=actor_id,
                    object_id=rec_id, state_after=new_version)
    db.write_audit("MISSION_CREATED", actor_type="SYSTEM", object_id=mission_id, state_after=new_version)
    return {"mission_id": mission_id, "candidate_id": candidate_id, "state_version": new_version}, 200


@bp.route("/<rec_id>/approve", methods=["POST"])
@require_role("COORDINATOR", "ADMIN")
def approve(rec_id):
    conn = db.get_db()
    rec = _get_rec(conn, rec_id)
    if rec is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    body = request.get_json(silent=True) or {}
    candidate_id = body.get("candidate_id") or rec["recommended_candidate_id"]
    if not candidate_id:
        return jsonify({"error": "NO_ACCEPTABLE_PLAN"}), 422
    result, status = _commit_approval(rec_id, candidate_id, g.current_user["user_id"], body.get("reason"))
    return jsonify(result), status


@bp.route("/<rec_id>/reject", methods=["POST"])
@require_role("COORDINATOR", "ADMIN")
def reject(rec_id):
    conn = db.get_db()
    rec = _get_rec(conn, rec_id)
    if rec is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    if rec["status"] != "PENDING_APPROVAL":
        return jsonify({"error": "NOT_PENDING", "status": rec["status"]}), 409
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "No reason provided")

    conn.execute("UPDATE recommendations SET status='REJECTED' WHERE recommendation_id=?", (rec_id,))
    conn.execute(
        "INSERT INTO approvals (approval_id, recommendation_id, decision, actor_id, reason, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (f"APPR_{uuid.uuid4().hex[:8]}", rec_id, "REJECT", g.current_user["user_id"], reason,
         _iso(datetime.now(timezone.utc))),
    )
    if rec["recommended_candidate_id"]:
        conn.execute("UPDATE candidate_plans SET status='REJECTED' WHERE candidate_id=?",
                     (rec["recommended_candidate_id"],))
    conn.commit()
    db.write_audit("COORDINATOR_REJECTED", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=rec_id, reason_codes=[reason])

    # spec's approval workflow diagram: REJECT -> Record Reason -> Re-rank
    result, status = ranking.plan_need(rec["need_id"])
    return jsonify({"rejected": True, "replanned": result}), 200


@bp.route("/<rec_id>/modify", methods=["POST"])
@require_role("COORDINATOR", "ADMIN")
def modify(rec_id):
    """Coordinator selects a different candidate from the same ranking
    run (spec's 'SELECT ALTERNATIVE'). The chosen candidate is
    re-validated and, if still sound, committed exactly like /approve --
    a human must never bypass the deterministic safety system through
    the UI (spec section 158)."""
    body = request.get_json(force=True) or {}
    candidate_id = body.get("candidate_id")
    if not candidate_id:
        return jsonify({"error": "VALIDATION_ERROR", "message": "candidate_id required"}), 422

    conn = db.get_db()
    rec = _get_rec(conn, rec_id)
    if rec is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    bundle = _get_candidate(conn, candidate_id)
    if bundle is None or bundle["plan"]["need_id"] != rec["need_id"]:
        return jsonify({"error": "VALIDATION_ERROR", "message": "candidate does not belong to this need"}), 422
    if rec["status"] != "PENDING_APPROVAL":
        return jsonify({"error": "NOT_PENDING", "status": rec["status"]}), 409

    db.write_audit("COORDINATOR_MODIFIED", actor_type="HUMAN", actor_id=g.current_user["user_id"],
                    object_id=rec_id, reason_codes=["SELECTED_ALTERNATIVE:" + candidate_id])
    result, status = _commit_approval(
        rec_id, candidate_id, g.current_user["user_id"],
        body.get("reason", "Coordinator selected an alternative candidate"),
    )
    return jsonify(result), status
