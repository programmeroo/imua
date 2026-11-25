"""
Document Store API — upload, list, download, and archive documents.

POST   /api/documents              — upload a document (requires bearer token)
GET    /api/documents               — list documents (optional ?archived=true|false)
GET    /api/documents/<id>/download — download the original file
POST   /api/documents/<id>/archive  — mark a document archived (requires bearer token)
POST   /api/documents/<id>/unarchive — restore an archived document (requires bearer token)
"""

import os
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from app.models.document import documents, get_document_by_id, list_documents
from app.routes.projects import error_response
from app.services import projects as project_svc
from app.services.auth import require_agent_token

documents_bp = Blueprint("documents", __name__)


@documents_bp.route("/documents")
def documents_page():
    """Render the documents page — list, upload, and archive."""
    return render_template("documents.html", title="Imua · Documents")


def _storage_dir() -> str:
    path = current_app.config["DOCS_STORAGE_DIR"]
    os.makedirs(path, exist_ok=True)
    return path


@documents_bp.route("/api/documents", methods=["POST"])
@require_agent_token
def upload():
    """Upload a new document."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "validation_error", "details": ["'file' is required"]}), 422

    filename = secure_filename(file.filename)
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:  # check the project (a form field) before storing anything
            project = project_svc.project_for_new_item(conn, request.form.get("project"))
        except project_svc.ProjectError as exc:
            return error_response(exc)
        stmt = documents.insert().values(
            filename=filename,
            content_type=file.content_type,
            uploaded_by=request.form.get("uploaded_by", ""),
            storage_path="",
            archived=False,
            created_at=datetime.utcnow(),
        )
        result = conn.execute(stmt)
        doc_id = result.inserted_primary_key[0]

        storage_path = os.path.join(_storage_dir(), f"{doc_id}_{filename}")
        file.save(storage_path)
        size = os.path.getsize(storage_path)

        conn.execute(
            documents.update().where(documents.c.id == doc_id).values(
                storage_path=storage_path, size=size
            )
        )
        if project:
            project_svc.put_item(conn, project, "document", doc_id, added_by=g.agent_name or g.get("admin_username"))
        conn.commit()

        return jsonify(project_svc.with_project(conn, "document", get_document_by_id(conn, doc_id))), 201
    finally:
        conn.close()


@documents_bp.route("/api/documents", methods=["GET"])
def list_docs():
    """List documents, optionally filtered by archived status."""
    archived_param = request.args.get("archived")
    archived = None
    if archived_param is not None:
        archived = archived_param.lower() == "true"

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        rows = project_svc.with_project(conn, "document", list_documents(conn, archived=archived))
        return jsonify({"documents": rows, "count": len(rows)}), 200
    finally:
        conn.close()


@documents_bp.route("/api/documents/<int:doc_id>/download", methods=["GET"])
def download(doc_id):
    """Download the original file."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        doc = get_document_by_id(conn, doc_id)
        if not doc or not os.path.exists(doc["storage_path"]):
            return jsonify({"error": "not_found", "message": f"Document {doc_id} not found"}), 404
        directory, filename = os.path.split(doc["storage_path"])
        return send_from_directory(directory, filename, as_attachment=True, download_name=doc["filename"])
    finally:
        conn.close()


@documents_bp.route("/api/documents/<int:doc_id>/archive", methods=["POST"])
@require_agent_token
def archive(doc_id):
    """Mark a document archived."""
    return _set_archived(doc_id, True)


@documents_bp.route("/api/documents/<int:doc_id>/unarchive", methods=["POST"])
@require_agent_token
def unarchive(doc_id):
    """Restore an archived document."""
    return _set_archived(doc_id, False)


def _set_archived(doc_id: int, archived: bool):
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        doc = get_document_by_id(conn, doc_id)
        if not doc:
            return jsonify({"error": "not_found", "message": f"Document {doc_id} not found"}), 404

        conn.execute(
            documents.update().where(documents.c.id == doc_id).values(
                archived=archived,
                archived_at=datetime.utcnow() if archived else None,
            )
        )
        conn.commit()
        return jsonify(project_svc.with_project(conn, "document", get_document_by_id(conn, doc_id))), 200
    finally:
        conn.close()
