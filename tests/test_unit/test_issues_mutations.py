"""
Unit tests for Issues service: report_issue, resolve_issue, acknowledge_issue.

PR 1c-1 of task 1.9. PR 1c-2 will cover list/suppress/summary.

Self-contained (no shared fixtures): the root tests/conftest.py triggers
create_app() which imports chromadb, and this dev venv lacks it. These
tests don't need the app fixture — they exercise the service layer
directly against in-memory SQLite.

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
    """Connection that auto-commits on context exit (for test convenience)."""
    connection = db_engine.connect()
    yield connection
    connection.commit()
    connection.close()


# ---------- report_issue ----------

class TestReportIssue:
    """report_issue creates a new row or updates an existing active one."""

    def test_first_report_creates_row(self, conn):
        result = svc.report_issue(
            conn, "vault", "access_denied", "secret-1", "warning", "first"
        )
        conn.commit()

        assert result["created"] is True
        assert result["count"] == 1
        assert result["status"] == "open"
        assert result["source"] == "vault"
        assert result["type"] == "access_denied"
        assert result["subject"] == "secret-1"
        assert result["severity"] == "warning"
        assert result["detail"] == "first"

    def test_repeat_report_increments_count(self, conn):
        svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()
        result = svc.report_issue(
            conn, "vault", "access_denied", "secret-1", "warning", "second"
        )
        conn.commit()

        assert result["created"] is False
        assert result["count"] == 2
        assert result["detail"] == "second"

    def test_different_subject_creates_new_row(self, conn):
        svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()
        result = svc.report_issue(
            conn, "vault", "access_denied", "secret-2", "error"
        )
        conn.commit()

        assert result["created"] is True
        assert result["subject"] == "secret-2"

    def test_different_source_same_type_subject_creates_new_row(self, conn):
        svc.report_issue(conn, "vault", "hook_failed", "abc", "warning")
        conn.commit()
        result = svc.report_issue(
            conn, "git", "hook_failed", "abc", "warning"
        )
        conn.commit()

        assert result["created"] is True
        assert result["source"] == "git"

    def test_none_subject_treated_as_empty(self, conn):
        a = svc.report_issue(conn, "agents", "ws_disconnect", None, "warning")
        conn.commit()
        b = svc.report_issue(conn, "agents", "ws_disconnect", "", "warning")
        conn.commit()
        c = svc.report_issue(conn, "agents", "ws_disconnect", "   ", "warning")
        conn.commit()

        assert a["id"] == b["id"] == c["id"]
        assert c["count"] == 3

    def test_report_after_resolve_creates_fresh_row(self, conn):
        """History is kept — re-occurrence is a new issue, not a re-open."""
        r1 = svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "access_denied", "secret-1", "fixed")
        conn.commit()

        r2 = svc.report_issue(
            conn, "vault", "access_denied", "secret-1", "warning", "recurred"
        )
        conn.commit()

        assert r2["id"] != r1["id"]
        assert r2["created"] is True
        assert r2["count"] == 1
        assert r2["status"] == "open"

    def test_invalid_severity_raises(self, conn):
        with pytest.raises(ValueError, match="severity"):
            svc.report_issue(conn, "vault", "x", None, "BOGUS")

    def test_empty_source_raises(self, conn):
        with pytest.raises(ValueError, match="source"):
            svc.report_issue(conn, "", "x", None, "warning")

    def test_empty_type_raises(self, conn):
        with pytest.raises(ValueError, match="type"):
            svc.report_issue(conn, "vault", "", None, "warning")

    @pytest.mark.parametrize("severity", ["info", "warning", "error", "critical"])
    def test_all_valid_severities_accepted(self, conn, severity):
        result = svc.report_issue(conn, "vault", "x", None, severity)
        conn.commit()
        assert result["severity"] == severity


# ---------- resolve_issue ----------

class TestResolveIssue:
    """resolve_issue transitions an active issue to resolved."""

    def test_resolve_open_issue(self, conn):
        r = svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()

        ok = svc.resolve_issue(
            conn, "vault", "access_denied", "secret-1", "key rotated"
        )
        conn.commit()

        assert ok is True
        row = svc.get_by_id(conn, r["id"])
        assert row["status"] == "resolved"
        assert row["resolution"] == "key rotated"
        assert row["resolved_at"] is not None

    def test_resolve_nonexistent_returns_false(self, conn):
        ok = svc.resolve_issue(conn, "vault", "access_denied", "nope")
        assert ok is False

    def test_resolve_already_resolved_is_noop(self, conn):
        svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "access_denied", "secret-1", "first")
        conn.commit()

        # Second resolve finds the active row gone, returns False (no-op).
        ok = svc.resolve_issue(conn, "vault", "access_denied", "secret-1", "second")
        assert ok is False

    def test_resolve_acknowledged_issue(self, conn):
        r = svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()
        svc.acknowledge_issue(conn, r["id"], "slk")
        conn.commit()

        ok = svc.resolve_issue(conn, "vault", "access_denied", "secret-1")
        conn.commit()
        assert ok is True
        row = svc.get_by_id(conn, r["id"])
        assert row["status"] == "resolved"

    def test_resolve_does_not_match_suppressed(self, conn):
        """Suppressed is also inactive — resolve should not match it."""
        r = svc.report_issue(conn, "vault", "access_denied", "secret-1", "warning")
        conn.commit()
        svc.suppress_issue(conn, r["id"])
        conn.commit()

        ok = svc.resolve_issue(conn, "vault", "access_denied", "secret-1")
        assert ok is False


# ---------- acknowledge_issue ----------

class TestAcknowledgeIssue:
    """acknowledge_issue transitions open → acknowledged."""

    def test_acknowledge_open_issue(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()

        ok = svc.acknowledge_issue(conn, r["id"], "slk")
        conn.commit()

        assert ok is True
        row = svc.get_by_id(conn, r["id"])
        assert row["status"] == "acknowledged"
        assert row["acknowledged_by"] == "slk"
        assert row["acknowledged_at"] is not None

    def test_acknowledge_is_idempotent(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.acknowledge_issue(conn, r["id"], "slk")
        conn.commit()

        ok = svc.acknowledge_issue(conn, r["id"], "akm")  # different actor
        conn.commit()

        assert ok is True
        row = svc.get_by_id(conn, r["id"])
        # First ack wins; actor is not overwritten.
        assert row["acknowledged_by"] == "slk"

    def test_acknowledge_nonexistent_returns_false(self, conn):
        ok = svc.acknowledge_issue(conn, 99999, "slk")
        assert ok is False

    def test_acknowledge_resolved_raises(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.resolve_issue(conn, "vault", "x", "secret-1")
        conn.commit()

        with pytest.raises(ValueError, match="Cannot acknowledge"):
            svc.acknowledge_issue(conn, r["id"], "slk")

    def test_acknowledge_suppressed_raises(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()
        svc.suppress_issue(conn, r["id"])
        conn.commit()

        with pytest.raises(ValueError, match="Cannot acknowledge"):
            svc.acknowledge_issue(conn, r["id"], "slk")

    def test_acknowledge_requires_actor(self, conn):
        r = svc.report_issue(conn, "vault", "x", "secret-1", "warning")
        conn.commit()

        with pytest.raises(ValueError, match="agent_or_operator"):
            svc.acknowledge_issue(conn, r["id"], "")