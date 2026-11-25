"""
Agent authentication — bearer token verification and operator key bypass.

Tokens are issued once at registration (see app/routes/agents.py) and
stored hashed. This module is the single place that verifies a bearer
token against that hash, plus checks the config-level operator key.
"""

import hashlib
import hmac
from functools import wraps

from flask import current_app, g, jsonify, request
from sqlalchemy import select

from app.models.agent import agents


def hash_token(token: str) -> str:
    """sha256 hex digest of a raw token — the form stored as token_hash."""
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(conn) -> tuple[str | None, bool]:
    """Identify the caller from the Authorization header.

    Returns (agent_name, is_operator):
      - (None, False) — no/invalid/unknown token
      - (None, True)  — token matches the configured operator key
      - (name, False) — token matches a registered agent
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, False
    token = auth_header[len("Bearer "):].strip()
    if not token:
        return None, False

    operator_key = current_app.config.get("OPERATOR_KEY", "")
    if (operator_key and current_app.config.get("OPERATOR_KEY_ENABLED", True)
            and hmac.compare_digest(token, operator_key)):
        return None, True

    token_hash = hash_token(token)
    row = conn.execute(
        select(agents.c.name).where(agents.c.token_hash == token_hash)
    ).one_or_none()
    return (row.name, False) if row else (None, False)


def require_bearer_token(f):
    """Route decorator — 401s unless a valid agent token or the operator key is
    presented. A signed-in browser session is NOT enough: used where the response
    must never reach a browser (reading a vault secret's value, admin plan D12).

    On success sets flask.g.agent_name (None for the operator) and
    flask.g.is_operator.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        conn = current_app.config["DB_ENGINE"].connect()
        try:
            agent_name, is_operator = authenticate(conn)
        finally:
            conn.close()

        if not agent_name and not is_operator:
            return jsonify({"error": "unauthorized",
                            "message": "Valid bearer token required"}), 401

        g.agent_name = agent_name
        g.is_operator = is_operator
        return f(*args, **kwargs)
    return wrapper


def require_agent_token(f):
    """Route decorator — a valid agent token, the operator key, or (task 5.8) a
    signed-in admin session, so the dashboard can act without tokens in the
    browser. A session acts as the operator (g.agent_name None, g.is_operator
    True, g.admin_username set); CSRF is checked for every session write
    (app/services/csrf.py).
    """
    bearer = require_bearer_token(f)

    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.headers.get("Authorization", "").startswith("Bearer "):
            return bearer(*args, **kwargs)
        from app.services.admin_session import current_admin  # avoid import cycle
        admin = current_admin()
        if not admin:
            return jsonify({"error": "unauthorized",
                            "message": "Valid bearer token required"}), 401
        g.admin_username, g.agent_name, g.is_operator = admin["username"], None, True
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """Route decorator for admin-only actions. Accepts a signed-in admin session
    (task 5.5; CSRF is checked for every session write in app/services/csrf.py)
    or the operator key, unless auth.operator_key_enabled is off. Agent tokens
    get 403: agents can't be trusted to delete.

    Sets flask.g.admin_username (the admin's name, or "operator") and
    g.agent_name = None / g.is_operator = True, as require_agent_token would.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        from app.services.admin_session import current_admin  # avoid import cycle
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            admin = current_admin()
            if not admin:
                return jsonify({"error": "unauthorized",
                                "message": "Sign in as an admin, or send the operator key"}), 401
            g.admin_username, g.agent_name, g.is_operator = admin["username"], None, True
            return f(*args, **kwargs)
        conn = current_app.config["DB_ENGINE"].connect()
        try:
            agent_name, is_operator = authenticate(conn)
        finally:
            conn.close()
        if not agent_name and not is_operator:
            return jsonify({"error": "unauthorized", "message": "Valid bearer token required"}), 401
        if not is_operator:
            return jsonify({"error": "forbidden", "message": "Admin only"}), 403
        g.admin_username, g.agent_name, g.is_operator = "operator", None, True
        return f(*args, **kwargs)
    return wrapper
