"""
Issues service — create-or-update, resolve, list, acknowledge, suppress.

This is the single mutation surface for the `issues` table. Routes and
other services call into here; no caller should touch `app.models.issue`
directly for writes.

Schema reference: docs/imua_flask_specification_v3.md §4.

Lifecycle (per spec §2.1):
    open  --acknowledge-->  acknowledged  --resolve-->  resolved
    open  --suppress-->     suppressed
    open  --(auto-resolve by service)-->  resolved
"""

from datetime import datetime
from sqlalchemy import update

from app.models.issue import (
    issues,
    fingerprint_for,
    find_active_by_fingerprint,
    get_by_id,
    list_issues as _list_issues_model,
    count_by_source_severity as _count_model,
)

# Valid enums (defensive — also enforced at the column level by SQLite types).
VALID_SEVERITIES = ("info", "warning", "error", "critical")
VALID_STATUSES = ("open", "acknowledged", "resolved", "suppressed")


def _now() -> datetime:
    return datetime.utcnow()


def _validate(source: str, type_: str, severity: str) -> str | None:
    """Return an error string if inputs are invalid, else None."""
    if not source or not isinstance(source, str):
        return "'source' is required"
    if not type_ or not isinstance(type_, str):
        return "'type' is required"
    if severity not in VALID_SEVERITIES:
        return (f"'severity' must be one of {VALID_SEVERITIES}, "
                f"got {severity!r}")
    return None


def report_issue(conn, source: str, type_: str, subject: str | None,
                 severity: str, detail: str = "") -> dict:
    """Create or update an issue by fingerprint.

    If an open/acknowledged issue with the same fingerprint exists, increment
    its count and refresh last_seen + detail. Otherwise insert a new row.

    Does NOT commit — the caller (route or service) owns the transaction
    boundary. Matches the convention in secrets_vault.py.

    Returns a dict with the issue row + a "created" flag (bool).
    """
    err = _validate(source, type_, severity)
    if err:
        raise ValueError(err)

    existing = find_active_by_fingerprint(conn, source, type_, subject)
    if existing:
        new_count = existing["count"] + 1
        conn.execute(
            update(issues)
            .where(issues.c.id == existing["id"])
            .values(count=new_count, last_seen=_now(), detail=detail or existing["detail"])
        )
        row = get_by_id(conn, existing["id"])
        return {**row, "created": False}
    else:
        fp = fingerprint_for(source, type_, subject)
        result = conn.execute(
            issues.insert().values(
                fingerprint=fp,
                source=source,
                type=type_,
                subject=subject,
                severity=severity,
                status="open",
                count=1,
                detail=detail,
                first_seen=_now(),
                last_seen=_now(),
            )
        )
        issue_id = result.inserted_primary_key[0]
        row = get_by_id(conn, issue_id)
        return {**row, "created": True}


def resolve_issue(conn, source: str, type_: str, subject: str | None,
                  resolution: str = "") -> bool:
    """Resolve the matching open/acknowledged issue. No-op if none exists.

    Does NOT commit — caller owns transaction boundary.
    """
    existing = find_active_by_fingerprint(conn, source, type_, subject)
    if not existing:
        return False
    conn.execute(
        update(issues)
        .where(issues.c.id == existing["id"])
        .values(status="resolved", resolved_at=_now(), resolution=resolution or None)
    )
    return True


def list_issues(conn, status: str | None = None, source: str | None = None,
                severity: str | None = None, limit: int = 100) -> list[dict]:
    """List issues, newest last_seen first. Optional filters.

    Default behavior (no `status` filter): returns open + acknowledged issues
    only. Resolved and suppressed rows are hidden unless the caller passes
    `status='all'` or an explicit status. Rationale: the dashboard shows
    "currently active problems" by default; history is queryable explicitly.
    """
    if status is not None and status not in VALID_STATUSES and status != "all":
        raise ValueError(f"'status' must be one of {VALID_STATUSES} or 'all', got {status!r}")
    if severity is not None and severity not in VALID_SEVERITIES:
        raise ValueError(f"'severity' must be one of {VALID_SEVERITIES}, got {severity!r}")

    if status == "all":
        # Explicit "give me everything" — bypass active-only default.
        return _list_issues_model(conn, status=None, source=source,
                                  severity=severity, limit=limit)

    if status is None:
        # No filter — default to active only (open + acknowledged).
        from sqlalchemy import select as _select
        from app.models.issue import issues as _issues, ACTIVE_STATUSES
        stmt = (_select(_issues)
                .where(_issues.c.status.in_(ACTIVE_STATUSES))
                .order_by(_issues.c.last_seen.desc())
                .limit(limit))
        if source:
            stmt = stmt.where(_issues.c.source == source)
        if severity:
            stmt = stmt.where(_issues.c.severity == severity)
        return [dict(r._mapping) for r in conn.execute(stmt).fetchall()]

    return _list_issues_model(conn, status=status, source=source,
                              severity=severity, limit=limit)


def acknowledge_issue(conn, issue_id: int, agent_or_operator: str) -> bool:
    """Mark an issue as acknowledged by an agent or operator.

    Allowed from "open" only — acknowledging an already-acknowledged issue
    is a no-op. Acknowledging a resolved/suppressed issue raises ValueError.
    """
    if not agent_or_operator:
        raise ValueError("'agent_or_operator' is required")
    row = get_by_id(conn, issue_id)
    if not row:
        return False
    if row["status"] == "acknowledged":
        return True  # idempotent
    if row["status"] != "open":
        raise ValueError(
            f"Cannot acknowledge issue in status {row['status']!r}"
        )
    conn.execute(
        update(issues)
        .where(issues.c.id == issue_id)
        .values(status="acknowledged",
                acknowledged_at=_now(),
                acknowledged_by=agent_or_operator)
    )
    return True


def suppress_issue(conn, issue_id: int) -> bool:
    """Hide an issue from dashboard counts. Keeps history queryable."""
    row = get_by_id(conn, issue_id)
    if not row:
        return False
    if row["status"] == "suppressed":
        return True  # idempotent
    if row["status"] in ("resolved",):
        raise ValueError(
            f"Cannot suppress resolved issue (use acknowledge instead)"
        )
    conn.execute(
        update(issues)
        .where(issues.c.id == issue_id)
        .values(status="suppressed")
    )
    return True


def summary(conn) -> dict[str, dict[str, int]]:
    """Counts of active (open+acknowledged) issues by source × severity.

    Returned shape: {"vault": {"warning": 3, "error": 1}, ...}
    Used by the dashboard summary tiles.
    """
    return _count_model(conn)