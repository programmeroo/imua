"""Task model — SQLAlchemy Core table definition.

Tracks task queue items with priorities, assignments, context handoff,
retry logic, and SLA monitoring.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, Boolean, MetaData
from sqlalchemy import select, func, and_

metadata = MetaData()

tasks = Table(
    "tasks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("type", String(64), nullable=False, index=True),
    Column("title", String(256)),
    Column("status", String(32), default="pending", index=True),
    Column("priority", Integer, default=3),                        # 1 (urgent) to 5 (low)
    Column("assigned_to", String(128), nullable=True, index=True),
    Column("created_by", String(128)),
    Column("params", Text),                                        # JSON string
    Column("context", Text),                                       # JSON string
    Column("result", Text),
    Column("tags", Text),                                          # JSON list
    Column("retry_count", Integer, default=0),
    Column("max_retries", Integer, default=3),
    Column("next_retry_at", DateTime, nullable=True),
    Column("escalated", Boolean, default=False),
    Column("created_at", DateTime, server_default=func.now()),
    Column("assigned_at", DateTime, nullable=True),
    Column("completed_at", DateTime, nullable=True),
)


def get_task_by_id(conn, task_id: int) -> dict | None:
    row = conn.execute(select(tasks).where(tasks.c.id == task_id)).one_or_none()
    return dict(row._mapping) if row else None


def list_tasks(conn, status: str | None = None, limit: int = 100) -> list[dict]:
    stmt = select(tasks).order_by(tasks.c.priority.asc(), tasks.c.created_at.desc())
    if status:
        stmt = stmt.where(tasks.c.status == status)
    rows = conn.execute(stmt.limit(limit)).fetchall()
    return [dict(r._mapping) for r in rows]


def list_unassigned(conn, limit: int = 50) -> list[dict]:
    """Highest-priority unassigned tasks (for claim endpoint)."""
    stmt = (select(tasks)
            .where(and_(tasks.c.status == "pending", tasks.c.assigned_to.is_(None)))
            .order_by(tasks.c.priority.asc(), tasks.c.created_at.asc())
            .limit(limit))
    return [dict(r._mapping) for r in conn.execute(stmt).fetchall()]


def count_by_status(conn, agent: str | None = None) -> dict[str, int]:
    """Count of tasks per status, optionally filtered by assigned agent."""
    counts = {}
    for s in ("pending", "in_progress", "completed", "failed", "cancelled"):
        stmt = select(func.count()).select_from(tasks).where(tasks.c.status == s)
        if agent:
            stmt = stmt.where(tasks.c.assigned_to == agent)
        counts[s] = conn.execute(stmt).scalar() or 0
    return counts
