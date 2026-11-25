"""
Cron job model — SQLAlchemy Core table definitions.

Stores scheduled recurring tasks and their execution history.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, MetaData
from sqlalchemy import select, func

metadata = MetaData()

cron_jobs = Table(
    "cron_jobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(256), nullable=False),
    Column("description", Text),
    Column("schedule", String(64), nullable=False),               # cron expression
    Column("schedule_human", String(128)),                        # human-readable
    Column("status", String(32), default="active", index=True),   # active | paused | failed | completed
    Column("assigned_to", String(128), nullable=True),
    Column("last_run", DateTime, nullable=True),
    Column("last_run_status", String(32), nullable=True),         # success | failed | timeout
    Column("next_run", DateTime, nullable=True),
    Column("success_count", Integer, default=0),
    Column("failure_count", Integer, default=0),
    Column("created_by", String(128)),
    Column("created_at", DateTime, server_default=func.now()),
)

cron_history = Table(
    "cron_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cron_id", Integer, nullable=False, index=True),
    Column("status", String(32), nullable=False),                 # success | failed | timeout
    Column("duration_ms", Integer, nullable=True),
    Column("output", Text),
    Column("error", Text),
    Column("triggered_by", String(32), default="schedule"),       # schedule | manual
    Column("created_at", DateTime, server_default=func.now()),
)


def get_cron_job_by_id(conn, job_id: int) -> dict | None:
    row = conn.execute(select(cron_jobs).where(cron_jobs.c.id == job_id)).one_or_none()
    return row._asdict() if row else None


def list_cron_jobs(conn) -> list[dict]:
    rows = conn.execute(
        select(cron_jobs).order_by(cron_jobs.c.name)
    ).fetchall()
    return [r._asdict() for r in rows]


def get_cron_history(conn, cron_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        select(cron_history)
        .where(cron_history.c.cron_id == cron_id)
        .order_by(cron_history.c.created_at.desc())
        .limit(limit)
    ).fetchall()
    return [r._asdict() for r in rows]
