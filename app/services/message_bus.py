"""
Message Bus — pub/sub + direct messaging between agents.

Handles sending, receiving, and WebSocket push delivery.
Supports single, broadcast ("all"), comma-separated, and role-based addressing.
"""

from datetime import datetime
from sqlalchemy import select
from app.models.message import messages


def send_message(conn, sender: str, to: str, msg_type: str = "chat",
                 body: str = "", payload: str | None = None,
                 topic: str | None = None) -> dict | list[dict]:
    """Send a message to one or more recipients.

    Addressing modes:
      - "agent_name"       → single recipient
      - "all"              → broadcast to all agents
      - "svy,slk,akm"     → comma-separated list
      - "role:developer"   → role-based (all agents with that role)
    """
    from app.models.agent import agents

    # Resolve recipients
    recipients = _resolve_recipients(conn, to)

    result_messages = []
    for recipient in recipients:
        stmt = messages.insert().values(
            msg_type="broadcast" if to == "all" else "direct",
            sender=sender,
            recipient=recipient,
            topic=topic,
            body=body,
            payload=payload,
            status="pending",
            created_at=datetime.utcnow(),
        )
        result = conn.execute(stmt)
        msg_id = result.inserted_primary_key[0]

        # Fetch back the full row
        row = conn.execute(
            select(messages).where(messages.c.id == msg_id)
        ).one()
        msg_data = row._asdict()
        result_messages.append(msg_data)

        # Push to WebSocket if the recipient is connected
        _push_via_ws(recipient, msg_data)

    if not result_messages:
        return {"status": "no_recipients", "sender": sender,
                "msg_type": "broadcast" if to == "all" else "direct",
                "body": body}
    return result_messages[0] if len(result_messages) == 1 else result_messages


def get_messages(conn, agent_name: str, since: str | None = None,
                 limit: int = 50, status: str | None = None,
                 unread: bool = False) -> list[dict]:
    """Fetch messages for an agent, optionally filtered by timestamp and status."""
    from app.models.message import get_messages_for_agent

    msgs = get_messages_for_agent(conn, agent_name, limit, status=status, unread=unread)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            msgs = [m for m in msgs if m["created_at"] and
                    m["created_at"] > since_dt.replace(tzinfo=None)]
        except (ValueError, TypeError):
            pass

    return msgs


def mark_read(conn, ids: list[int], agent_name: str | None) -> dict:
    """Set status='read' on the given message ids. Idempotent.

    agent_name scopes the update to that agent's own rows (recipient match), so a
    broadcast caller only ever touches its own copy. None means operator: any row.
    Returns {"marked": [ids updated or already read], "skipped": [ids not found
    or not the caller's]} — the two aren't distinguished, so ids can't be probed.
    """
    ids = list(dict.fromkeys(ids))
    query = select(messages.c.id).where(messages.c.id.in_(ids))
    if agent_name is not None:
        query = query.where(messages.c.recipient == agent_name)
    owned = {row[0] for row in conn.execute(query)}
    if owned:
        conn.execute(messages.update().where(messages.c.id.in_(owned)).values(status="read"))
    return {"marked": sorted(owned), "skipped": [i for i in ids if i not in owned]}


def _scoped(stmt, agent_name: str | None):
    """Restrict a statement to agent_name's own rows; None (operator) means all rows."""
    return stmt if agent_name is None else stmt.where(messages.c.recipient == agent_name)


def get_message(conn, msg_id: int, agent_name: str | None) -> dict | None:
    """One message, or None if missing / not the caller's. A recipient reading
    its own message marks it read; the operator viewing it changes nothing."""
    row = conn.execute(_scoped(select(messages).where(messages.c.id == msg_id), agent_name)).one_or_none()
    if row is None:
        return None
    msg = row._asdict()
    if agent_name is not None and msg["status"] != "read":
        conn.execute(messages.update().where(messages.c.id == msg_id).values(status="read"))
        msg["status"] = "read"
    return msg


def set_status(conn, msg_id: int, status: str, agent_name: str | None) -> bool:
    """Set one message's status. False if missing / not the caller's."""
    stmt = _scoped(messages.update().where(messages.c.id == msg_id), agent_name).values(status=status)
    return conn.execute(stmt).rowcount > 0


def delete_messages(conn, agent_name: str | None, msg_id: int | None = None,
                    before: datetime | None = None) -> int:
    """Delete one message by id, or every message created before `before`.
    Scoped to the caller's own rows unless operator. Returns rows deleted."""
    stmt = messages.delete()
    if msg_id is not None:
        stmt = stmt.where(messages.c.id == msg_id)
    if before is not None:
        stmt = stmt.where(messages.c.created_at < before)
    return conn.execute(_scoped(stmt, agent_name)).rowcount


def _resolve_recipients(conn, to: str) -> list[str]:
    """Resolve an addressing string into a list of agent names."""
    to = to.strip()

    if to == "all":
        from app.models.agent import list_agents
        agents = list_agents(conn)
        return [a["name"] for a in agents]

    if to.startswith("role:"):
        role_name = to[5:]
        from app.models.agent import agents as agent_table
        rows = conn.execute(
            select(agent_table.c.name).where(agent_table.c.role == role_name)
        ).fetchall()
        return [r[0] for r in rows]

    # Comma-separated or single
    return [name.strip() for name in to.split(",")]


def _push_via_ws(agent_name: str, msg_data: dict) -> None:
    """Push a message to a connected agent via WebSocket (if connected)."""
    from app.server import socketio

    room = f"agent_{agent_name}"
    socketio.emit("message.new", msg_data, to=room)
