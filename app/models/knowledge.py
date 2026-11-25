"""
Knowledge Base model — SQLAlchemy Core table definition.

Tracks metadata for entries in the vector knowledge store.
Vector embeddings live in ChromaDB (data/chroma/), referenced by `chroma_id`.
This table holds the source-of-truth metadata for each entry so we can
list/delete/update without re-querying the vector store.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, MetaData
from sqlalchemy import select, func

metadata = MetaData()

knowledge_entries = Table(
    "knowledge_entries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("chroma_id", String(64), nullable=False, unique=True, index=True),
    Column("source", String(32), nullable=False),  # manual|agent_log|document|mempalace
    Column("agent", String(128)),                    # creator agent name
    Column("title", String(256)),
    Column("body", Text, nullable=False),
    Column("tags", String(512)),                     # JSON list of tags
    Column("created_at", DateTime, server_default=func.now()),
)


def get_entry_by_id(conn, entry_id: int) -> dict | None:
    row = conn.execute(
        select(knowledge_entries).where(knowledge_entries.c.id == entry_id)
    ).one_or_none()
    return row._asdict() if row else None


def get_entry_by_chroma_id(conn, chroma_id: str) -> dict | None:
    row = conn.execute(
        select(knowledge_entries).where(knowledge_entries.c.chroma_id == chroma_id)
    ).one_or_none()
    return row._asdict() if row else None


def list_entries(conn, source: str | None = None, agent: str | None = None,
                 limit: int = 100) -> list[dict]:
    stmt = select(knowledge_entries).order_by(knowledge_entries.c.created_at.desc())
    if source:
        stmt = stmt.where(knowledge_entries.c.source == source)
    if agent:
        stmt = stmt.where(knowledge_entries.c.agent == agent)
    stmt = stmt.limit(limit)
    rows = conn.execute(stmt).fetchall()
    return [r._asdict() for r in rows]


def count_entries(conn) -> int:
    row = conn.execute(select(func.count()).select_from(knowledge_entries)).one()
    return row[0]