"""
Agent Registry API — register, heartbeat, list agents.

POST  /api/agents/register         — register a new agent, returns bearer token
PATCH /api/agents/<name>/heartbeat — update heartbeat, mark online
PATCH /api/agents/<name>/token     — rotate the agent's bearer token (self-service)
GET   /api/agents                  — list all agents
GET   /api/agents/<name>           — get single agent details
"""

import secrets
from flask import Blueprint, request, jsonify, current_app, g
from sqlalchemy import select
from app.models.agent import agents, is_online
from app.services.auth import hash_token, require_agent_token

agents_bp = Blueprint("agents", __name__)


@agents_bp.route("/api/agents/register", methods=["POST"])
def register():
    """Register a new agent. Returns bearer token (show once)."""
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "validation_error", "details": ["'name' is required"]}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        existing = conn.execute(
            select(agents).where(agents.c.name == name)
        ).one_or_none()
        if existing:
            return jsonify({"error": "conflict", "message": f"Agent '{name}' already exists"}), 409

        token = secrets.token_hex(32)
        token_hash = hash_token(token)

        conn.execute(agents.insert().values(
            name=name,
            display_name=data.get("display_name", name),
            token_hash=token_hash,
            status="online",
            role=data.get("role", "worker"),
            capabilities=__import__("json").dumps(data.get("capabilities", [])),
            host=data.get("host", ""),
            port=data.get("port", 0),
        ))
        conn.commit()

        return jsonify({
            "agent": name,
            "token": token,
            "message": "Save this token — it won't be shown again"
        }), 201
    finally:
        conn.close()


@agents_bp.route("/api/agents/<name>/heartbeat", methods=["PATCH"])
@require_agent_token
def heartbeat(name):
    """Update agent's last_heartbeat and mark online. Requires a token owned by <name>."""
    if g.is_operator or g.agent_name != name:
        return jsonify({"error": "forbidden",
                        "message": "Token does not authorize acting as this agent"}), 403

    from sqlalchemy import func
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = conn.execute(
            agents.update()
            .where(agents.c.name == name)
            .values(status="online", last_heartbeat=func.now())
        )
        conn.commit()
        if result.rowcount == 0:
            return jsonify({"error": "not_found", "message": f"Agent '{name}' not found"}), 404
        return jsonify({"status": "online", "agent": name}), 200
    finally:
        conn.close()


@agents_bp.route("/api/agents/<name>/token", methods=["PATCH"])
@require_agent_token
def rotate_token(name):
    """Self-service token rotation. Generates a new bearer token for <name>,
    replaces the stored hash, and returns the new token in the response —
    shown exactly once. The old token is invalidated on commit.

    Auth: requires the current bearer token (or operator key).
    - Agent token: caller must be the named agent (g.agent_name == name).
    - Operator key: allowed for any name (operator override).
    """
    if not g.is_operator and g.agent_name != name:
        return jsonify({"error": "forbidden",
                        "message": "Token does not authorize acting as this agent"}), 403

    new_token = secrets.token_hex(32)
    new_hash = hash_token(new_token)

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = conn.execute(
            agents.update()
            .where(agents.c.name == name)
            .values(token_hash=new_hash)
        )
        conn.commit()
        if result.rowcount == 0:
            return jsonify({"error": "not_found",
                            "message": f"Agent '{name}' not found"}), 404
        # Token returned ONCE in this response. The hash in the DB is the only
        # durable form. Treat the response value like a password: capture to
        # ~/.hermes/.env or to the Imua vault immediately, never log it.
        return jsonify({
            "agent": name,
            "token": new_token,
            "message": "New token. Save it now — it won't be shown again. The old token is invalidated.",
        }), 200
    finally:
        conn.close()


def _with_live_status(row: dict, timeout_seconds: int) -> dict:
    """Override the stored status with one computed from heartbeat recency."""
    row["status"] = "online" if is_online(row["last_heartbeat"], row["created_at"], timeout_seconds) else "offline"
    return row


@agents_bp.route("/api/agents", methods=["GET"])
def list_agents():
    """List all registered agents with their status."""
    timeout = current_app.config.get("HEARTBEAT_TIMEOUT", 120)
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        rows = conn.execute(
            select(
                agents.c.name, agents.c.display_name, agents.c.status,
                agents.c.role, agents.c.capabilities, agents.c.host,
                agents.c.last_heartbeat, agents.c.created_at
            ).order_by(agents.c.name)
        ).fetchall()
        return jsonify({
            "agents": [_with_live_status(dict(r._mapping), timeout) for r in rows],
            "count": len(rows)
        }), 200
    finally:
        conn.close()


@agents_bp.route("/api/agents/<name>", methods=["GET"])
def get_agent(name):
    """Get details for a single agent."""
    timeout = current_app.config.get("HEARTBEAT_TIMEOUT", 120)
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        row = conn.execute(
            select(
                agents.c.name, agents.c.display_name, agents.c.status,
                agents.c.role, agents.c.capabilities, agents.c.host,
                agents.c.port, agents.c.last_heartbeat, agents.c.created_at
            ).where(agents.c.name == name)
        ).one_or_none()
        if not row:
            return jsonify({"error": "not_found", "message": f"Agent '{name}' not found"}), 404
        return jsonify(_with_live_status(dict(row._mapping), timeout)), 200
    finally:
        conn.close()
