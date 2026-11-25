"""
Admin users — people who sign in to the dashboard (task 5.2,
docs/imua_admin_security_plan_v1.md). Agents are not admins: they use bearer
tokens (app/models/agent.py) and never get a row here.

Passwords are stored only as scrypt hashes. There is no default account; the
first admin is created on the server with scripts/create_admin.py.
"""

from sqlalchemy import Table, Column, Integer, String, DateTime, Boolean, MetaData, func

metadata = MetaData()

admin_users = Table(
    "admin_users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False, unique=True),  # stored lowercase
    Column("password_hash", String(256), nullable=False),
    Column("disabled", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, server_default=func.now()),
    Column("last_login_at", DateTime, nullable=True),
)
