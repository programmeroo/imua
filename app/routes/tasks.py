"""
Task Queue API endpoints — create, claim, list, update tasks.

POST /api/tasks             — create a new task (auto-routed)
POST /api/tasks/claim       — agent claims the next task it can handle
GET  /api/tasks             — list tasks (optional status filter)
GET  /api/tasks/<id>        — get single task detail
PATCH /api/tasks/<id>       — update task status/assignment
POST /api/tasks/check-overdue — flag overdue tasks (operator/agent)
GET  /tasks                  — render tasks dashboard page
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, current_app, g
from sqlalchemy import func, select
from app.models.task import tasks, get_task_by_id, list_tasks, count_by_status
from app.services import projects as project_svc
from app.routes.projects import error_response
from app.services.auth import require_admin, require_agent_token
from app.services.task_queue import (
    dispatch_task, claim_next_task, complete_task, fail_task,
    escalate_overdue_tasks,
)

tasks_bp = Blueprint("tasks", __name__)

TASK_STATUSES = ("pending", "in_progress", "completed", "failed", "cancelled")
FINISHED = ("completed", "failed", "cancelled")  # the only statuses a prune may delete (plan D13)


@tasks_bp.route("/api/tasks", methods=["POST"])
@require_agent_token
def create_task():
    """Create a new task in the queue. Auto-routed to the best agent."""
    data = request.get_json(silent=True) or {}
    errors = _validate_create(data)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:  # check the project before inserting, so a bad one leaves no task behind
            project = project_svc.project_for_new_item(conn, data.get("project"))
        except project_svc.ProjectError as exc:
            return error_response(exc)
        stmt = tasks.insert().values(
            type=data["type"],
            title=data.get("title", ""),
            status="pending",
            priority=data.get("priority", 3),
            assigned_to=data.get("assigned_to"),
            created_by=g.agent_name or g.get("admin_username") or data.get("created_by", "operator"),
            params=__import__("json").dumps(data.get("params", {})),
            context=__import__("json").dumps(data.get("context", {})),
            tags=__import__("json").dumps(data.get("tags", [])),
            max_retries=data.get("max_retries", 3),
            created_at=datetime.utcnow(),
        )
        result = conn.execute(stmt)
        conn.commit()
        task_id = result.inserted_primary_key[0]
        if project:
            project_svc.put_item(conn, project, "task", task_id, added_by=g.agent_name or g.get("admin_username"))
            conn.commit()
        # Auto-route unless explicitly assigned
        if not data.get("assigned_to"):
            dispatch_task(conn, task_id)
        task = project_svc.with_project(conn, "task", get_task_by_id(conn, task_id))
        return jsonify(task), 201
    finally:
        conn.close()


@tasks_bp.route("/api/tasks/claim", methods=["POST"])
@require_agent_token
def claim():
    """Agent claims the next unassigned task matching its capabilities."""
    if g.is_operator:
        return jsonify({"error": "forbidden", "message": "Operator cannot claim tasks"}), 403
    data = request.get_json(silent=True) or {}
    caps = data.get("capabilities", [])
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        result = claim_next_task(conn, g.agent_name, caps)
        return jsonify(result), 200
    finally:
        conn.close()


@tasks_bp.route("/api/tasks", methods=["GET"])
def list_tasks_endpoint():
    """List tasks, optionally filtered by status."""
    status = request.args.get("status")
    agent = request.args.get("assigned_to")
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        rows = list_tasks(conn, status=status)
        if agent:
            rows = [r for r in rows if r.get("assigned_to") == agent]
        counts = count_by_status(conn, agent=agent)
        project_svc.with_project(conn, "task", rows)
        return jsonify({"tasks": rows, "count": len(rows), "counts": counts}), 200
    finally:
        conn.close()


@tasks_bp.route("/api/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        task = get_task_by_id(conn, task_id)
        if not task:
            return jsonify({"error": "not_found", "message": f"Task {task_id} not found"}), 404
        return jsonify(project_svc.with_project(conn, "task", task)), 200
    finally:
        conn.close()


@tasks_bp.route("/api/tasks/<int:task_id>", methods=["PATCH"])
@require_agent_token
def update_task(task_id):
    """Update task status, assignment, or result. Triggers retry on failure."""
    data = request.get_json(silent=True) or {}
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        task = get_task_by_id(conn, task_id)
        if not task:
            return jsonify({"error": "not_found", "message": f"Task {task_id} not found"}), 404

        status = data.get("status")
        if status and status not in TASK_STATUSES:
            return jsonify({"error": "validation_error",
                            "details": [f"'status' must be one of {', '.join(TASK_STATUSES)}"]}), 422
        updates = {}
        if status:
            updates["status"] = status
            if status == "in_progress" and not task.get("assigned_at"):
                updates["assigned_at"] = datetime.utcnow()
            if status in FINISHED:
                updates["completed_at"] = datetime.utcnow()
        if "assigned_to" in data:
            updates["assigned_to"] = data["assigned_to"]
            updates["assigned_at"] = datetime.utcnow()
        if "priority" in data:
            updates["priority"] = data["priority"]
        if "result" in data:
            updates["result"] = data["result"]

        if updates:
            conn.execute(tasks.update().where(tasks.c.id == task_id).values(**updates))
            conn.commit()

        # Trigger retry logic for manual failure
        if status == "failed":
            result = fail_task(conn, task_id, data.get("result"))
            return jsonify(result), 200

        updated = project_svc.with_project(conn, "task", get_task_by_id(conn, task_id))
        return jsonify(updated), 200
    finally:
        conn.close()


@tasks_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@require_admin
def delete_task(task_id):
    """Delete one task (any status). Admin only (task 5.16)."""
    with current_app.config["DB_ENGINE"].begin() as conn:
        if not conn.execute(tasks.delete().where(tasks.c.id == task_id)).rowcount:
            return jsonify({"error": "not_found", "message": f"Task {task_id} not found"}), 404
        project_svc.unlink_item(conn, "task", task_id)
    return jsonify({"deleted": 1}), 200


@tasks_bp.route("/api/tasks", methods=["DELETE"])
@require_admin
def prune_tasks():
    """Delete FINISHED tasks (completed, failed, cancelled) that finished before
    ?before=<ISO date>. Pending and in-progress tasks are never touched. Admin only."""
    try:
        before = datetime.fromisoformat(request.args.get("before", ""))
    except ValueError:
        return jsonify({"error": "validation_error",
                        "details": ["'before' must be an ISO date, e.g. 2026-10-01"]}), 422
    finished_at = func.coalesce(tasks.c.completed_at, tasks.c.created_at)
    with current_app.config["DB_ENGINE"].begin() as conn:
        ids = list(conn.execute(select(tasks.c.id).where(tasks.c.status.in_(FINISHED),
                                                         finished_at < before)).scalars())
        if ids:
            conn.execute(tasks.delete().where(tasks.c.id.in_(ids)))
            for task_id in ids:
                project_svc.unlink_item(conn, "task", task_id)
    return jsonify({"deleted": len(ids)}), 200


@tasks_bp.route("/api/tasks/check-overdue", methods=["POST"])
@require_agent_token
def check_overdue():
    """Flag tasks past the SLA threshold. Threshold in minutes (default 30)."""
    threshold = request.get_json(silent=True) or {}
    minutes = threshold.get("threshold_minutes", 30)
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        flagged = escalate_overdue_tasks(conn, threshold_minutes=minutes)
        return jsonify({"overdue": flagged, "count": len(flagged)}), 200
    finally:
        conn.close()


@tasks_bp.route("/tasks")
def tasks_page():
    """Render the tasks dashboard page."""
    return render_template("tasks.html", title="Imua · Tasks")


def _validate_create(data: dict) -> list[str]:
    errors = []
    if not data.get("type"):
        errors.append("'type' is required")
    return errors
