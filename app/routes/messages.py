"""
Message API endpoints — send, receive, list messages, and page view.

POST /api/messages            — send a message
GET  /api/messages            — get messages for an agent (?status=, ?unread=true)
POST /api/messages/<id>/read  — mark one message read (recipient or operator)
POST /api/messages/read       — bulk mark read, body {"ids": [...]}
GET    /api/messages/<id>     — read one message; the recipient reading it marks it read
PATCH  /api/messages/<id>     — set status, body {"status": "pending|delivered|read"}
DELETE /api/messages/<id>     — delete one message (admin only)
DELETE /api/messages?before=  — delete messages created before an ISO date/datetime (admin only)
GET  /messages                — render messages dashboard page
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app, render_template, g
from app.models.message import MESSAGE_STATUSES
from app.services.message_bus import (send_message, get_messages, mark_read, get_message,
                                      set_status, delete_messages)
from app.services.auth import require_agent_token, require_admin

messages_bp = Blueprint("messages", __name__)

MAX_BULK_IDS = 500


@messages_bp.route("/api/messages", methods=["POST"])
@require_agent_token
def send():
    """Send a message to one or more agents. Sender identity comes from the
    authenticated token, not the request body."""
    if g.is_operator:
        return jsonify({"error": "forbidden",
                        "message": "Operator key cannot send messages as an agent"}), 403

    data = request.get_json(silent=True) or {}
    errors = _validate_send(data)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = send_message(
            conn=conn,
            sender=g.agent_name,
            to=data["to"],
            msg_type=data.get("type", "chat"),
            body=data.get("body", ""),
            payload=(
                __import__("json").dumps(data.get("payload"))
                if data.get("payload") else None
            ),
            topic=data.get("topic"),
        )
        conn.commit()
        return jsonify(result), 201
    finally:
        conn.close()


@messages_bp.route("/api/messages", methods=["GET"])
def list_messages():
    """Get messages for an agent, optionally filtered by timestamp."""
    agent_name = request.args.get("to") or request.args.get("agent")
    if not agent_name:
        return jsonify({"error": "missing_param",
                        "message": "Provide 'to' or 'agent' query param"}), 400

    since = request.args.get("since")
    limit = request.args.get("limit", 50, type=int)
    status = request.args.get("status") or None
    if status and status not in MESSAGE_STATUSES:
        return jsonify({"error": "validation_error",
                        "details": [f"'status' must be one of {', '.join(MESSAGE_STATUSES)}"]}), 422
    unread = request.args.get("unread", "").lower() in ("1", "true", "yes")

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        msgs = get_messages(conn, agent_name, since=since, limit=limit,
                            status=status, unread=unread)
        return jsonify({"messages": msgs, "count": len(msgs)}), 200
    finally:
        conn.close()


@messages_bp.route("/api/messages/<int:msg_id>/read", methods=["POST"])
@require_agent_token
def mark_one_read(msg_id):
    """Mark one message read. Only its recipient (or the operator) may; anyone
    else gets 404, the same as a nonexistent id."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = mark_read(conn, [msg_id], None if g.is_operator else g.agent_name)
        conn.commit()
    finally:
        conn.close()
    if not result["marked"]:
        return jsonify({"error": "not_found", "message": f"No message {msg_id} for this caller"}), 404
    return jsonify({"id": msg_id, "status": "read"}), 200


@messages_bp.route("/api/messages/read", methods=["POST"])
@require_agent_token
def mark_many_read():
    """Bulk mark read: body {"ids": [int, ...]} (1..MAX_BULK_IDS). Ids that don't
    exist or aren't the caller's are returned under "skipped", not an error."""
    ids = (request.get_json(silent=True) or {}).get("ids")
    valid = (isinstance(ids, list) and 0 < len(ids) <= MAX_BULK_IDS
             and all(type(i) is int for i in ids))
    if not valid:
        return jsonify({"error": "validation_error",
                        "details": [f"'ids' must be a list of 1-{MAX_BULK_IDS} integers"]}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = mark_read(conn, ids, None if g.is_operator else g.agent_name)
        conn.commit()
        return jsonify(result), 200
    finally:
        conn.close()


def _caller():
    """Row scope for the authenticated caller: its own name, or None for the operator."""
    return None if g.is_operator else g.agent_name


def _not_found(msg_id):
    return jsonify({"error": "not_found", "message": f"No message {msg_id} for this caller"}), 404


def _db_call(fn):
    """Run fn(conn) in a committed transaction and return its result."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = fn(conn)
        conn.commit()
        return result
    finally:
        conn.close()


@messages_bp.route("/api/messages/<int:msg_id>", methods=["GET"])
@require_agent_token
def get_one(msg_id):
    """Read one message. Recipient only (or operator); a recipient reading it
    marks it read, the operator viewing it does not."""
    msg = _db_call(lambda conn: get_message(conn, msg_id, _caller()))
    return (jsonify(msg), 200) if msg else _not_found(msg_id)


@messages_bp.route("/api/messages/<int:msg_id>", methods=["PATCH"])
@require_agent_token
def update_one(msg_id):
    """Set a message's status: body {"status": "pending" | "delivered" | "read"}."""
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in MESSAGE_STATUSES:
        return jsonify({"error": "validation_error",
                        "details": [f"'status' must be one of {', '.join(MESSAGE_STATUSES)}"]}), 422
    if not _db_call(lambda conn: set_status(conn, msg_id, status, _caller())):
        return _not_found(msg_id)
    return jsonify({"id": msg_id, "status": status}), 200


@messages_bp.route("/api/messages/<int:msg_id>", methods=["DELETE"])
@require_admin
def delete_one(msg_id):
    """Delete one message. Admin only."""
    if not _db_call(lambda conn: delete_messages(conn, None, msg_id=msg_id)):
        return _not_found(msg_id)
    return jsonify({"deleted": 1}), 200


@messages_bp.route("/api/messages", methods=["DELETE"])
@require_admin
def delete_before():
    """Prune all messages created before ?before=<ISO date or datetime, UTC>. Admin only."""
    try:
        before = datetime.fromisoformat(request.args.get("before", "").replace("Z", "+00:00"))
    except ValueError:
        return jsonify({"error": "validation_error",
                        "details": ["'before' must be an ISO date or datetime, e.g. 2026-10-01"]}), 422
    if before.tzinfo:  # created_at is stored as naive UTC
        before = before.astimezone(timezone.utc).replace(tzinfo=None)
    count = _db_call(lambda conn: delete_messages(conn, None, before=before))
    return jsonify({"deleted": count}), 200


@messages_bp.route("/messages")
def messages_page():
    """Render the messages dashboard page."""
    return render_template("messages.html", title="Imua · Messages")


def _validate_send(data: dict) -> list[str]:
    """Validate send message payload. Returns list of error messages."""
    errors = []
    if not data.get("to"):
        errors.append("'to' is required")
    return errors
