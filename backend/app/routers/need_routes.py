"""
Need routes  —  spec section 164 (/api/needs, /api/needs/:id/recalculate)
and section 172 (the full planning pipeline).
"""
import json
from flask import Blueprint, jsonify, g
from .. import db
from ..auth import require_auth, require_role, can_access_shelter, forbidden_shelter
from ..decision import urgency as U
from ..decision import ranking

bp = Blueprint("needs", __name__, url_prefix="/api/needs")


def _live_urgency_for_need(conn, need, context):
    shelter = conn.execute("SELECT * FROM shelters WHERE shelter_id=?", (need["shelter_id"],)).fetchone()
    res = conn.execute(
        "SELECT * FROM shelter_resources WHERE shelter_id=? AND resource_type=?",
        (need["shelter_id"], need["resource_type"]),
    ).fetchone()
    return U.calculate_urgency(need, shelter, res, context)


@bp.route("", methods=["GET"])
@require_auth
def list_needs():
    conn = db.get_db()
    state_version = db.current_state_version()
    context = ranking.build_context(state_version)
    role = g.current_user["role"]
    if role in ("VOLUNTEER", "SHELTER_MANAGER"):
        rows = conn.execute(
            "SELECT * FROM needs WHERE status='ACTIVE' AND shelter_id=?",
            (g.current_user.get("assigned_shelter_id"),),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM needs WHERE status='ACTIVE'").fetchall()

    out = []
    for n in rows:
        ur = _live_urgency_for_need(conn, n, context)
        shelter = conn.execute("SELECT name FROM shelters WHERE shelter_id=?", (n["shelter_id"],)).fetchone()
        latest_rec = conn.execute(
            "SELECT * FROM recommendations WHERE need_id=? ORDER BY created_at DESC LIMIT 1", (n["need_id"],)
        ).fetchone()
        out.append({
            "need_id": n["need_id"], "shelter_id": n["shelter_id"], "shelter_name": shelter["name"],
            "resource_type": n["resource_type"], "target_quantity_canonical": n["target_quantity_canonical"],
            "unit": n["unit"], "status": n["status"], "urgency": ur,
            "latest_recommendation_id": latest_rec["recommendation_id"] if latest_rec else None,
            "latest_recommendation_status": latest_rec["status"] if latest_rec else None,
        })
    out.sort(key=lambda x: x["urgency"]["score_internal"] or 0, reverse=True)
    return jsonify(out)


@bp.route("/<need_id>", methods=["GET"])
@require_auth
def get_need(need_id):
    conn = db.get_db()
    n = conn.execute("SELECT * FROM needs WHERE need_id=?", (need_id,)).fetchone()
    if n is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    if not can_access_shelter(n["shelter_id"]):
        return forbidden_shelter()
    context = ranking.build_context(db.current_state_version())
    ur = _live_urgency_for_need(conn, n, context)
    candidates = conn.execute(
        "SELECT * FROM candidate_plans WHERE need_id=? ORDER BY created_at DESC LIMIT 30", (need_id,)
    ).fetchall()
    return jsonify({
        "need_id": n["need_id"], "shelter_id": n["shelter_id"], "resource_type": n["resource_type"],
        "target_quantity_canonical": n["target_quantity_canonical"], "unit": n["unit"],
        "status": n["status"], "urgency": ur,
        "candidates": [
            {"candidate": json.loads(c["plan_json"]),
             "feasibility": json.loads(c["feasibility_json"]) if c["feasibility_json"] else None,
             "utility": json.loads(c["utility_json"]) if c["utility_json"] else None,
             "status": c["status"]}
            for c in candidates
        ],
    })


@bp.route("/<need_id>/recalculate", methods=["POST"])
@require_role("COORDINATOR", "ADMIN")
def recalculate(need_id):
    """Runs the full Urgency -> Candidate Generation -> Feasibility ->
    Utility -> Ranking pipeline (spec section 172) and returns a fresh
    Recommendation."""
    result, status = ranking.plan_need(need_id)
    return jsonify(result), status
