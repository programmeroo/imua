"""
Projects service — the only place that writes projects, members and project
contents (task 6.2, docs/imua_projects_plan_v1.md §4).

Rules:
- A slug is lowercase letters, digits and '-', 2-64 characters; made from the
  name when not given. Slugs never change.
- Each task / document / cron job / knowledge entry is in at most one project.
  Putting it in a project moves it there if it was elsewhere (D5).
- Archived projects accept no new items (D9).
- A project can't be deleted while it contains anything (D7). Members don't
  block deletion; they're removed with it.

Errors are raised as ProjectError subclasses so routes can map them to HTTP
codes. Like the other services, nothing here commits; the caller owns the
transaction.
"""

import re
from datetime import datetime

from sqlalchemy import func, select

from app.models.agent import agents
from app.models.cron import cron_jobs
from app.models.document import documents
from app.models.knowledge import knowledge_entries
from app.models.project import ITEM_TYPES, project_agents, project_items, projects
from app.models.task import tasks

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
STATUSES = ("active", "archived")
MAX_NAME = 128
_ITEM_TABLES = {"task": tasks, "document": documents, "cron": cron_jobs, "knowledge": knowledge_entries}


class ProjectError(ValueError):
    """Invalid input (HTTP 400)."""


class NotFound(ProjectError):
    """No such project, agent or item (HTTP 404)."""


class Conflict(ProjectError):
    """Slug taken, project archived, or project not empty (HTTP 409)."""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:64].strip("-")


def _clean_name(name) -> str:
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name or len(name) > MAX_NAME:
        raise ProjectError(f"'name' is required, at most {MAX_NAME} characters")
    return name


def _row(conn, slug: str) -> dict:
    row = conn.execute(select(projects).where(projects.c.slug == (slug or "").lower())).one_or_none()
    if not row:
        raise NotFound(f"No project '{slug}'")
    return row._asdict()


def _counts(conn, project_id: int) -> dict:
    rows = conn.execute(select(project_items.c.item_type, func.count())
                        .where(project_items.c.project_id == project_id)
                        .group_by(project_items.c.item_type)).all()
    found = dict(rows)
    return {t: found.get(t, 0) for t in ITEM_TYPES}


def _members(conn, project_id: int) -> list[str]:
    return list(conn.execute(select(project_agents.c.agent_name)
                             .where(project_agents.c.project_id == project_id)
                             .order_by(project_agents.c.agent_name)).scalars())


def _full(conn, row: dict) -> dict:
    return {**row, "agents": _members(conn, row["id"]), "counts": _counts(conn, row["id"])}


def create_project(conn, name, slug=None, description="", created_by=None) -> dict:
    name = _clean_name(name)
    slug = (slug or slugify(name)).strip().lower()
    if not SLUG_RE.match(slug):
        raise ProjectError("'slug' must be 2-64 characters: lowercase letters, digits and '-'")
    if conn.execute(select(projects.c.id).where(projects.c.slug == slug)).one_or_none():
        raise Conflict(f"Project '{slug}' already exists")
    now = datetime.utcnow()
    conn.execute(projects.insert().values(slug=slug, name=name, description=description or "",
                                          status="active", created_by=created_by,
                                          created_at=now, updated_at=now))
    return get_project(conn, slug)


def get_project(conn, slug: str) -> dict:
    return _full(conn, _row(conn, slug))


def list_projects(conn, status: str | None = None) -> list[dict]:
    q = select(projects).order_by(projects.c.name)
    if status:
        q = q.where(projects.c.status == status)
    return [_full(conn, r._asdict()) for r in conn.execute(q)]


def update_project(conn, slug: str, name=None, description=None, status=None) -> dict:
    row = _row(conn, slug)
    values = {}
    if name is not None:
        values["name"] = _clean_name(name)
    if description is not None:
        values["description"] = str(description)
    if status is not None:
        if status not in STATUSES:
            raise ProjectError(f"'status' must be one of {STATUSES}")
        values["status"] = status
    if values:
        values["updated_at"] = datetime.utcnow()
        conn.execute(projects.update().where(projects.c.id == row["id"]).values(**values))
    return get_project(conn, row["slug"])


def delete_project(conn, slug: str) -> None:
    row = _row(conn, slug)
    if any(_counts(conn, row["id"]).values()):
        raise Conflict(f"Project '{row['slug']}' still contains items; remove or move them first")
    conn.execute(project_agents.delete().where(project_agents.c.project_id == row["id"]))
    conn.execute(projects.delete().where(projects.c.id == row["id"]))


def add_agent(conn, slug: str, agent_name: str) -> dict:
    row = _row(conn, slug)
    if not conn.execute(select(agents.c.id).where(agents.c.name == agent_name)).one_or_none():
        raise NotFound(f"No agent '{agent_name}'")
    if agent_name not in _members(conn, row["id"]):
        conn.execute(project_agents.insert().values(project_id=row["id"], agent_name=agent_name,
                                                    added_at=datetime.utcnow()))
    return get_project(conn, row["slug"])


