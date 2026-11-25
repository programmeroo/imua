"""
Projects API (task 6.3, docs/imua_projects_plan_v1.md §5.1).

    GET    /api/projects                              list (?status=active|archived)
    POST   /api/projects                              create            [admin]
    GET    /api/projects/<slug>                       one project
    PATCH  /api/projects/<slug>                       name/description/status [admin]
    DELETE /api/projects/<slug>                       409 unless empty   [admin]
    GET    /api/projects/<slug>/items?type=<type>     the items themselves
    PUT    /api/projects/<slug>/items/<type>/<id>     put in (moves it)  [admin]
    DELETE /api/projects/<slug>/items/<type>/<id>     take out           [admin]
    PUT    /api/projects/<slug>/agents/<name>         add member         [admin]
    DELETE /api/projects/<slug>/agents/<name>         remove member      [admin]

Reads are open, like the rest of the hub's reads until admin plan task 5.21.
Not to be confused with app/routes/project.py (git site hosting, /api/project/).
"""

from functools import wraps

from flask import Blueprint, abort, current_app, g, jsonify, render_template, request

from app.services import projects as svc
from app.services.auth import require_admin

projects_bp = Blueprint("projects", __name__)

_STATUS = {svc.NotFound: (404, "not_found"), svc.Conflict: (409, "conflict"),
           svc.ProjectError: (400, "validation_error")}


def error_response(exc: svc.ProjectError):
    """HTTP response for a ProjectError (also used by the task and cron routes)."""
    status, code = next(v for k, v in _STATUS.items() if isinstance(exc, k))
    return jsonify({"error": code, "message": str(exc)}), status


def _db(f):
    """Run the view in one transaction, passing the connection; map ProjectError to HTTP."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            with current_app.config["DB_ENGINE"].begin() as conn:
                return f(conn, *args, **kwargs)
        except svc.ProjectError as exc:
            return error_response(exc)
    return wrapper


def _actor() -> str:
    return g.get("admin_username") or g.get("agent_name") or "operator"


@projects_bp.get("/projects")
def projects_page():
    """Projects list page (task 6.6). Needs a signed-in admin, like every page (5.7)."""
    return render_template("projects.html", title="Imua · Projects")


@projects_bp.get("/projects/<slug>")
def project_page(slug):
    """Project detail page with tabs (task 6.7). Unknown slug → 404."""
    try:
        with current_app.config["DB_ENGINE"].connect() as conn:
            project = svc.get_project(conn, slug)
    except svc.NotFound:
        abort(404)
    return render_template("project_detail.html", title=f"Imua · {project['name']}", project=project)


@projects_bp.get("/api/projects")
@_db
def list_projects(conn):
    rows = svc.list_projects(conn, status=request.args.get("status"))
    return jsonify({"projects": rows, "count": len(rows)})


@projects_bp.post("/api/projects")
@require_admin
@_db
def create_project(conn):
    data = request.get_json(silent=True) or {}
    project = svc.create_project(conn, data.get("name"), slug=data.get("slug"),
                                 description=data.get("description", ""), created_by=_actor())
    return jsonify(project), 201


@projects_bp.get("/api/projects/<slug>")
@_db
def get_project(conn, slug):
    return jsonify(svc.get_project(conn, slug))


@projects_bp.patch("/api/projects/<slug>")
@require_admin
@_db
def update_project(conn, slug):
    data = request.get_json(silent=True) or {}
    unknown = set(data) - {"name", "description", "status"}
    if unknown:
        raise svc.ProjectError(f"Can't change: {', '.join(sorted(unknown))}")
    return jsonify(svc.update_project(conn, slug, **data))


@projects_bp.delete("/api/projects/<slug>")
@require_admin
@_db
def delete_project(conn, slug):
    svc.delete_project(conn, slug)
    return jsonify({"status": "deleted", "slug": slug.lower()})


@projects_bp.get("/api/projects/<slug>/items")
@_db
def list_items(conn, slug):
    item_type = request.args.get("type", "")
    rows = svc.list_items(conn, slug, item_type)
    return jsonify({"type": item_type, "items": rows, "count": len(rows)})


@projects_bp.put("/api/projects/<slug>/items/<item_type>/<int:item_id>")
@require_admin
@_db
def put_item(conn, slug, item_type, item_id):
    svc.put_item(conn, slug, item_type, item_id, added_by=_actor())
    return jsonify(svc.get_project(conn, slug))


@projects_bp.delete("/api/projects/<slug>/items/<item_type>/<int:item_id>")
@require_admin
@_db
def remove_item(conn, slug, item_type, item_id):
    svc.remove_item(conn, slug, item_type, item_id)
    return jsonify(svc.get_project(conn, slug))


@projects_bp.put("/api/projects/<slug>/agents/<agent_name>")
@require_admin
@_db
def add_agent(conn, slug, agent_name):
    return jsonify(svc.add_agent(conn, slug, agent_name))


@projects_bp.delete("/api/projects/<slug>/agents/<agent_name>")
@require_admin
@_db
def remove_agent(conn, slug, agent_name):
    return jsonify(svc.remove_agent(conn, slug, agent_name))
