from flask import Blueprint, request, jsonify, g
from .. import db
from ..auth import login as auth_login, issue_token, require_auth

bp = Blueprint("auth", __name__, url_prefix="/api")


@bp.route("/auth/login", methods=["POST"])
def login():
    body = request.get_json(force=True) or {}
    user = auth_login(body.get("email", ""), body.get("password", ""))
    if user is None:
        return jsonify({"error": "INVALID_CREDENTIALS"}), 401
    token = issue_token(user)
    return jsonify({
        "token": token,
        "user": {
            "user_id": user["user_id"], "name": user["name"], "email": user["email"],
            "role": user["role"], "assigned_shelter_id": user["assigned_shelter_id"],
        },
    })


@bp.route("/me", methods=["GET"])
@require_auth
def me():
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (g.current_user["user_id"],)).fetchone()
    if user is None:
        return jsonify({"error": "NOT_FOUND"}), 404
    return jsonify({
        "user_id": user["user_id"], "name": user["name"], "email": user["email"],
        "role": user["role"], "assigned_shelter_id": user["assigned_shelter_id"],
    })


@bp.route("/municipality", methods=["GET"])
@require_auth
def municipality():
    row = db.get_db().execute("SELECT name FROM municipalities LIMIT 1").fetchone()
    return jsonify({"name": row["name"] if row else "Emergency Management"})


@bp.route("/demo-users", methods=["GET"])
def demo_users():
    """Convenience endpoint (not in the original spec) so the login
    screen can offer one-click demo accounts instead of making judges
    type passwords during a live demo."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT user_id, name, email, role, assigned_shelter_id FROM users ORDER BY role, email"
    ).fetchall()
    return jsonify([dict(r) for r in rows])
