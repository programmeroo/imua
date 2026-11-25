"""
Secrets model — SQLAlchemy Core table definition.

Stores encrypted secret values, descriptions, and access scope.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, MetaData
from sqlalchemy import select, func

metadata = MetaData()

secrets = Table(
    "secrets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(256), unique=True, nullable=False, index=True),
    Column("encrypted_value", Text, nullable=False),
    Column("description", Text),
    Column("access_scope", Text),     # JSON list of agent names
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
    Column("last_access", DateTime),
)


def get_secret_by_name(conn, name: str) -> dict | None:
    """Fetch a secret row by name. Returns row dict or None."""
    row = conn.execute(
        select(secrets).where(secrets.c.name == name)
    ).one_or_none()
    return row._asdict() if row else None


def list_secret_names(conn) -> list[str]:
    """Return all secret names (no values)."""
    rows = conn.execute(
        select(secrets.c.name).order_by(secrets.c.name)
    ).fetchall()
    return [r[0] for r in rows]
