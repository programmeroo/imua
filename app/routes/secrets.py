"""
Secrets Vault API endpoints — store, retrieve, and list secrets.

POST /api/vault/secrets           — store a new secret
GET  /api/vault/secrets/<name>    — retrieve a secret (scoped)
GET  /api/vault/secrets           — list available secret names
"""

from cryptography.fernet import InvalidToken
from flask import Blueprint, request, jsonify, current_app, g
from app.services.secrets_vault import store_secret, retrieve_secret, list_available_secrets
from app.models.secret import get_secret_by_name
from app.services.auth import require_agent_token, require_bearer_token

secrets_bp = Blueprint("secrets", __name__)


@secrets_bp.route("/api/vault/secrets", methods=["POST"])
@require_agent_token
def store():
    """Encrypt and store a new secret."""
    data = request.get_json(silent=True) or {}
    errors = _validate_store(data)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        # Check for duplicate name
        existing = get_secret_by_name(conn, data["name"])
        if existing:
            return jsonify({"error": "conflict",
                            "message": f"Secret '{data['name']}' already exists"}), 409

        result = store_secret(
            conn=conn,
            name=data["name"],
            value=data["value"],
            description=data.get("description", ""),
            access_scope=data.get("access_scope"),
            master_key=current_app.config.get("VAULT_KEY"),
        )
        conn.commit()
        return jsonify(result), 201
    finally:
        conn.close()


@secrets_bp.route("/api/vault/secrets/<name>", methods=["GET"])
@require_bearer_token  # never to a browser session: secret values stay out of the dashboard (D12)
def retrieve(name: str):
    """Retrieve a decrypted secret. Access is scoped to the calling agent's
    identity (from the token); the operator key bypasses access_scope entirely."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:
            result = retrieve_secret(
                conn=conn,
                name=name,
                agent_name=g.agent_name,
                master_key=current_app.config.get("VAULT_KEY"),
                bypass_scope=g.is_operator,
            )
        except InvalidToken:
            return jsonify({"error": "undecryptable",
                            "message": f"Secret '{name}' was encrypted with a different vault key "
                                       "(stored before the key was persisted). Store it again."}), 409
        conn.commit()

        if result is None:
            row = get_secret_by_name(conn, name)
            if row is None:
                return jsonify({"error": "not_found",
                                "message": f"Secret '{name}' not found"}), 404
            return jsonify({"error": "access_denied",
                            "message": f"Agent '{g.agent_name}' does not have access to '{name}'"}), 403

        return jsonify(result), 200
    finally:
        conn.close()


@secrets_bp.route("/api/vault/secrets", methods=["GET"])
def list_secrets():
    """List available secret names for the calling agent."""
    agent_name = request.args.get("agent") or request.headers.get("X-Agent-Name")

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = list_available_secrets(conn, agent_name=agent_name)
        return jsonify({"secrets": result, "count": len(result)}), 200
    finally:
        conn.close()


def _validate_store(data: dict) -> list[str]:
    """Validate store secret payload."""
    errors = []
    if not data.get("name"):
        errors.append("'name' is required")
    if not data.get("value"):
        errors.append("'value' is required")
    return errors
