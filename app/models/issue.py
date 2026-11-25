"""
Issues model — SQLAlchemy Core table definition.

Stores operational issues raised by Imua's running services. Issues are
deduped by `fingerprint` (SHA-256 of source+type+subject) so a condition
that fires repeatedly increments `count` instead of creating new rows.

Lifecycle: open → acknowledged → resolved
            open → suppressed  (operator hides from dashboard counts)

Schema reference: docs/imua_flask_specification_v3.md §3.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, MetaData
from sqlalchemy import select, func, and_, or_

metadata = MetaData()

issues = Table(
    "issues",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fingerprint", String(64), nullable=False, index=True),
    Column("source", String(32), nullable=False, index=True),
    Column("type", String(64), nullable=False, index=True),
    Column("subject", String(256), nullable=True),
    Column("severity", String(16), nullable=False, default="warning"),
    Column("status", String(16), nullable=False, default="open", index=True),
    Column("count", Integer, nullable=False, default=1),
    Column("detail", Text),
    Column("first_seen", DateTime, server_default=func.now()),
    Column("last_seen", DateTime, server_default=func.now()),
    Column("acknowledged_at", DateTime, nullable=True),
    Column("acknowledged_by", String(128), nullable=True),
    Column("resolved_at", DateTime, nullable=True),
    Column("resolution", Text, nullable=True),
)

# A fingerprint is "active" while the matching row is open or acknowledged.
# Once resolved/suppressed, a new occurrence gets a fresh row (history kept).
ACTIVE_STATUSES = ("open", "acknowledged")


def _normalize_subject(subject: str | None) -> str | None:
    """Treat None and empty string as the same fingerprint input."""
    if subject is None:
        return None
    s = subject.strip()
    return s or None


def fingerprint_for(source: str, type_: str, subject: str | None) -> str:
    """Compute the dedup fingerprint for an issue. Stable for None subject."""
    import hashlib
    sub = _normalize_subject(subject) or ""
    payload = f"{source}\x00{type_}\x00{sub}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def find_active_by_fingerprint(conn, source: str, type_: str,
                                subject: str | None) -> dict | None:
    """Return the active (open/acknowledged) issue for this fingerprint, or None."""
    fp = fingerprint_for(source, type_, subject)
    stmt = (select(issues)
            .where(and_(issues.c.fingerprint == fp,
                        issues.c.status.in_(ACTIVE_STATUSES))))
    row = conn.execute(stmt).one_or_none()
    return dict(row._mapping) if row else None


def get_by_id(conn, issue_id: int) -> dict | None:
    """Fetch an issue by primary key. Returns dict or None."""
    row = conn.execute(
        select(issues).where(issues.c.id == issue_id)
    ).one_or_none()
    return dict(row._mapping) if row else None


def list_issues(conn, status: str | None = None, source: str | None = None,
                severity: str | None = None, limit: int = 100) -> list[dict]:
    """List issues, newest last_seen first. Optional filters."""
    stmt = select(issues).order_by(issues.c.last_seen.desc()).limit(limit)
    if status:
        stmt = stmt.where(issues.c.status == status)
    if source:
        stmt = stmt.where(issues.c.source == source)
    if severity:
        stmt = stmt.where(issues.c.severity == severity)
    return [dict(r._mapping) for r in conn.execute(stmt).fetchall()]


def count_by_source_severity(conn) -> dict[str, dict[str, int]]:
    """Counts of active issues grouped by source and severity.

    Used by the dashboard summary tiles. Only counts open+acknowledged.
    """
    stmt = (select(issues.c.source, issues.c.severity, func.count())
            .where(issues.c.status.in_(ACTIVE_STATUSES))
            .group_by(issues.c.source, issues.c.severity))
    rows = conn.execute(stmt).fetchall()
    out: dict[str, dict[str, int]] = {}
    for source, severity, n in rows:
        out.setdefault(source, {})[severity] = n
    return out