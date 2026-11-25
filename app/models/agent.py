"""
Agent model — SQLAlchemy Core table definition.

Tracks agent identity, status, capabilities, and last heartbeat.
"""

from datetime import datetime, timedelta

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, Float, MetaData
from sqlalchemy import select, func

metadata = MetaData()

agents = Table(
    "agents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(128), unique=True, nullable=False, index=True),
    Column("display_name", String(256)),
    Column("token_hash", String(128), nullable=False),
    Column("status", String(32), default="offline"),
    Column("role", String(64), default="worker"),
    Column("capabilities", Text),             # JSON string
    Column("host", String(256)),
    Column("port", Integer),
    Column("last_heartbeat", DateTime),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
)


def get_agent_by_name(conn, name: str) -> dict | None:
    """Fetch an agent by name. Returns row dict or None."""
    row = conn.execute(
        select(agents).where(agents.c.name == name)
    ).one_or_none()
    return row._asdict() if row else None


def list_agents(conn, status: str | None = None) -> list[dict]:
    """List all agents, optionally filtered by status."""
    stmt = select(agents)
    if status:
        stmt = stmt.where(agents.c.status == status)
    rows = conn.execute(stmt).fetchall()
    return [r._asdict() for r in rows]


def is_online(last_heartbeat, created_at, timeout_seconds: int) -> bool:
    """Whether an agent counts as online, based on heartbeat recency.

    Falls back to created_at when no heartbeat has landed yet, so a
    freshly registered agent is online during its initial grace period.
    """
    last_contact = last_heartbeat or created_at
    if not last_contact:
        return False
    return datetime.utcnow() - last_contact < timedelta(seconds=timeout_seconds)
