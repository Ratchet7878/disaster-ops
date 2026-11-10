"""
Authentication  —  spec sections 148-149 (login flow, RBAC table).

Lightweight JWT auth (PyJWT, already available) instead of a session
store. Good enough for a hackathon prototype; swapping in a real OAuth /
SSO provider later would only touch this file.
"""
import functools
import os
import jwt
from datetime import datetime, timezone, timedelta
from flask import request, jsonify, g
from werkzeug.security import check_password_hash
from . import db

JWT_SECRET = os.environ.get("DISASTEROPS_JWT_SECRET", "disasterops-hackathon-demo-secret-not-for-production")
JWT_ALGO = "HS256"
TOKEN_TTL_HOURS = 12


def issue_token(user_row):
    payload = {
        "user_id": user_row["user_id"],
        "role": user_row["role"],
        "assigned_shelter_id": user_row["assigned_shelter_id"],
        "name": user_row["name"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError:
        return None


def login(email, password):
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return None
    conn.execute("UPDATE users SET last_login=? WHERE user_id=?",
                 (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), user["user_id"]))
    conn.commit()
    return user


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "UNAUTHORIZED", "message": "Missing bearer token"}), 401
        payload = decode_token(auth_header[len("Bearer "):])
        if payload is None:
            return jsonify({"error": "UNAUTHORIZED", "message": "Invalid or expired token"}), 401
        g.current_user = payload
        return f(*args, **kwargs)
    return wrapper


def require_role(*roles):
    def decorator(f):
        @functools.wraps(f)
        @require_auth
        def wrapper(*args, **kwargs):
            if g.current_user["role"] not in roles:
                return jsonify({"error": "FORBIDDEN", "message": f"Requires role in {roles}"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


STAFF_ROLES = ("COORDINATOR", "ADMIN")
SHELTER_ROLES = ("VOLUNTEER", "SHELTER_MANAGER")


def can_access_shelter(shelter_id):
    """Coordinators/admins see every shelter; volunteers and shelter
    managers only their own assigned shelter (spec section 149)."""
    user = g.current_user
    if user["role"] in STAFF_ROLES:
        return True
    return user["role"] in SHELTER_ROLES and user.get("assigned_shelter_id") == shelter_id


def forbidden_shelter():
    return jsonify({"error": "FORBIDDEN", "message": "Not assigned to this shelter"}), 403
