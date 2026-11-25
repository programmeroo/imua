"""Unit tests for Task Queue service layer."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.task_queue import (
    _backoff_seconds, _find_best_agent, dispatch_task, claim_next_task,
    complete_task, fail_task, escalate_overdue_tasks,
)


class TestBackoff:
    def test_backoff_doubles(self):
        assert _backoff_seconds(0) == 30
        assert _backoff_seconds(1) == 60
        assert _backoff_seconds(2) == 120
        assert _backoff_seconds(3) == 240


class TestFindBestAgent:
    def test_returns_none_when_no_agents(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        assert _find_best_agent(conn, "code.write") is None

    def test_picks_matching_agent(self):
        conn = MagicMock()
        row_a = MagicMock()
        row_a.name = "AKM"
        row_a.capabilities = json.dumps(["flask", "cron"])
        row_b = MagicMock()
        row_b.name = "SVY"
        row_b.capabilities = json.dumps(["schemas", "code-review"])
        conn.execute.return_value.fetchall.return_value = [row_a, row_b]
        conn.execute.return_value.scalar.return_value = 0
        result = _find_best_agent(conn, "code-review")
        assert result == "SVY"

    def test_picks_least_loaded(self):
        conn = MagicMock()
        row_a = MagicMock()
        row_a.name = "AKM"
        row_a.capabilities = json.dumps(["flask", "code-review"])
        row_b = MagicMock()
        row_b.name = "SVY"
        row_b.capabilities = json.dumps(["code-review"])
        conn.execute.return_value.fetchall.return_value = [row_a, row_b]
        # AKM has 2 in_progress, SVY has 0
        call_count = [0]
        def _scalar():
            call_count[0] += 1
            return 2 if call_count[0] == 1 else 0
        conn.execute.return_value.scalar = _scalar
        result = _find_best_agent(conn, "code-review")
        assert result == "SVY"


class TestDispatchTask:
    def test_assigns_to_matching_agent(self):
        conn = MagicMock()
        task_row = {"id": 1, "type": "code.write", "status": "pending",
                     "assigned_to": None, "assigned_at": None,
                     "retry_count": 0, "max_retries": 3}
        conn.execute.return_value.one_or_none.return_value = MagicMock(
            _mapping=task_row
        )
        row = MagicMock()
        row.name = "AKM"
        row.capabilities = json.dumps(["code.write"])
        conn.execute.return_value.fetchall.return_value = [row]
        conn.execute.return_value.scalar.return_value = 0

        result = dispatch_task(conn, 1)
        assert result["assigned_to"] == "AKM"


class TestClaimNextTask:
    def test_claims_matching_unassigned(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.side_effect = [
            # list_unassigned returns 1 task
            [MagicMock(_mapping={"id": 1, "type": "code.write", "status": "pending",
                                  "priority": 3, "assigned_to": None,
                                  "created_at": datetime.utcnow()})],
            # get_task_by_id after claim
            [MagicMock(_mapping={"id": 1, "type": "code.write", "status": "in_progress",
                                  "assigned_to": "AKM"})],
        ]
        # For the two fetches inside claim_next_task
        conn.execute.return_value.one_or_none.side_effect = [
            MagicMock(_mapping={"id": 1, "type": "code.write", "status": "in_progress",
                                 "assigned_to": "AKM"}),
        ]
        result = claim_next_task(conn, "AKM", ["code.write"])
        assert result["task"]["status"] == "in_progress"
        assert result["task"]["assigned_to"] == "AKM"

    def test_no_match_returns_none(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.side_effect = [
            [MagicMock(_mapping={"id": 1, "type": "code.write", "status": "pending",
                                  "priority": 3, "assigned_to": None,
                                  "created_at": datetime.utcnow()})],
        ]
        result = claim_next_task(conn, "AKM", ["n8n"])
        assert result["task"] is None


class TestCompleteTask:
    def test_marks_completed(self):
        conn = MagicMock()
        conn.execute.return_value.one_or_none.return_value = MagicMock(
            _mapping={"id": 1, "status": "completed"}
        )
        result = complete_task(conn, 1, "done")
        assert result["task"]["status"] == "completed"


class TestFailTask:
    def test_requeues_with_backoff(self):
        now = datetime.utcnow()
        conn = MagicMock()
        conn.execute.return_value.one_or_none.return_value = MagicMock(
            _mapping={"id": 1, "retry_count": 0, "max_retries": 3,
                       "assigned_to": "AKM"}
        )
        result = fail_task(conn, 1, "timeout")
        assert result["retry_count"] == 1
        assert result["maxed_out"] is False

    def test_escalates_after_max_retries(self):
        conn = MagicMock()
        conn.execute.return_value.one_or_none.return_value = MagicMock(
            _mapping={"id": 1, "retry_count": 2, "max_retries": 3,
                       "assigned_to": "AKM"}
        )
        result = fail_task(conn, 1, "final failure")
        assert result["retry_count"] == 3
        assert result["maxed_out"] is True


class TestEscalateOverdue:
    def test_flags_overdue_tasks(self):
        conn = MagicMock()
        now = datetime.utcnow()
        old = now - timedelta(hours=2)
        conn.execute.return_value.fetchall.return_value = [
            MagicMock(_mapping={"id": 1, "type": "code.write", "title": "Fix bug",
                                 "status": "pending", "assigned_to": None,
                                 "created_at": old, "escalated": False}),
        ]
        flagged = escalate_overdue_tasks(conn, threshold_minutes=30)
        assert len(flagged) == 1
        assert flagged[0]["id"] == 1
