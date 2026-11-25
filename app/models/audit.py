"""
Audit log — every admin action (task 5.6, docs/imua_admin_security_plan_v1.md).

One row per admin write (any POST/PUT/PATCH/DELETE made with an admin session or
the operator key) and per sign-in event (success, failure, lockout, sign-out).
Agent-token requests are not admin actions and aren't recorded here.
"""

from sqlalchemy import Table, Column, Integer, String, Text, DateTime, MetaData

metadata = MetaData()

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("at", DateTime, nullable=False, index=True),
    Column("actor", String(128), nullable=False, index=True),  # admin username, "operator", or the name tried
    Column("action", String(64), nullable=False, index=True),  # e.g. "sign_in", "POST /api/projects"
    Column("target", String(256)),                             # e.g. "/api/projects/lead-gen"
    Column("status", Integer),                                 # HTTP status of the result
    Column("ip", String(64)),
    Column("detail", Text),
)
