"""Tests for imua_mcp.tools_write.register_write_tools.

Covers:
- Registration against a real FastMCP instance does not raise.
- send_message posts to the real /api/messages hub path with the expected
  body shape (to, type, body, optional topic).
- send_message never accepts/forwards a caller-supplied `from` — sender
  identity is the hub's job (derived from the bearer token), not this
  tool's.
- The ImuaClientError -> {"ok": False, ...} envelope matches tools_read.py.
"""

import unittest
from typing import Any

from mcp.server.fastmcp import FastMCP

from imua_mcp.client import ImuaClientError
from imua_mcp.tools_write import register_write_tools


class _RecordingClient:
    """Fake ImuaClient that records POSTs instead of hitting a hub."""

    def __init__(self, response: dict[str, Any] | None = None, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._response = response if response is not None else {"id": "msg-1"}
        self._raises = raises

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((path, body))
        if self._raises:
            raise self._raises
        return self._response


def _build(response: dict[str, Any] | None = None, raises: Exception | None = None):
    mcp = FastMCP(name="test")
    client = _RecordingClient(response, raises=raises)
    register_write_tools(mcp, token_file=None, client=client, agent_name="TEST")
    return mcp, client


def _tool(mcp: FastMCP, name: str):
    return mcp._tool_manager._tools[name].fn


class Registration(unittest.TestCase):
    def test_register_write_tools_does_not_raise(self):
        try:
            _build()
        except ValueError as e:
            self.fail(f"register_write_tools raised on a fresh FastMCP instance: {e}")

    def test_send_message_registered(self):
        mcp, _ = _build()
        names = {t.name for t in mcp._tool_manager.list_tools()}
        self.assertIn("send_message", names)
        self.assertIn("mark_messages_read", names)


class SendMessage(unittest.TestCase):
    def test_posts_to_api_messages_with_expected_body(self):
        mcp, client = _build()
        result = _tool(mcp, "send_message")(to="SVY", body="hello")
        self.assertEqual(
            client.calls,
            [("/api/messages", {"to": "SVY", "type": "chat", "body": "hello"})],
        )
        self.assertEqual(result, {"ok": True, "data": {"id": "msg-1"}})

    def test_custom_type_and_topic_included(self):
        mcp, client = _build()
        _tool(mcp, "send_message")(to="SVY,SLK", body="ship it", type="request", topic="deploy")
        self.assertEqual(
            client.calls,
            [("/api/messages", {"to": "SVY,SLK", "type": "request", "body": "ship it", "topic": "deploy"})],
        )

    def test_broadcast_to_all(self):
        mcp, client = _build()
        _tool(mcp, "send_message")(to="all", body="status update", type="broadcast")
        self.assertEqual(
            client.calls,
            [("/api/messages", {"to": "all", "type": "broadcast", "body": "status update"})],
        )

    def test_no_from_parameter_exists(self):
        """Sender is derived hub-side from the bearer token — the tool must
        not expose a `from` argument a caller could use to spoof identity."""
        import inspect

        mcp, _ = _build()
        sig = inspect.signature(_tool(mcp, "send_message"))
        self.assertNotIn("from", sig.parameters)
        self.assertNotIn("sender", sig.parameters)

    def test_error_envelope_matches_read_tools(self):
        mcp, _ = _build(raises=ImuaClientError("forbidden", "not allowed", status=403))
        result = _tool(mcp, "send_message")(to="SVY", body="hi")
        self.assertEqual(
            result,
            {"ok": False, "error": "forbidden", "message": "not allowed", "status": 403},
        )


if __name__ == "__main__":
    unittest.main()


class MarkMessagesRead(unittest.TestCase):
    def test_posts_ids_to_bulk_read_endpoint(self):
        mcp, client = _build(response={"marked": [1, 2], "skipped": [3]})
        result = _tool(mcp, "mark_messages_read")(ids=[1, 2, 3])
        self.assertEqual(client.calls, [("/api/messages/read", {"ids": [1, 2, 3]})])
        self.assertEqual(result, {"ok": True, "data": {"marked": [1, 2], "skipped": [3]}})

    def test_hub_error_returns_error_envelope(self):
        err = ImuaClientError("validation_error", "bad ids", status=422)
        mcp, _ = _build(raises=err)
        result = _tool(mcp, "mark_messages_read")(ids=[1])
        self.assertEqual(result, {"ok": False, "error": "validation_error", "message": "bad ids", "status": 422})


class _TaskClient(_RecordingClient):
    def patch(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((path, body))
        if self._raises:
            raise self._raises
        return self._response


def _build_tasks(response=None, raises=None):
    mcp = FastMCP(name="test")
    client = _TaskClient(response or {"id": 7}, raises=raises)
    register_write_tools(mcp, token_file=None, client=client, agent_name="TEST")
    return mcp, client


class TaskTools(unittest.TestCase):
    """Task 6.11a: create_task / claim_task / complete_task."""

    def test_create_task_minimal(self):
        mcp, client = _build_tasks()
        result = _tool(mcp, "create_task")(type="build", title="Hero")
        self.assertEqual(client.calls, [("/api/tasks", {"type": "build", "title": "Hero", "priority": 3})])
        self.assertTrue(result["ok"])

    def test_create_task_with_project_and_assignee(self):
        mcp, client = _build_tasks()
        _tool(mcp, "create_task")(type="build", project="lead-gen", assigned_to="AKM", tags=["web"])
        body = client.calls[0][1]
        self.assertEqual((body["project"], body["assigned_to"], body["tags"]), ("lead-gen", "AKM", ["web"]))
        self.assertNotIn("created_by", body)  # the hub takes the creator from the token

    def test_claim_task(self):
        mcp, client = _build_tasks({"task": None})
        _tool(mcp, "claim_task")(capabilities=["build", "python"])
        self.assertEqual(client.calls, [("/api/tasks/claim", {"capabilities": ["build", "python"]})])

    def test_complete_and_fail(self):
        mcp, client = _build_tasks()
        _tool(mcp, "complete_task")(task_id=7, result="shipped")
        _tool(mcp, "complete_task")(task_id=8, failed=True)
        self.assertEqual(client.calls, [("/api/tasks/7", {"status": "completed", "result": "shipped"}),
                                        ("/api/tasks/8", {"status": "failed"})])

    def test_error_envelope(self):
        mcp, _ = _build_tasks(raises=ImuaClientError("not_found", "No project 'x'", 404))
        result = _tool(mcp, "create_task")(type="build", project="x")
        self.assertEqual(result, {"ok": False, "error": "not_found", "message": "No project 'x'", "status": 404})


class KnowledgeAndCronTools(unittest.TestCase):
    """Task 6.11b: add_knowledge / create_cron_job."""

    def test_add_knowledge(self):
        mcp, client = _build_tasks()
        _tool(mcp, "add_knowledge")(body="Lead with the monthly payment.", title="Brand voice",
                                    tags=["style"], project="lead-gen")
        expected = {"body": "Lead with the monthly payment.", "title": "Brand voice", "source": "manual",
                    "tags": ["style"], "project": "lead-gen"}
        self.assertEqual(client.calls, [("/api/knowledge", expected)])

    def test_add_knowledge_without_project(self):
        mcp, client = _build_tasks()
        _tool(mcp, "add_knowledge")(body="x")
        self.assertNotIn("project", client.calls[0][1])
        self.assertNotIn("agent", client.calls[0][1])  # the hub takes the agent from the token

    def test_create_cron_job(self):
        mcp, client = _build_tasks()
        _tool(mcp, "create_cron_job")(name="nightly", schedule="0 2 * * *", schedule_human="Every day at 2am",
                                      assigned_to="AKM", project="lead-gen")
        expected = {"name": "nightly", "schedule": "0 2 * * *", "schedule_human": "Every day at 2am",
                    "description": "", "assigned_to": "AKM", "project": "lead-gen"}
        self.assertEqual(client.calls, [("/api/cron", expected)])

    def test_error_envelope(self):
        mcp, _ = _build_tasks(raises=ImuaClientError("validation_error", "'schedule' is required", 422))
        result = _tool(mcp, "create_cron_job")(name="x", schedule="")
        self.assertEqual((result["ok"], result["status"]), (False, 422))


class IssueTools(unittest.TestCase):
    """Task 6.11c: report_issue / update_issue_status."""

    def test_report_issue_defaults_source_to_agent(self):
        mcp, client = _build_tasks()
        _tool(mcp, "report_issue")(type="broken_dependency", subject="mcp 2.0 renamed fastmcp", detail="pin <2")
        expected = {"source": "test", "type": "broken_dependency", "subject": "mcp 2.0 renamed fastmcp",
                    "severity": "warning", "detail": "pin <2"}
        self.assertEqual(client.calls, [("/api/issues", expected)])

    def test_report_issue_explicit_source_and_severity(self):
        mcp, client = _build_tasks()
        _tool(mcp, "report_issue")(type="t", subject="s", severity="critical", source="n8n")
        self.assertEqual((client.calls[0][1]["source"], client.calls[0][1]["severity"]), ("n8n", "critical"))

    def test_update_issue_status(self):
        mcp, client = _build_tasks()
        _tool(mcp, "update_issue_status")(issue_id=3, action="acknowledge")
        _tool(mcp, "update_issue_status")(issue_id=3, action="resolve", resolution="pinned mcp<2")
        self.assertEqual(client.calls, [("/api/issues/3/acknowledge", {}),
                                        ("/api/issues/3/resolve", {"resolution": "pinned mcp<2"})])

    def test_update_issue_status_rejects_unknown_action(self):
        mcp, client = _build_tasks()
        result = _tool(mcp, "update_issue_status")(issue_id=3, action="delete")
        self.assertEqual((result["ok"], result["error"], client.calls), (False, "validation_error", []))


NEW_TOKEN = "b" * 64


class _VaultClient(_TaskClient):
    """Adds get + use_token; patch returns a rotation response."""

    def __init__(self, response=None, raises=None, post_raises=None):
        super().__init__(response, raises)
        self.pinned = None
        self._post_raises = post_raises

    def get(self, path):
        self.calls.append((path, None))
        return {"name": "k", "value": "s3cret"}

    def post(self, path, body=None):
        if self._post_raises:
            self.calls.append((path, body))
            raise self._post_raises
        return super().post(path, body)

    def use_token(self, token):
        self.pinned = token


class _TokenFile:
    def __init__(self, fail=False):
        self.written, self._fail = None, fail

    def write(self, token):
        if self._fail:
            raise OSError("disk full")
        self.written = token


def _build_vault(response=None, raises=None, file_fails=False, post_raises=None):
    mcp = FastMCP(name="test")
    client = _VaultClient(response if response is not None else {"token": NEW_TOKEN}, raises, post_raises)
    tf = _TokenFile(fail=file_fails)
    register_write_tools(mcp, token_file=tf, client=client, agent_name="AKM")
    return mcp, client, tf


class VaultTools(unittest.TestCase):
    """Task 6.11d: get_secret / put_secret."""

    def test_get_secret_encodes_name(self):
        mcp, client, _ = _build_vault()
        _tool(mcp, "get_secret")(name="a/b")
        self.assertEqual(client.calls, [("/api/vault/secrets/a%2Fb", None)])

    def test_put_secret(self):
        mcp, client, _ = _build_vault({"status": "stored"})
        _tool(mcp, "put_secret")(name="k", value="v", description="d", access_scope=["AKM"])
        self.assertEqual(client.calls, [("/api/vault/secrets",
                                         {"name": "k", "value": "v", "description": "d", "access_scope": ["AKM"]})])


class RotateToken(unittest.TestCase):
    """Task 6.11d: rotate_token never shows the token and never strands the agent."""

    def test_success_writes_file_and_hides_token(self):
        mcp, client, tf = _build_vault()
        result = _tool(mcp, "rotate_token")()
        self.assertEqual(client.calls, [("/api/agents/AKM/token", None)])
        self.assertEqual(tf.written, NEW_TOKEN)
        self.assertTrue(result["ok"] and result["data"]["token_file_updated"])
        self.assertNotIn(NEW_TOKEN, str(result))

    def test_hub_refuses_nothing_changes(self):
        mcp, client, tf = _build_vault(raises=ImuaClientError("unauthorized", "Valid bearer token required", 401))
        result = _tool(mcp, "rotate_token")()
        self.assertEqual((result["ok"], result["status"], tf.written, client.pinned), (False, 401, None, None))

    def test_file_write_fails_keeps_working_and_backs_up(self):
        mcp, client, _ = _build_vault(file_fails=True)
        result = _tool(mcp, "rotate_token")()
        self.assertEqual(client.pinned, NEW_TOKEN)  # this server keeps working on the new token
        path, body = client.calls[-1]
        self.assertEqual(path, "/api/vault/secrets")
        self.assertTrue(body["name"].startswith("AKM_token_rotated_") and body["value"] == NEW_TOKEN)
        self.assertEqual(result["error"], "token_file_write_failed")
        self.assertIn(body["name"], result["message"])
        self.assertNotIn(NEW_TOKEN, str(result))

    def test_file_and_vault_both_fail(self):
        mcp, client, _ = _build_vault(file_fails=True, post_raises=ImuaClientError("conflict", "exists", 409))
        result = _tool(mcp, "rotate_token")()
        self.assertEqual(client.pinned, NEW_TOKEN)
        self.assertIn("memory only", result["message"])
        self.assertNotIn(NEW_TOKEN, str(result))