def remove_agent(conn, slug: str, agent_name: str) -> dict:
    row = _row(conn, slug)
    conn.execute(project_agents.delete().where(project_agents.c.project_id == row["id"],
                                               project_agents.c.agent_name == agent_name))
    return get_project(conn, row["slug"])


def _check_type(item_type: str) -> None:
    if item_type not in ITEM_TYPES:
        raise ProjectError(f"Item type must be one of {ITEM_TYPES}")


def put_item(conn, slug: str, item_type: str, item_id: int, added_by=None) -> None:
    """Put an item in this project, moving it if it is in another one."""
    _check_type(item_type)
    row = _row(conn, slug)
    if row["status"] != "active":
        raise Conflict(f"Project '{row['slug']}' is archived")
    table = _ITEM_TABLES[item_type]
    if not conn.execute(select(table.c.id).where(table.c.id == item_id)).one_or_none():
        raise NotFound(f"No {item_type} {item_id}")
    unlink_item(conn, item_type, item_id)
    conn.execute(project_items.insert().values(project_id=row["id"], item_type=item_type, item_id=item_id,
                                               added_by=added_by, added_at=datetime.utcnow()))
    _sync_search_index(conn, item_type, item_id, row["slug"])


def remove_item(conn, slug: str, item_type: str, item_id: int) -> None:
    """Take an item out of this project (the item itself is kept)."""
    _check_type(item_type)
    row = _row(conn, slug)
    result = conn.execute(project_items.delete().where(project_items.c.project_id == row["id"],
                                                       project_items.c.item_type == item_type,
                                                       project_items.c.item_id == item_id))
    if not result.rowcount:
        raise NotFound(f"{item_type} {item_id} is not in project '{row['slug']}'")
    _sync_search_index(conn, item_type, item_id, None)


def _sync_search_index(conn, item_type: str, item_id: int, slug: str | None) -> None:
    """Knowledge entries also carry their project in ChromaDB metadata (plan D6)."""
    if item_type != "knowledge":
        return
    chroma_id = conn.execute(select(knowledge_entries.c.chroma_id)
                             .where(knowledge_entries.c.id == item_id)).scalar()
    if chroma_id:
        from app.services import knowledge_base as kb  # chromadb is heavy; load only when needed
        kb.set_project(chroma_id, slug)


def unlink_item(conn, item_type: str, item_id: int) -> None:
    """Drop an item's project link, if any. Call this when the item is deleted (D5)."""
    conn.execute(project_items.delete().where(project_items.c.item_type == item_type,
                                              project_items.c.item_id == item_id))


def item_ids(conn, slug: str, item_type: str) -> list[int]:
    _check_type(item_type)
    row = _row(conn, slug)
    return list(conn.execute(select(project_items.c.item_id)
                             .where(project_items.c.project_id == row["id"],
                                    project_items.c.item_type == item_type)
                             .order_by(project_items.c.item_id)).scalars())


def list_items(conn, slug: str, item_type: str) -> list[dict]:
    """The rows of this project's items of one type, oldest first."""
    ids = item_ids(conn, slug, item_type)
    if not ids:
        return []
    table = _ITEM_TABLES[item_type]
    return [r._asdict() for r in conn.execute(select(table).where(table.c.id.in_(ids)).order_by(table.c.id))]


def project_for_new_item(conn, slug) -> str | None:
    """Check the `project` named when creating an item, before the item is inserted.
    None/"" means no project. Unknown → NotFound; archived → Conflict."""
    if slug in (None, ""):
        return None
    if not isinstance(slug, str):
        raise ProjectError("'project' must be a project slug")
    row = _row(conn, slug)
    if row["status"] != "active":
        raise Conflict(f"Project '{row['slug']}' is archived")
    return row["slug"]


def with_project(conn, item_type: str, rows):
    """Add "project" (slug or None) to one item dict or a list of them, in place."""
    items = [rows] if isinstance(rows, dict) else list(rows or [])
    found = projects_of(conn, item_type, [r["id"] for r in items if r and "id" in r])
    for r in items:
        if r:
            r["project"] = found.get(r.get("id"))
    return rows


def projects_of(conn, item_type: str, ids) -> dict[int, str]:
    """{item_id: project slug} for the given items; items in no project are left out."""
    ids = list(ids)
    if not ids:
        return {}
    rows = conn.execute(select(project_items.c.item_id, projects.c.slug)
                        .join(projects, projects.c.id == project_items.c.project_id)
                        .where(project_items.c.item_type == item_type, project_items.c.item_id.in_(ids)))
    return {r.item_id: r.slug for r in rows}
