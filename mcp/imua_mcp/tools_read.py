"""Read-only MCP tools and resources for the Imua hub.

PR1b: 13 read tools + 5 read-only resources. No writes, no mutations.
All tools are stateless; each call re-reads from the live hub (per spec §4).

Tool categories:
  - Agent registry (list, get, status)
  - Messages (list, get thread)
  - Tasks (list, get, history)
  - Documents (list, get, search)
  - Secrets (list names only, never values)
  - Knowledge (search, get, recent, stats)

Resources (read-only):
  - imua://self — agent identity
  - imua://agents/<name> — agent state
  - imua://tasks/<id> — task detail
  - imua://documents/<id> — document content
  - imua://knowledge/<query> — search results
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

import httpx

from imua_mcp.client import ImuaClient, ImuaClientError


def register_read_tools(mcp, token_file, client: ImuaClient, agent_name: str) -> None:
    """Register all read-only tools and resources on the FastMCP instance.

    Called during server startup after bootstrap, before stdio loop.
    """

    # ---- Tools ----

    @mcp.tool()
    def list_agents() -> dict[str, Any]:
        """List all registered agents with their status (online/offline)."""
        try:
            result = client.get("/api/agents")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_agent(name: str) -> dict[str, Any]:
        """Get a single agent's detail (status, capabilities, host, last_heartbeat)."""
        try:
            result = client.get(f"/api/agents/{name}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_agent_status(name: str) -> dict[str, Any]:
        """Check if an agent is currently online (based on heartbeat timeout)."""
        try:
            agent = client.get(f"/api/agents/{name}")
            status = agent.get("status", "unknown")
            return {"ok": True, "data": {"name": name, "status": status}}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def list_messages(to: str, since: str | None = None, limit: int = 50,
                      unread: bool = False, status: str | None = None) -> dict[str, Any]:
        """List messages for an agent, newest first.

        Args:
            to: Agent name whose inbox to list.
            since: Only messages after this ISO timestamp.
            limit: Max messages returned (filters apply before the limit).
            unread: Only messages not yet marked read. Use this to poll for new work,
                then call mark_messages_read on the ids you handled.
            status: Exact status filter: pending, delivered or read.
        """
        try:
            params: dict[str, Any] = {"to": to, "limit": limit}
            if since:
                params["since"] = since
            if status:
                params["status"] = status
            if unread:
                params["unread"] = "true"
            result = client.get(f"/api/messages?{urlencode(params)}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_message_thread(agent: str, topic: str | None = None) -> dict[str, Any]:
        """Get a message thread for an agent, optionally filtered by topic.

        Note: the hub's GET /api/messages has no topic filter today — `topic`
        is sent but silently ignored server-side. Kept for forward-compat if
        the hub adds it; this currently just returns all messages for `agent`.
        """
        try:
            params: dict[str, Any] = {"agent": agent}
            if topic:
                params["topic"] = topic
            result = client.get(f"/api/messages?{urlencode(params)}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def list_tasks(
        status: str | None = None,
        assigned_to: str | None = None,
        limit: int = 50
    ) -> dict[str, Any]:
        """List tasks. Filter by status (pending/claimed/done), assigned_to agent."""
        try:
            params: dict[str, Any] = {"limit": limit}
            if status:
                params["status"] = status
            if assigned_to:
                params["assigned_to"] = assigned_to
            result = client.get(f"/api/tasks?{urlencode(params)}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_task(task_id: str) -> dict[str, Any]:
        """Get a single task's full detail."""
        try:
            result = client.get(f"/api/tasks/{task_id}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_task_history(task_id: str, limit: int = 50) -> dict[str, Any]:
        """Get execution history for a task (retries, status changes).

        NOTE: the hub has no GET /api/tasks/<id>/history route today (only
        /api/cron/<id>/history exists) — this always returns a clean
        {"ok": false, "error": "not_found"} until that endpoint is added
        hub-side. Kept registered (matches the spec's 13-tool surface)
        rather than removed, since the failure is well-formed, not a crash.
        """
        try:
            result = client.get(f"/api/tasks/{task_id}/history?{urlencode({'limit': limit})}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def list_documents(archived: bool | None = None) -> dict[str, Any]:
        """List documents. If archived=true, only archived; omitted returns all."""
        try:
            qs = f"?{urlencode({'archived': 'true' if archived else 'false'})}" if archived is not None else ""
            result = client.get(f"/api/documents{qs}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_document(doc_id: str) -> dict[str, Any]:
        """Get a document's metadata (name, upload_date, size, etc.).

        NOTE: the hub has no bare GET /api/documents/<id> route today (only
        /download, /archive, /unarchive exist per-document) — this always
        returns a clean {"ok": false, "error": "not_found"} until that
        endpoint is added hub-side.
        """
        try:
            result = client.get(f"/api/documents/{doc_id}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def search_documents(query: str, limit: int = 10) -> dict[str, Any]:
        """Search documents by name/metadata (not full-text body).

        NOTE: the hub's GET /api/documents only supports an `archived`
        filter today — `q` and `limit` are sent but silently ignored
        server-side, so this currently returns the same full list as
        list_documents(archived=None) regardless of `query`.
        """
        try:
            result = client.get(f"/api/documents?{urlencode({'q': query, 'limit': limit})}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def list_secrets() -> dict[str, Any]:
        """List secret names and descriptions. Values are NEVER returned."""
        try:
            result = client.get("/api/vault/secrets")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def search_knowledge(query: str, n: int = 10, project: str | None = None) -> dict[str, Any]:
        """Semantic search over the knowledge base. Returns top N results by similarity.

        Args:
            query: What to search for (meaning, not exact words).
            n: Max results (capped at 50).
            project: Optional project slug: only that project's entries.
        """
        try:
            n = min(n, 50)  # cap at 50 per spec
            params = {"q": query, "n": n}
            if project:
                params["project"] = project
            result = client.get(f"/api/knowledge?{urlencode(params)}")
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    # ---- Projects (task 6.9, docs/imua_projects_plan_v1.md §5.4) ----

    @mcp.tool()
    def list_projects(status: str | None = None) -> dict[str, Any]:
        """List projects with their member agents and item counts.

        Args:
            status: Optional filter: "active" or "archived".
        """
        try:
            query = f"?{urlencode({'status': status})}" if status else ""
            return {"ok": True, "data": client.get(f"/api/projects{query}")}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def get_project(slug: str) -> dict[str, Any]:
        """Get one project: name, description, status, member agents and item counts."""
        try:
            return {"ok": True, "data": client.get(f"/api/projects/{quote(slug, safe='')}")}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def list_project_items(slug: str, type: str) -> dict[str, Any]:
        """List a project's items of one type.

        Args:
            slug: The project's slug (from list_projects).
            type: One of task, document, cron, knowledge.
        """
        try:
            path = f"/api/projects/{quote(slug, safe='')}/items?{urlencode({'type': type})}"
            return {"ok": True, "data": client.get(path)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    # ---- Resources ----

    @mcp.resource("imua://self")
    def resource_self() -> str:
        """Agent identity (imua://self). Contains agent name, token identity, etc."""
        try:
            agent = client.get(f"/api/agents/{agent_name}")
            return f"Agent: {agent_name}\nStatus: {agent.get('status', 'unknown')}\nCapabilities: {agent.get('capabilities', [])}"
        except ImuaClientError as e:
            return f"Error reading imua://self: {e.message}"

    @mcp.resource("imua://agents/{name}")
    def resource_agent(name: str) -> str:
        """Agent detail resource (imua://agents/<name>)."""
        try:
            agent = client.get(f"/api/agents/{name}")
            lines = [
                f"Agent: {name}",
                f"Status: {agent.get('status', 'unknown')}",
                f"Capabilities: {agent.get('capabilities', [])}",
                f"Last heartbeat: {agent.get('last_heartbeat', 'never')}",
                f"Created: {agent.get('created_at', 'unknown')}",
            ]
            return "\n".join(lines)
        except ImuaClientError as e:
            return f"Error reading imua://agents/{name}: {e.message}"

    @mcp.resource("imua://tasks/{task_id}")
    def resource_task(task_id: str) -> str:
        """Task detail resource (imua://tasks/<id>)."""
        try:
            task = client.get(f"/api/tasks/{task_id}")
            lines = [
                f"Task: {task_id}",
                f"Type: {task.get('type', 'unknown')}",
                f"Status: {task.get('status', 'unknown')}",
                f"Assigned to: {task.get('assigned_to', 'unassigned')}",
                f"Priority: {task.get('priority', 0)}",
                f"Created: {task.get('created_at', 'unknown')}",
                f"Result: {task.get('result', 'none')}",
            ]
            return "\n".join(lines)
        except ImuaClientError as e:
            return f"Error reading imua://tasks/{task_id}: {e.message}"

    @mcp.resource("imua://documents/{doc_id}")
    def resource_document(doc_id: str) -> str:
        """Document content resource (imua://documents/<id>). For text docs, returns body.

        NOTE: same as get_document — the hub has no bare
        GET /api/documents/<id> route, so this currently always errors.
        """
        try:
            doc = client.get(f"/api/documents/{doc_id}")
            lines = [
                f"Document: {doc_id}",
                f"Name: {doc.get('name', 'unknown')}",
                f"Uploaded: {doc.get('uploaded_at', 'unknown')}",
                f"Size: {doc.get('size', 0)} bytes",
                f"Type: {doc.get('mime_type', 'unknown')}",
            ]
            if doc.get("body"):
                lines.append("")
                lines.append("--- Content ---")
                lines.append(doc["body"][:1000])  # cap at 1000 chars for display
            return "\n".join(lines)
        except ImuaClientError as e:
            return f"Error reading imua://documents/{doc_id}: {e.message}"

    @mcp.resource("imua://knowledge/{query}")
    def resource_knowledge_search(query: str) -> str:
        """Knowledge search resource (imua://knowledge/<query>). Returns top results."""
        try:
            results = client.get(f"/api/knowledge?{urlencode({'q': query, 'n': 5})}")
            lines = [f"Knowledge search: {query}", ""]
            # GET /api/knowledge returns {"count": N, "hits": [...]}, not "data" —
            # this used to always report "no results" regardless of real hits.
            for i, entry in enumerate(results.get("hits", []), 1):
                lines.append(f"{i}. {entry.get('title', 'Untitled')}")
                lines.append(f"   Tags: {entry.get('tags', [])}")
                lines.append(f"   By: {entry.get('agent', 'unknown')}")
                lines.append("")
            return "\n".join(lines) if len(lines) > 2 else f"No results for: {query}"
        except ImuaClientError as e:
            return f"Error searching imua://knowledge: {e.message}"
