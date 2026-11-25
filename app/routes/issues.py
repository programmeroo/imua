"""
Issues API endpoints — list, summary, acknowledge, suppress, resolve, report.

Reference: docs/imua_flask_specification_v3.md §5 (HTTP API table).

Auth model (per task 2.3 / 2.3a pattern):
- GET endpoints (list, summary, single-issue detail): open
- POST mutating endpoints (acknowledge, suppress, resolve, report):
  require a valid bearer token (agent OR operator key)

Note: 'acknowledge' and 'suppress' return 200 with bool, not the full
row. Caller can re-fetch via GET /api/issues/<id> if they want details.
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, render_template, g

from app.services.auth import require_agent_token
from app.services import issues as svc

issues_bp = Blueprint("issues", __name__)


# ---------- list ----------

@issues_bp.route("/api/issues", methods=["GET"])
def list_issues():
    """List issues. Default: open + acknowledged (active only).

    Query params:
      status   — 'open' | 'acknowledged' | 'resolved' | 'suppressed' | 'all'
      source   — filter by source (vault, agents, git, ...)
      severity — 'info' | 'warning' | 'error' | 'critical'
      limit    — max rows (default 100)
    """
    status = request.args.get("status")
    source = request.args.get("source")
    severity = request.args.get("severity")
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"error": "validation_error",
                        "message": "'limit' must be an integer"}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        rows = svc.list_issues(conn, status=status, source=source,
                               severity=severity, limit=limit)
        return jsonify({"issues": rows, "count": len(rows)}), 200
    except ValueError as e:
        return jsonify({"error": "validation_error", "message": str(e)}), 422
    finally:
        conn.close()


# ---------- summary ----------

@issues_bp.route("/api/issues/summary", methods=["GET"])
def summary():
    """Counts of active (open+acknowledged) issues by source × severity.

    Used by the dashboard tiles. Response shape:
      {"summary": {"vault": {"warning": 3, "error": 1}, ...}}
    """
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        return jsonify({"summary": svc.summary(conn)}), 200
    finally:
        conn.close()


# ---------- single ----------

@issues_bp.route("/api/issues/<int:issue_id>", methods=["GET"])
def get_issue(issue_id):
    """Single issue detail."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        row = svc.get_by_id(conn, issue_id)
        if not row:
            return jsonify({"error": "not_found",
                            "message": f"Issue {issue_id} not found"}), 404
        return jsonify(row), 200
    finally:
        conn.close()


# ---------- acknowledge ----------

@issues_bp.route("/api/issues/<int:issue_id>/acknowledge",
                 methods=["POST"])
@require_agent_token
def acknowledge(issue_id):
    """Mark an issue as acknowledged. Caller identity is the actor."""
    actor = g.agent_name or g.get("admin_username") or ("operator" if g.is_operator else "unknown")
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:
            ok = svc.acknowledge_issue(conn, issue_id, actor)
        except ValueError as e:
            return jsonify({"error": "invalid_state", "message": str(e)}), 409
        conn.commit()
        if not ok:
            return jsonify({"error": "not_found",
                            "message": f"Issue {issue_id} not found"}), 404
        row = svc.get_by_id(conn, issue_id)
        return jsonify({"acknowledged": True, "issue": row}), 200
    finally:
        conn.close()


# ---------- suppress ----------

@issues_bp.route("/api/issues/<int:issue_id>/suppress", methods=["POST"])
@require_agent_token
def suppress(issue_id):
    """Hide an issue from dashboard counts."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:
            ok = svc.suppress_issue(conn, issue_id)
        except ValueError as e:
            return jsonify({"error": "invalid_state", "message": str(e)}), 409
        conn.commit()
        if not ok:
            return jsonify({"error": "not_found",
                            "message": f"Issue {issue_id} not found"}), 404
        row = svc.get_by_id(conn, issue_id)
        return jsonify({"suppressed": True, "issue": row}), 200
    finally:
        conn.close()


# ---------- resolve (force, not via fingerprint) ----------

@issues_bp.route("/api/issues/<int:issue_id>/resolve", methods=["POST"])
@require_agent_token
def resolve(issue_id):
    """Force-resolve an issue by id. Mostly for operators; services should
    use the fingerprint-based resolve_issue() internally."""
    resolution = ""
    if request.is_json:
        body = request.get_json(silent=True) or {}
        resolution = body.get("resolution", "")
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        row = svc.get_by_id(conn, issue_id)
        if not row:
            return jsonify({"error": "not_found",
                            "message": f"Issue {issue_id} not found"}), 404
        # Direct UPDATE since fingerprint-resolve requires source/type/subject.
        from sqlalchemy import update
        from app.models.issue import issues
        conn.execute(
            update(issues)
            .where(issues.c.id == issue_id)
            .values(status="resolved",
                    resolved_at=datetime.utcnow(),
                    resolution=resolution or None)
        )
        conn.commit()
        row = svc.get_by_id(conn, issue_id)
        return jsonify({"resolved": True, "issue": row}), 200
    finally:
        conn.close()


# ---------- report (agent self-report) ----------

@issues_bp.route("/api/issues", methods=["POST"])
@require_agent_token
def report():
    """Agent self-reports an operational issue. The agent_name is taken
    from the authenticated caller, NOT the request body."""
    if g.is_operator:
        return jsonify({"error": "forbidden",
                        "message": "Operator key cannot self-report issues"}), 403
    data = request.get_json(silent=True) or {}
    errors = _validate_report(data)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = svc.report_issue(
            conn,
            source=data["source"],
            type_=data["type"],
            subject=data.get("subject"),
            severity=data["severity"],
            detail=data.get("detail", ""),
        )
        conn.commit()
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": "validation_error", "message": str(e)}), 422
    finally:
        conn.close()


def _validate_report(data: dict) -> list[str]:
    errors = []
    if not data.get("source"):
        errors.append("'source' is required")
    if not data.get("type"):
        errors.append("'type' is required")
    if not data.get("severity"):
        errors.append("'severity' is required")
    return errors


# ---------- page route ----------

@issues_bp.route("/issues", methods=["GET"])
def issues_page():
    """Issues dashboard page. Server-rendered shell; data comes from /api/issues via JS."""
    return render_template("issues.html")