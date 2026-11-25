"""
Audit log API (task 5.6): GET /api/audit — admin only (signed-in session or operator key).

    ?limit=100 (max 500)   ?before=<id> for the next page   ?actor=<name>
"""

from flask import Blueprint, current_app, jsonify, request

from app.services import audit
from app.services.auth import require_admin

audit_bp = Blueprint("audit", __name__)


@audit_bp.get("/api/audit")
@require_admin
def list_audit():
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
        before = int(request.args["before"]) if request.args.get("before") else None
    except ValueError:
        return jsonify({"error": "validation_error", "message": "'limit' and 'before' must be integers"}), 400
    with current_app.config["DB_ENGINE"].connect() as conn:
        rows = audit.recent(conn, limit=limit, before_id=before, actor=request.args.get("actor"))
    return jsonify({"entries": rows, "count": len(rows)})
