"""
Cron job API endpoints — list, manage, and trigger scheduled jobs.

GET  /api/cron                — list all cron jobs
GET  /api/cron/<id>           — get job details + recent history
PATCH /api/cron/<id>          — update job (pause/resume, edit schedule)
POST /api/cron/<id>/run       — trigger immediate run
DELETE /api/cron/<id>         — remove a cron job
GET  /api/cron/<id>/history   — paginated execution history
GET  /cron                    — render cron list page
GET  /cron/<id>               — render cron detail page
"""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, current_app, g
from app.models.cron import cron_jobs, cron_history, get_cron_job_by_id, list_cron_jobs, get_cron_history
from app.routes.projects import error_response
from app.services import projects as project_svc
from app.services.auth import require_agent_token

cron_bp = Blueprint("cron", __name__)


@cron_bp.route("/api/cron", methods=["GET"])
def list_jobs():
    """List all cron jobs with status."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        rows = project_svc.with_project(conn, "cron", list_cron_jobs(conn))
        return jsonify({"cron_jobs": rows, "count": len(rows)}), 200
    finally:
        conn.close()


@cron_bp.route("/api/cron", methods=["POST"])
@require_agent_token
def create_job():
    """Create a new cron job."""
    data = request.get_json(silent=True) or {}

    # Validate required fields
    errors = []
    if not data.get("name"):
        errors.append("'name' is required")
    if not data.get("schedule"):
        errors.append("'schedule' (cron expression) is required")
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:  # check the project before inserting, so a bad one leaves no job behind
            project = project_svc.project_for_new_item(conn, data.get("project"))
        except project_svc.ProjectError as exc:
            return error_response(exc)
        now = datetime.utcnow()
        result = conn.execute(cron_jobs.insert().values(
            name=data["name"],
            description=data.get("description", ""),
            schedule=data["schedule"],
            schedule_human=data.get("schedule_human", ""),
            status=data.get("status", "active"),
            assigned_to=data.get("assigned_to"),
            created_by=data.get("created_by", "api"),
            created_at=now,
        ))
        conn.commit()
        job_id = result.inserted_primary_key[0]
        if project:
            project_svc.put_item(conn, project, "cron", job_id, added_by=g.agent_name or g.get("admin_username"))
            conn.commit()
        job = project_svc.with_project(conn, "cron", get_cron_job_by_id(conn, job_id))
        return jsonify(job), 201
    finally:
        conn.close()


@cron_bp.route("/api/cron/<int:job_id>", methods=["GET"])
def get_job(job_id):
    """Get cron job details + recent execution history."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        job = get_cron_job_by_id(conn, job_id)
        if not job:
            return jsonify({"error": "not_found", "message": f"Cron job {job_id} not found"}), 404
        history = get_cron_history(conn, job_id, limit=20)
        job["history"] = history
        project_svc.with_project(conn, "cron", job)
        return jsonify(job), 200
    finally:
        conn.close()


@cron_bp.route("/api/cron/<int:job_id>", methods=["PATCH"])
@require_agent_token
def update_job(job_id):
    """Update cron job (pause/resume, edit schedule)."""
    data = request.get_json(silent=True) or {}
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        job = get_cron_job_by_id(conn, job_id)
        if not job:
            return jsonify({"error": "not_found", "message": f"Cron job {job_id} not found"}), 404

        updates = {}
        for field in ("status", "schedule", "schedule_human", "description", "name", "assigned_to"):
            if field in data:
                updates[field] = data[field]

        if updates:
            conn.execute(cron_jobs.update().where(cron_jobs.c.id == job_id).values(**updates))
            conn.commit()

        updated = project_svc.with_project(conn, "cron", get_cron_job_by_id(conn, job_id))
        return jsonify(updated), 200
    finally:
        conn.close()


@cron_bp.route("/api/cron/<int:job_id>/run", methods=["POST"])
@require_agent_token
def trigger_job(job_id):
    """Trigger an immediate run of a cron job."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        job = get_cron_job_by_id(conn, job_id)
        if not job:
            return jsonify({"error": "not_found", "message": f"Cron job {job_id} not found"}), 404

        now = datetime.utcnow()
        conn.execute(cron_jobs.update().where(cron_jobs.c.id == job_id).values(
            last_run=now, last_run_status="running"
        ))
        conn.execute(cron_history.insert().values(
            cron_id=job_id,
            status="running",
            triggered_by="manual",
            created_at=now,
        ))
        conn.commit()

        return jsonify({"status": "triggered", "job_id": job_id}), 200
    finally:
        conn.close()


@cron_bp.route("/api/cron/<int:job_id>", methods=["DELETE"])
@require_agent_token
def delete_job(job_id):
    """Remove a cron job."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        job = get_cron_job_by_id(conn, job_id)
        if not job:
            return jsonify({"error": "not_found", "message": f"Cron job {job_id} not found"}), 404
        conn.execute(cron_jobs.delete().where(cron_jobs.c.id == job_id))
        conn.execute(cron_history.delete().where(cron_history.c.cron_id == job_id))
        project_svc.unlink_item(conn, "cron", job_id)  # plan D5: no orphan project links
        conn.commit()
        return jsonify({"status": "deleted", "job_id": job_id}), 200
    finally:
        conn.close()


@cron_bp.route("/api/cron/<int:job_id>/history", methods=["GET"])
def job_history(job_id):
    """Get paginated execution history for a cron job."""
    limit = request.args.get("limit", 50, type=int)
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        history = get_cron_history(conn, job_id, limit=limit)
        return jsonify({"history": history, "count": len(history)}), 200
    finally:
        conn.close()


@cron_bp.route("/cron")
def cron_list_page():
    """Render the cron job list page."""
    return render_template("cron.html", title="Imua · Cron Jobs")


@cron_bp.route("/cron/<int:job_id>")
def cron_detail_page(job_id):
    """Render the cron job detail page."""
    return render_template("cron_detail.html", title="Imua · Cron Job", job_id=job_id)
