"""Tests for imua_mcp.tools_read.register_read_tools.

Covers:
- Registration against a real FastMCP instance does not raise (regression
  for a bug where resource URIs used regex named-group syntax instead of
  FastMCP's `{param}` template syntax, which crashed the server on startup).
- Tools build correctly URL-encoded query strings (regression for a bug
  where query params were concatenated via raw f-strings, letting values
  containing "&"/"#"/"%" corrupt the request or inject extra params).
- Every tool/resource calls the real /api/... hub path (regression for a
  bug where every single one was missing the /api prefix and either hit
  the HTML dashboard route or 404'd).
- resource_knowledge_search reads the "hits" key GET /api/knowledge
  actually returns, not "data" (regression — it always reported "no
  results" regardless of real hits).
- Templated resources resolve and read back expected content.
"""

import asyncio
import unittest
from typing import Any

from mcp.server.fastmcp import FastMCP

from imua_mcp.tools_read import register_read_tools


class _RecordingClient:
    """Fake ImuaClient that records requested paths instead of hitting a hub."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[str] = []
        self._response = response if response is not None else {"hits": []}

    def get(self, path: str) -> dict[str, Any]:
        self.calls.append(path)
        return self._response


def _build(response: dict[str, Any] | None = None) -> tuple[FastMCP, _RecordingClient]:
    mcp = FastMCP(name="test")
    client = _RecordingClient(response)
    register_read_tools(mcp, token_file=None, client=client, agent_name="TEST")
    return mcp, client


def _tool(mcp: FastMCP, name: str):
    return mcp._tool_manager._tools[name].fn


class Registration(unittest.TestCase):
    def test_register_read_tools_does_not_raise(self):
        """Regression: resource templates must use FastMCP's {param} syntax,
        not regex named groups, or registration raises ValueError."""
        try:
            _build()
        except ValueError as e:
            self.fail(f"register_read_tools raised on a fresh FastMCP instance: {e}")

    def test_all_read_tools_registered(self):
        mcp, _ = _build()
        names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {
            "list_agents", "get_agent", "get_agent_status",
            "list_messages", "get_message_thread",
            "list_tasks", "get_task", "get_task_history",
            "list_documents", "get_document", "search_documents",
            "list_secrets", "search_knowledge",
            "list_projects", "get_project", "list_project_items",
        }
        self.assertEqual(names, expected)


class ApiPrefix(unittest.TestCase):
    """Regression: every tool/resource must hit /api/... — earlier all 18
    call sites (13 tools + 5 resources) called the bare path instead, which
    either 404'd or (for /agents, /documents, /messages, /tasks) hit the
    HTML dashboard route and got back a page, not JSON."""

    def test_list_agents(self):
        mcp, client = _build()
        _tool(mcp, "list_agents")()
        self.assertEqual(client.calls, ["/api/agents"])

    def test_get_agent(self):
        mcp, client = _build()
        _tool(mcp, "get_agent")(name="SLK")
        self.assertEqual(client.calls, ["/api/agents/SLK"])

    def test_get_agent_status(self):
        mcp, client = _build({"status": "online"})
        _tool(mcp, "get_agent_status")(name="SLK")
        self.assertEqual(client.calls, ["/api/agents/SLK"])

    def test_get_task(self):
        mcp, client = _build()
        _tool(mcp, "get_task")(task_id="abc-123")
        self.assertEqual(client.calls, ["/api/tasks/abc-123"])

    def test_get_task_history(self):
        mcp, client = _build()
        _tool(mcp, "get_task_history")(task_id="abc-123", limit=10)
        self.assertEqual(client.calls, ["/api/tasks/abc-123/history?limit=10"])

    def test_get_document(self):
        mcp, client = _build()
        _tool(mcp, "get_document")(doc_id="42")
        self.assertEqual(client.calls, ["/api/documents/42"])

    def test_list_secrets(self):
        mcp, client = _build()
        _tool(mcp, "list_secrets")()
        self.assertEqual(client.calls, ["/api/vault/secrets"])


class QueryStringEncoding(unittest.TestCase):
    """Regression: values must be percent-encoded, not raw-concatenated."""

    def test_list_messages_encodes_ampersand_in_to(self):
        mcp, client = _build()
        _tool(mcp, "list_messages")(to="SLK & co", since=None, limit=10)
        self.assertEqual(client.calls, ["/api/messages?to=SLK+%26+co&limit=10"])

    def test_list_messages_unread_and_status_filters(self):
        mcp, client = _build()
        _tool(mcp, "list_messages")(to="SLK", limit=5, unread=True, status="pending")
        self.assertEqual(client.calls, ["/api/messages?to=SLK&limit=5&status=pending&unread=true"])

    def test_list_messages_includes_since_when_present(self):
        mcp, client = _build()
        _tool(mcp, "list_messages")(to="SLK", since="2026-07-01T00:00:00Z", limit=5)
        self.assertEqual(
            client.calls,
            ["/api/messages?to=SLK&limit=5&since=2026-07-01T00%3A00%3A00Z"],
        )

    def test_get_message_thread_encodes_topic(self):
        mcp, client = _build()
        _tool(mcp, "get_message_thread")(agent="SLK", topic="q&a #1")
        self.assertEqual(client.calls, ["/api/messages?agent=SLK&topic=q%26a+%231"])

    def test_list_tasks_encodes_status_and_assigned_to(self):
        mcp, client = _build()
        _tool(mcp, "list_tasks")(status="pending&done", assigned_to="SLK", limit=50)
        self.assertEqual(
            client.calls,
            ["/api/tasks?limit=50&status=pending%26done&assigned_to=SLK"],
        )

    def test_search_documents_encodes_query(self):
        mcp, client = _build()
        _tool(mcp, "search_documents")(query="foo & bar", limit=10)
        self.assertEqual(client.calls, ["/api/documents?q=foo+%26+bar&limit=10"])

    def test_search_knowledge_encodes_query_and_caps_n(self):
        mcp, client = _build()
        _tool(mcp, "search_knowledge")(query="a/b#c", n=999)
        self.assertEqual(client.calls, ["/api/knowledge?q=a%2Fb%23c&n=50"])

    def test_list_documents_omits_query_when_archived_not_given(self):
        mcp, client = _build()
        _tool(mcp, "list_documents")(archived=None)
        self.assertEqual(client.calls, ["/api/documents"])


class Resources(unittest.TestCase):
    def test_resource_task_template_resolves(self):
        mcp, client = _build({"type": "cron", "status": "done"})

        async def run():
            r = await mcp._resource_manager.get_resource("imua://tasks/abc-123")
            return await r.read()

        content = asyncio.run(run())
        self.assertIn("Task: abc-123", content)
        self.assertIn("Type: cron", content)
        self.assertEqual(client.calls, ["/api/tasks/abc-123"])

    def test_resource_knowledge_search_encodes_query(self):
        mcp, client = _build({"hits": []})

        async def run():
            r = await mcp._resource_manager.get_resource("imua://knowledge/foo bar")
            return await r.read()

        content = asyncio.run(run())
        self.assertIn("No results for: foo bar", content)
        self.assertEqual(client.calls, ["/api/knowledge?q=foo+bar&n=5"])

    def test_resource_knowledge_search_renders_real_hits(self):
        """Regression: GET /api/knowledge returns {"count": N, "hits": [...]},
        not {"data": [...]} — reading the wrong key silently swallowed every
        real result and always printed "no results", even for a hit."""
        mcp, client = _build({
            "count": 1,
            "hits": [{"title": "Deploy procedure", "tags": ["ops"], "agent": "CLD"}],
        })

        async def run():
            r = await mcp._resource_manager.get_resource("imua://knowledge/deploy")
            return await r.read()

        content = asyncio.run(run())
        self.assertIn("Deploy procedure", content)
        self.assertNotIn("No results", content)

    def test_resource_document_hits_api_prefix(self):
        mcp, client = _build({"name": "notes.md"})

        async def run():
            r = await mcp._resource_manager.get_resource("imua://documents/42")
            return await r.read()

        asyncio.run(run())
        self.assertEqual(client.calls, ["/api/documents/42"])

    def test_resource_agent_hits_api_prefix(self):
        mcp, client = _build({"status": "online"})

        async def run():
            r = await mcp._resource_manager.get_resource("imua://agents/SLK")
            return await r.read()

        asyncio.run(run())
        self.assertEqual(client.calls, ["/api/agents/SLK"])

    def test_resource_self(self):
        mcp, client = _build({"status": "online", "capabilities": ["read"]})

        async def run():
            r = await mcp._resource_manager.get_resource("imua://self")
            return await r.read()

        content = asyncio.run(run())
        self.assertIn("Agent: TEST", content)
        self.assertIn("Status: online", content)
        self.assertEqual(client.calls, ["/api/agents/TEST"])


if __name__ == "__main__":
    unittest.main()


class Projects(unittest.TestCase):
    """Task 6.9: project read tools hit the right hub paths, with values encoded."""

    def test_list_projects(self):
        mcp, client = _build({"projects": []})
        _tool(mcp, "list_projects")()
        _tool(mcp, "list_projects")(status="archived")
        self.assertEqual(client.calls, ["/api/projects", "/api/projects?status=archived"])

    def test_get_project_encodes_slug(self):
        mcp, client = _build({})
        _tool(mcp, "get_project")(slug="lead-gen/../x")
        self.assertEqual(client.calls, ["/api/projects/lead-gen%2F..%2Fx"])

    def test_list_project_items(self):
        mcp, client = _build({"items": []})
        result = _tool(mcp, "list_project_items")(slug="lead-gen", type="task")
        self.assertEqual(client.calls, ["/api/projects/lead-gen/items?type=task"])
        self.assertTrue(result["ok"])

    def test_search_knowledge_project_filter(self):
        mcp, client = _build()
        _tool(mcp, "search_knowledge")(query="pricing", project="lead-gen")
        _tool(mcp, "search_knowledge")(query="pricing")
        self.assertEqual(client.calls, ["/api/knowledge?q=pricing&n=10&project=lead-gen",
                                        "/api/knowledge?q=pricing&n=10"])
