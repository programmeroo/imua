"""
Database initialization and table definitions.
Aggregates all model metadata and provides `init_db()`.
"""

from sqlalchemy import create_engine
from sqlalchemy import MetaData
import os

from app.models.agent import metadata as agent_meta
from app.models.message import metadata as message_meta
from app.models.secret import metadata as secret_meta
from app.models.task import metadata as task_meta
from app.models.cron import metadata as cron_meta
from app.models.document import metadata as document_meta
from app.models.knowledge import metadata as knowledge_meta
from app.models.issue import metadata as issue_meta
from app.models.admin_user import metadata as admin_meta
from app.models.project import metadata as project_meta
from app.models.audit import metadata as audit_meta


def init_db(app) -> None:
    """Create all tables from the combined metadata."""
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///") and not db_uri.startswith("sqlite:///:memory"):
        db_path = db_uri.replace("sqlite:///", "", 1)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(db_uri)
    combined = MetaData()
    for meta in (agent_meta, message_meta, secret_meta, task_meta, cron_meta,
                 document_meta, knowledge_meta, issue_meta, admin_meta, project_meta, audit_meta):
        for table in meta.tables.values():
            table.to_metadata(combined)
    combined.create_all(engine)
    app.config["DB_ENGINE"] = engine
