"""
Agent chat route  —  the HTTP entry point for spec section 173's Agent
Orchestration Layer. Not in the spec's original API map (§164), since
that map predates this being built out, but it's the natural sibling
of that list.
"""
from flask import Blueprint, request, jsonify, g
from ..auth import require_role
from ..agent.orchestrator import run_agent

bp = Blueprint("agent", __name__, url_prefix="/api/agent")


@bp.route("/chat", methods=["POST"])
@require_role("COORDINATOR", "ADMIN")
def chat():
    body = request.get_json(force=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "VALIDATION_ERROR", "message": "message is required"}), 422

    # conversation continuity within a session: the client passes back
    # the `messages` array from the previous response for follow-ups.
    prior_messages = body.get("conversation")
    if prior_messages is not None and (not isinstance(prior_messages, list) or len(prior_messages) > 60):
        return jsonify({"error": "VALIDATION_ERROR", "message": "conversation must be a list of at most 60 messages"}), 422

    result = run_agent(message, conversation=prior_messages)
    if result.get("error") == "LLM_NOT_CONFIGURED":
        return jsonify({"error": result["error"], "message": result["message"]}), 503
    if result.get("error") == "LLM_REQUEST_FAILED":
        return jsonify({"error": result["error"], "message": result["message"]}), 502

    return jsonify({
        "trace": result["trace"],
        "final_message": result.get("final_message"),
        "conversation": result["messages"],
        "actor_id": g.current_user["user_id"],
    })
