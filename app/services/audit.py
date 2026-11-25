"""
Audit log service (task 5.6, docs/imua_admin_security_plan_v1.md).

    record(actor, action, ...)  write one entry (never raises: logging must not
                                break the request it describes)
    recent(conn, ...)           newest first, with optional filters
    init_app(app)               after_request hook: records every admin write

"Admin write" = POST/PUT/PATCH/DELETE where the caller authenticated as an admin
(signed-in session or operator key). The auth decorators mark that on flask.g
(g.is_operator / g.admin_username), so routes added later are covered without
any per-route code. Sign-in events are recorded explicitly by app/routes/auth.py.
"""

import logging
from datetime import datetime

from flask import current_app, g, request
from sqlalchemy import select

from app.models.audit import audit_log

log = logging.getLogger(__name__)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip() -> str:
    return request.remote_addr or ""


def record(actor: str, action: str, target: str | None = None, status: int | None = None,
           detail: str | None = None, ip: str | None = None) -> None:
    try:
        with current_app.config["DB_ENGINE"].begin() as conn:
            conn.execute(audit_log.insert().values(
                at=datetime.utcnow(), actor=(actor or "?")[:128], action=action[:64],
                target=(target or "")[:256] or None, status=status, ip=ip if ip is not None else client_ip(),
                detail=detail))
    except Exception:  # never let auditing break the action itself
        log.exception("audit log write failed: %s %s", actor, action)


def recent(conn, limit: int = 100, before_id: int | None = None, actor: str | None = None) -> list[dict]:
    q = select(audit_log).order_by(audit_log.c.id.desc()).limit(limit)
    if before_id:
        q = q.where(audit_log.c.id < before_id)
    if actor:
        q = q.where(audit_log.c.actor == actor)
    return [r._asdict() for r in conn.execute(q)]


def _after_request(response):
    if request.method in WRITE_METHODS and g.get("is_operator"):
        actor = g.get("admin_username") or "operator"
        record(actor, f"{request.method} {request.url_rule.rule if request.url_rule else request.path}",
               target=request.path, status=response.status_code)
    return response


def init_app(app) -> None:
    app.after_request(_after_request)
