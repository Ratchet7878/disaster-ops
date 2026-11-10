"""
DisasterOps backend entrypoint.

    python -m app.main

Serves the REST API on http://localhost:5001. Run `python -m app.seed`
first (or set AUTO_SEED=1) to populate the demo dataset.
"""
import os
from flask import Flask, jsonify
from . import db
from .routers import auth_routes, shelters, need_routes, recommendation_routes, mission_routes, resource_routes, agent_routes


def create_app():
    app = Flask(__name__)
    app.teardown_appcontext(db.close_db)

    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(shelters.bp)
    app.register_blueprint(need_routes.bp)
    app.register_blueprint(recommendation_routes.bp)
    app.register_blueprint(mission_routes.bp)
    app.register_blueprint(resource_routes.bp)
    app.register_blueprint(agent_routes.bp)

    @app.after_request
    def add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Idempotency-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return resp

    @app.route("/api/<path:_any>", methods=["OPTIONS"])
    def cors_preflight(_any):
        return ("", 204)

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "state_version": db.current_state_version()})

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "NOT_FOUND"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "INTERNAL_ERROR", "message": str(e)}), 500

    with app.app_context():
        if not os.path.exists(db.DB_PATH):
            from . import seed_gsi
            seed_gsi.run_default_seed(reset=True)
        else:
            db.init_db(reset=False)

    return app


app = create_app()

if __name__ == "__main__":
    # The Werkzeug debugger allows remote code execution, so it is opt-in and
    # the server binds to localhost unless DISASTEROPS_HOST says otherwise.
    app.run(host=os.environ.get("DISASTEROPS_HOST", "127.0.0.1"), port=5001,
            debug=os.environ.get("DISASTEROPS_DEBUG") == "1", use_reloader=False)
