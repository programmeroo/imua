"""
Unit tests for Issues service: list_issues, suppress_issue, summary.

PR 1c-2 of task 1.9. PR 1c-1 covered report/resolve/acknowledge.

Self-contained (no shared fixtures): see test_issues_mutations.py for why.

Reference: docs/imua_flask_specification_v3.md §4.
"""

import pytest
from flask import Flask

from app.models import init_db
from app.services import issues as svc


@pytest.fixture
def db_engine():
    """In-memory SQLite engine with all tables created via init_db()."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    init_db(app)
    return app.config["DB_ENGINE"]


@pytest.fixture
def conn(db_engine):
    """Connection that auto-commits on context exit."""
    connection = db_engine.connect()
    yield connection
    connection.commit()
    connection.close()


# ---------- list_issues ----------

class TestListIssues:
    """list_issues filters and ordering semantics."""

    def test_default_returns_active_only(self, conn):
        svc.report_issue(conn, "vault", "x", "active-1", "warning")
        conn.commit()
        svc.report_issue(conn, "vault", "x", "resolved-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "x", "resolved-1")
        conn.commit()
        r3 = svc.report_issue(conn, "vault", "x", "suppressed-1", "warning")
        conn.commit()
        svc.suppress_issue(conn, r3["id"])
        conn.commit()

        rows = svc.list_issues(conn)
        subjects = [r["subject"] for r in rows]
        assert subjects == ["active-1"]

    def test_status_all_returns_everything(self, conn):
        svc.report_issue(conn, "vault", "x", "open-1", "warning")
        conn.commit()
        svc.report_issue(conn, "vault", "x", "resolved-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "x", "resolved-1")
        conn.commit()

        rows = svc.list_issues(conn, status="all")
        assert len(rows) == 2

    def test_status_resolved_returns_history(self, conn):
        svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "x", "secret-1")
        conn.commit()

        rows = svc.list_issues(conn, status="resolved")
        assert len(rows) == 1
        assert rows[0]["subject"] == "secret-1"

    def test_status_suppressed_returns_history(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.suppress_issue(conn, r["id"])
        conn.commit()

        rows = svc.list_issues(conn, status="suppressed")
        assert len(rows) == 1
        assert rows[0]["subject"] == "secret-1"

    def test_filter_by_source(self, conn):
        svc.report_issue(conn, "vault", "x", "v-1", "warning")
        conn.commit()
        svc.report_issue(conn, "agents", "y", "a-1", "warning")
        conn.commit()

        rows = svc.list_issues(conn, source="vault")
        assert len(rows) == 1
        assert rows[0]["source"] == "vault"

    def test_filter_by_severity(self, conn):
        svc.report_issue(conn, "vault", "x", "warn-1", "warning")
        conn.commit()
        svc.report_issue(conn, "vault", "x", "err-1", "error")
        conn.commit()

        rows = svc.list_issues(conn, severity="error")
        assert len(rows) == 1
        assert rows[0]["subject"] == "err-1"

    def test_combined_filters(self, conn):
        svc.report_issue(conn, "vault", "x", "vault-err", "error")
        conn.commit()
        svc.report_issue(conn, "agents", "x", "agents-err", "error")
        conn.commit()
        svc.report_issue(conn, "vault", "x", "vault-warn", "warning")
        conn.commit()

        rows = svc.list_issues(conn, source="vault", severity="error")
        assert len(rows) == 1
        assert rows[0]["subject"] == "vault-err"

    def test_invalid_status_raises(self, conn):
        with pytest.raises(ValueError, match="status"):
            svc.list_issues(conn, status="BOGUS")

    def test_invalid_severity_raises(self, conn):
        with pytest.raises(ValueError, match="severity"):
            svc.list_issues(conn, severity="BOGUS")

    def test_limit_respected(self, conn):
        for i in range(5):
            svc.report_issue(conn, "vault", "x", f"sub-{i}", "warning")
            conn.commit()
        rows = svc.list_issues(conn, status="all", limit=3)
        assert len(rows) == 3


# ---------- suppress_issue ----------

class TestSuppressIssue:
    """suppress_issue hides an active issue from the dashboard."""

    def test_suppress_open_issue(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()

        ok = svc.suppress_issue(conn, r["id"])
        conn.commit()

        assert ok is True
        row = svc.get_by_id(conn, r["id"])
        assert row["status"] == "suppressed"

    def test_suppress_is_idempotent(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.suppress_issue(conn, r["id"])
        conn.commit()

        ok = svc.suppress_issue(conn, r["id"])
        assert ok is True

    def test_suppress_nonexistent_returns_false(self, conn):
        ok = svc.suppress_issue(conn, 99999)
        assert ok is False

    def test_suppress_resolved_raises(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "x", "secret-1")
        conn.commit()

        with pytest.raises(ValueError, match="Cannot suppress resolved"):
            svc.suppress_issue(conn, r["id"])

    def test_suppress_acknowledged_succeeds(self, conn):
        """Suppressed is allowed from acknowledged — operator can hide
        even seen-but-unresolved issues."""
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.acknowledge_issue(conn, r["id"], "slk")
        conn.commit()

        ok = svc.suppress_issue(conn, r["id"])
        conn.commit()
        assert ok is True


# ---------- summary ----------

class TestSummary:
    """summary counts active issues by source × severity."""

    def test_empty_db_returns_empty_dict(self, conn):
        assert svc.summary(conn) == {}

    def test_counts_active_only(self, conn):
        svc.report_issue(conn, "vault", "x", "v-warn", "warning")
        conn.commit()
        svc.report_issue(conn, "vault", "x", "v-err", "error")
        conn.commit()
        svc.report_issue(conn, "agents", "x", "a-info", "info")
        conn.commit()
        r = svc.report_issue(conn, "git", "x", "g-resolved", "warning")
        conn.commit()
        svc.resolve_issue(conn, "git", "x", "g-resolved")
        conn.commit()
        r2 = svc.report_issue(conn, "tasks", "x", "t-suppressed", "warning")
        conn.commit()
        svc.suppress_issue(conn, r2["id"])
        conn.commit()

        result = svc.summary(conn)
        assert result == {
            "vault": {"warning": 1, "error": 1},
            "agents": {"info": 1},
        }

    def test_counts_after_acknowledge_still_active(self, conn):
        """Acknowledged issues count as active (still need resolution)."""
        r = svc.report_issue(conn, "vault", "x", "v-warn", "warning")
        conn.commit()
        svc.acknowledge_issue(conn, r["id"], "slk")
        conn.commit()

        result = svc.summary(conn)
        assert result == {"vault": {"warning": 1}}