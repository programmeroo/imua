"""
Projects — the highest-level grouping in Imua (task 6.2,
docs/imua_projects_plan_v1.md).

A project contains tasks, documents, cron jobs and knowledge entries, and has
member agents. Membership and contents live in link tables so no existing table
gains a column (plan D1: the hub has no migration tool; init_db() creates these
new tables on the next start).
"""

from sqlalchemy import (Table, Column, Integer, String, Text, DateTime, MetaData, ForeignKey,
                        UniqueConstraint, func)

metadata = MetaData()

ITEM_TYPES = ("task", "document", "cron", "knowledge")

projects = Table(
    "projects",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("slug", String(64), nullable=False, unique=True, index=True),
    Column("name", String(128), nullable=False),
    Column("description", Text, default=""),
    Column("status", String(16), nullable=False, default="active"),  # active | archived
    Column("created_by", String(128)),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now(), onupdate=func.now()),
)

project_agents = Table(
    "project_agents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("project_id", Integer, ForeignKey("projects.id"), nullable=False, index=True),
    Column("agent_name", String(128), nullable=False, index=True),
    Column("added_at", DateTime, server_default=func.now()),
    UniqueConstraint("project_id", "agent_name", name="uq_project_agent"),
)

# One row per item that is in a project. The unique key on (item_type, item_id)
# keeps each item in at most one project (plan D4).
project_items = Table(
    "project_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("project_id", Integer, ForeignKey("projects.id"), nullable=False, index=True),
    Column("item_type", String(16), nullable=False),  # one of ITEM_TYPES
    Column("item_id", Integer, nullable=False),
    Column("added_by", String(128)),
    Column("added_at", DateTime, server_default=func.now()),
    UniqueConstraint("item_type", "item_id", name="uq_project_item"),
)
