"""Task Queue — priority dispatch, auto-routing, retry with backoff, SLA monitoring.

Depends on the `agents` table (for capabilities) and the `tasks` table.
"""

import json
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_
from app.models.task import tasks, get_task_by_id


# ── Retry schedule ──────────────────────────────────────────────

def _backoff_seconds(attempt: int) -> int:
    """Exponential backoff: 30s, 60s, 120s, 240s, 480s..."""
    return 30 * (2 ** attempt)


# ── Auto-routing ───────────────────────────────────────────────

def _agent_capabilities(conn) -> list[dict]:
    """Return all agents with their capabilities parsed from JSON."""
    from app.models.agent import agents
    rows = conn.execute(
        select(agents.c.name, agents.c.capabilities)
        .where(agents.c.status == "online")
    ).fetchall()
    result = []
    for r in rows:
        caps = json.loads(r.capabilities) if r.capabilities else []
        result.append({"name": r.name, "capabilities": caps})
    return result


def _in_progress_count(conn, agent_name: str) -> int:
    return conn.execute(
        select(func.count()).select_from(tasks)
        .where(and_(tasks.c.assigned_to == agent_name, tasks.c.status == "in_progress"))
    ).scalar() or 0


def _find_best_agent(conn, task_type: str) -> str | None:
    """Find the agent with the lightest load whose capabilities match task_type."""
    best = None
    best_load = 999
    for agent in _agent_capabilities(conn):
        if any(task_type.lower() in cap.lower() for cap in agent["capabilities"]):
            load = _in_progress_count(conn, agent["name"])
            if load < best_load:
                best = agent["name"]
                best_load = load
    return best


def dispatch_task(conn, task_id: int) -> dict:
    """Auto-route a task to the best-matching agent. Returns updated task."""
    task = get_task_by_id(conn, task_id)
    if not task:
        return {"error": "not_found"}
    if task["status"] != "pending":
        return {"error": "wrong_status", "status": task["status"]}

    agent = _find_best_agent(conn, task["type"])
    if agent:
        conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(
                assigned_to=agent, assigned_at=datetime.utcnow()
            )
        )
        conn.commit()
    task = get_task_by_id(conn, task_id)
    return {"task": task, "assigned_to": agent}


def claim_next_task(conn, agent_name: str, capabilities: list[str]) -> dict:
    """Agent claims the highest-priority pending task it can handle."""
    from app.models.task import list_unassigned
    unassigned = list_unassigned(conn)
    for task in unassigned:
        if any(task["type"].lower() in cap.lower() or cap.lower() in task["type"].lower()
               for cap in capabilities):
            conn.execute(
                tasks.update().where(tasks.c.id == task["id"]).values(
                    status="in_progress",
                    assigned_to=agent_name,
                    assigned_at=datetime.utcnow(),
                )
            )
            conn.commit()
            return {"task": get_task_by_id(conn, task["id"])}
    return {"task": None}


# ── Lifecycle ──────────────────────────────────────────────────

def complete_task(conn, task_id: int, result: str | None = None) -> dict:
    """Mark a task as completed with optional result."""
    updates = {"status": "completed", "completed_at": datetime.utcnow()}
    if result is not None:
        updates["result"] = result
    conn.execute(tasks.update().where(tasks.c.id == task_id).values(**updates))
    conn.commit()
    return {"task": get_task_by_id(conn, task_id)}


def fail_task(conn, task_id: int, error: str | None = None) -> dict:
    """Mark a task as failed. Re-queues with backoff if retries remain."""
    task = get_task_by_id(conn, task_id)
    if not task:
        return {"error": "not_found"}

    retry_count = (task.get("retry_count") or 0) + 1
    max_retries = task.get("max_retries") or 3

    if retry_count < max_retries:
        delay = _backoff_seconds(retry_count)
        conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(
                status="pending",
                assigned_to=None,
                assigned_at=None,
                retry_count=retry_count,
                next_retry_at=datetime.utcnow() + timedelta(seconds=delay),
                result=error,
            )
        )
    else:
        conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(
                status="failed",
                retry_count=retry_count,
                escalated=True,
                result=error or "max retries exceeded",
            )
        )
    conn.commit()
    return {"task": get_task_by_id(conn, task_id), "retry_count": retry_count,
            "maxed_out": retry_count >= max_retries}


def escalate_overdue_tasks(conn, threshold_minutes: int = 30) -> list[dict]:
    """Flag tasks that have been pending/in_progress past threshold as escalated."""
    cutoff = datetime.utcnow() - timedelta(minutes=threshold_minutes)
    overdue = conn.execute(
        select(tasks).where(
            and_(
                tasks.c.status.in_(["pending", "in_progress"]),
                tasks.c.created_at < cutoff,
                tasks.c.escalated == False,
            )
        )
    ).fetchall()
    flagged = []
    for row in overdue:
        t = dict(row._mapping)
        conn.execute(
            tasks.update().where(tasks.c.id == t["id"]).values(escalated=True)
        )
        flagged.append(t)
    if flagged:
        conn.commit()
    return [{"id": t["id"], "type": t["type"], "title": t["title"],
             "status": t["status"], "assigned_to": t["assigned_to"],
             "created_at": t["created_at"].isoformat() if t.get("created_at") else None}
            for t in flagged]
