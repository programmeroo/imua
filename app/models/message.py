"""
Message model — SQLAlchemy Core table definition.

Stores structured messages between agents. Supports both
direct messages and broadcast messages.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, MetaData
from sqlalchemy import select, func

metadata = MetaData()

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("msg_type", String(32), default="direct"),   # direct | broadcast
    Column("sender", String(128), nullable=False, index=True),
    Column("recipient", String(128), nullable=True, index=True),
    Column("topic", String(128)),
    Column("body", Text),
    Column("payload", Text),                              # JSON string
    Column("status", String(32), default="pending"),      # pending | delivered | read
    Column("created_at", DateTime, server_default=func.now()),
)


MESSAGE_STATUSES = ("pending", "delivered", "read")


def get_messages_for_agent(conn, agent_name: str, limit: int = 50,
                           status: str | None = None, unread: bool = False) -> list[dict]:
    """Fetch an agent's messages, newest first.

    Broadcasts are stored as one row per recipient, so filtering on recipient alone
    returns the agent's own copy — matching msg_type == "broadcast" as well would
    leak every other agent's copy too. Filters run in SQL, before the limit.
    """
    stmt = select(messages).where(messages.c.recipient == agent_name)
    if status:
        stmt = stmt.where(messages.c.status == status)
    if unread:
        stmt = stmt.where(messages.c.status != "read")
    stmt = (
        stmt.order_by(messages.c.created_at.desc(), messages.c.id.desc())
        .limit(limit)
    )
    rows = conn.execute(stmt).fetchall()
    return [r._asdict() for r in rows]
