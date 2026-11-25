"""
Document model — SQLAlchemy Core table definition.

Tracks uploaded document metadata. File bytes live on disk under
data/docs/; this table tracks where, by whom, and whether archived.
"""

from sqlalchemy import Table, Column, Integer, String, Boolean, DateTime, MetaData
from sqlalchemy import select, func

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("filename", String(256), nullable=False),
    Column("content_type", String(128)),
    Column("size", Integer, default=0),
    Column("storage_path", String(512), nullable=False),
    Column("uploaded_by", String(128)),
    Column("archived", Boolean, default=False, index=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("archived_at", DateTime, nullable=True),
)


def get_document_by_id(conn, doc_id: int) -> dict | None:
    row = conn.execute(select(documents).where(documents.c.id == doc_id)).one_or_none()
    return row._asdict() if row else None


def list_documents(conn, archived: bool | None = None) -> list[dict]:
    stmt = select(documents).order_by(documents.c.created_at.desc())
    if archived is not None:
        stmt = stmt.where(documents.c.archived == archived)
    rows = conn.execute(stmt).fetchall()
    return [r._asdict() for r in rows]
