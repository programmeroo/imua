"""
Knowledge Base API — vector search, add, delete, and stats endpoints.

POST   /api/knowledge             — add an entry (requires bearer token)
GET    /api/knowledge?q=...        — semantic search (open, dashboard-style)
GET    /api/knowledge/<id>         — get single entry by SQLite id (open)
DELETE /api/knowledge/<id>         — delete entry (requires bearer token + creator or operator)
GET    /api/knowledge/stats        — collection stats (open)
"""

import json
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, render_template, request

from app.models.knowledge import (
    knowledge_entries,
    get_entry_by_id,
    list_entries,
)
from app.routes.projects import error_response
from app.services.auth import require_agent_token
from app.services import knowledge_base as kb
from app.services import projects as project_svc

knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.route("/knowledge")
def knowledge_page():
    """Render the knowledge base dashboard page."""
    return render_template("knowledge.html", title="Imua · Knowledge")


@knowledge_bp.route("/api/knowledge", methods=["POST"])
@require_agent_token
def add_entry():
    """Add a knowledge entry. Body and source required; agent = g.agent_name."""
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "validation_error",
                        "details": ["'body' is required"]}), 422

    source = (data.get("source") or "manual").strip()
    title = (data.get("title") or "").strip() or None
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        return jsonify({"error": "validation_error",
                        "details": ["'tags' must be a list"]}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        try:  # check the project before storing anything
            project = project_svc.project_for_new_item(conn, data.get("project"))
        except project_svc.ProjectError as exc:
            return error_response(exc)
        chroma_id = kb.add_entry(body=body, source=source, agent=g.agent_name, title=title,
                                 tags=tags, project=project)
        conn.execute(knowledge_entries.insert().values(
            chroma_id=chroma_id,
            source=source,
            agent=g.agent_name,
            title=title or "",
            body=body,
            tags=json.dumps(tags),
            created_at=datetime.utcnow(),
        ))
        entry_id = conn.execute(knowledge_entries.select()
                                .where(knowledge_entries.c.chroma_id == chroma_id)).one().id
        if project:
            project_svc.put_item(conn, project, "knowledge", entry_id,
                                 added_by=g.agent_name or g.get("admin_username"))
        conn.commit()
        return jsonify(project_svc.with_project(conn, "knowledge", get_entry_by_id(conn, entry_id))), 201
    finally:
        conn.close()


@knowledge_bp.route("/api/knowledge", methods=["GET"])
def search():
    """Semantic search. ?q= required, optional ?n= (default 10)."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "validation_error",
                        "details": ["'q' query parameter is required"]}), 422
    try:
        n = max(1, min(int(request.args.get("n", 10)), 50))
    except ValueError:
        return jsonify({"error": "validation_error",
                        "details": ["'n' must be an integer"]}), 422

    project = request.args.get("project")
    if project:
        conn = current_app.config["DB_ENGINE"].connect()
        try:
            project = project_svc.get_project(conn, project)["slug"]
        except project_svc.ProjectError as exc:
            return error_response(exc)
        finally:
            conn.close()
    result = kb.search(query, n_results=n, where={"project": project} if project else None)

    ids = result.get("ids", [[]])[0] if result.get("ids") else []
    docs = result.get("documents", [[]])[0] if result.get("documents") else []
    metas = result.get("metadatas", [[]])[0] if result.get("metadatas") else []
    dists = result.get("distances", [[]])[0] if result.get("distances") else []

    # Join with SQLite metadata for source/agent/timestamps
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        hits = []
        for chroma_id, doc, meta, dist in zip(ids, docs, metas, dists):
            row = conn.execute(
                knowledge_entries.select()
                .where(knowledge_entries.c.chroma_id == chroma_id)
            ).one_or_none()
            entry = row._asdict() if row else {}
            hits.append({
                "id": entry.get("id"),
                "chroma_id": chroma_id,
                "body": doc,
                "title": (meta or {}).get("title") or entry.get("title"),
                "source": (meta or {}).get("source") or entry.get("source"),
                "agent": (meta or {}).get("agent") or entry.get("agent"),
                "distance": dist,
                "created_at": entry["created_at"].isoformat() if entry.get("created_at") else None,
            })
        project_svc.with_project(conn, "knowledge", hits)
        return jsonify({"query": query, "project": project, "hits": hits, "count": len(hits)}), 200
    finally:
        conn.close()


@knowledge_bp.route("/api/knowledge/<int:entry_id>", methods=["GET"])
def get_entry(entry_id):
    """Get one entry by SQLite id."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        row = get_entry_by_id(conn, entry_id)
        if not row:
            return jsonify({"error": "not_found",
                            "message": f"Entry {entry_id} not found"}), 404
        return jsonify(project_svc.with_project(conn, "knowledge", row)), 200
    finally:
        conn.close()


@knowledge_bp.route("/api/knowledge/<int:entry_id>", methods=["PATCH"])
@require_agent_token
def update_entry(entry_id):
    """Edit title, body and/or tags (task 5.18). Same rule as delete: the creator or an
    admin. The search index is updated first; if that fails nothing is changed."""
    data = request.get_json(silent=True) or {}
    unknown = set(data) - {"title", "body", "tags"}
    errors = [f"Can't change: {', '.join(sorted(unknown))}"] if unknown else []
    body = data.get("body")
    if body is not None:
        body = body.strip() if isinstance(body, str) else ""
        if not body:
            errors.append("'body' can't be empty")
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        errors.append("'title' must be text")
    tags = data.get("tags")
    if tags is not None and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        errors.append("'tags' must be a list of text")
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 422

    conn = current_app.config["DB_ENGINE"].connect()
    try:
        row = get_entry_by_id(conn, entry_id)
        if not row:
            return jsonify({"error": "not_found", "message": f"Entry {entry_id} not found"}), 404
        if not g.is_operator and row.get("agent") != g.agent_name:
            return jsonify({"error": "forbidden",
                            "message": "Only the creator or an admin may edit this entry"}), 403
        title = title.strip() if isinstance(title, str) else None
        tags = [t.strip() for t in tags if t.strip()] if tags is not None else None
        try:
            kb.update_entry(row["chroma_id"], body=body, title=title, tags=tags)
        except Exception as exc:
            current_app.logger.warning("knowledge re-index failed for %s: %s", row["chroma_id"], exc)
            return jsonify({"error": "index_error",
                            "message": "Could not update the search index; nothing was changed"}), 502
        changes = (("title", title), ("body", body), ("tags", json.dumps(tags) if tags is not None else None))
        values = {k: v for k, v in changes if v is not None}
        if values:
            conn.execute(knowledge_entries.update().where(knowledge_entries.c.id == entry_id).values(**values))
            conn.commit()
        return jsonify(project_svc.with_project(conn, "knowledge", get_entry_by_id(conn, entry_id))), 200
    finally:
        conn.close()


@knowledge_bp.route("/api/knowledge/<int:entry_id>", methods=["DELETE"])
@require_agent_token
def delete_entry(entry_id):
    """Delete an entry. Only the creator or the operator may delete."""
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        row = get_entry_by_id(conn, entry_id)
        if not row:
            return jsonify({"error": "not_found",
                            "message": f"Entry {entry_id} not found"}), 404

        if not g.is_operator and row.get("agent") != g.agent_name:
            return jsonify({"error": "forbidden",
                            "message": "Only the creator or operator may delete this entry"}), 403

        try:
            kb.delete_entry(row["chroma_id"])
        except Exception as exc:
            # Chroma-side error — log but proceed with SQL cleanup so the
            # SQLite row doesn't dangle. The next reindex can rebuild vectors.
            current_app.logger.warning("chroma delete failed for %s: %s",
                                       row["chroma_id"], exc)

        conn.execute(knowledge_entries.delete()
                     .where(knowledge_entries.c.id == entry_id))
        project_svc.unlink_item(conn, "knowledge", entry_id)  # plan D5
        conn.commit()
        return jsonify({"status": "deleted", "id": entry_id}), 200
    finally:
        conn.close()


@knowledge_bp.route("/api/knowledge/stats", methods=["GET"])
def stats():
    """Collection stats — entry count."""
    try:
        s = kb.get_stats()
    except RuntimeError as exc:
        return jsonify({"error": "not_initialized", "message": str(exc)}), 503
    return jsonify(s), 200


@knowledge_bp.route("/api/knowledge/recent", methods=["GET"])
def recent():
    """List the most recently added entries (no semantic search, dashboard 'recent' tab)."""
    try:
        limit = max(1, min(int(request.args.get("limit", 20)), 100))
    except ValueError:
        return jsonify({"error": "validation_error",
                        "details": ["'limit' must be an integer"]}), 422
    conn = current_app.config["DB_ENGINE"].connect()
    try:
        rows = project_svc.with_project(conn, "knowledge", list_entries(conn, limit=limit))
        return jsonify({"entries": rows, "count": len(rows)}), 200
    finally:
        conn.close()