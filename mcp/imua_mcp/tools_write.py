"""Write MCP tools for the Imua hub: messaging (PR2a), tasks (6.11a), knowledge and cron (6.11b), issues (6.11c),
vault and token rotation (6.11d).

Mirrors the error-envelope and registration pattern from tools_read.py:

    Success:  {"ok": true,  "data": <response_body>}
    Failure:  {"ok": false, "error": "<type>", "message": "...", "status": <http_code>}

Sender identity is never agent-supplied. The hub derives `from` from the
bearer token (see app/routes/messages.py `send()` — "Sender identity comes
from the authenticated token, not the request body"), so there is no `from`
parameter here to keep the tool's contract honest with what the hub actually
does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from imua_mcp.client import ImuaClient, ImuaClientError


def register_write_tools(mcp, token_file, client: ImuaClient, agent_name: str) -> None:
    """Register write (mutating) tools on the FastMCP instance.

    Called during server startup, after register_read_tools.
    """

    @mcp.tool()
    def send_message(
        to: str,
        body: str,
        type: str = "chat",
        topic: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to one or more agents via the Imua hub.

        Sender is always this agent's own identity (derived from its bearer
        token by the hub) — it cannot be spoofed via arguments.

        Args:
            to: Recipient agent name, comma-separated names ("SVY,SLK"), or
                "all" to broadcast to every registered agent.
            body: Free-text message content.
            type: One of chat, request, response, broadcast, error, status.
                Use "request" for task delegation. Default: chat.
            topic: Optional topic string to group a message thread.
        """
        try:
            payload: dict[str, Any] = {"to": to, "type": type, "body": body}
            if topic:
                payload["topic"] = topic
            result = client.post("/api/messages", body=payload)
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def mark_messages_read(ids: list[int]) -> dict[str, Any]:
        """Mark messages read after handling them (standing rule).

        Only this agent's own messages can be marked — for a broadcast, only its own
        copy. Ids that don't exist or aren't this agent's come back under "skipped"
        (expected, not an error). Marking twice is harmless.

        Args:
            ids: Message ids to mark read (1-500), e.g. from list_messages(unread=True).
        """
        try:
            result = client.post("/api/messages/read", body={"ids": ids})
            return {"ok": True, "data": result}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    # ---- Tasks (task 6.11a) ----

    @mcp.tool()
    def create_task(
        type: str,
        title: str = "",
        priority: int = 3,
        assigned_to: str | None = None,
        project: str | None = None,
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a task in the hub's task queue. created_by is this agent.

        Args:
            type: What kind of work, e.g. "build", "code.review". Used to route the
                task to an agent whose capabilities match, unless assigned_to is given.
            title: Short human-readable description.
            priority: 1 (urgent) to 5 (low). Default 3.
            assigned_to: Give it to this agent directly instead of auto-routing.
            project: Optional project slug (from list_projects) to put the task in.
            params, context: Free-form JSON for the agent that does the work.
            tags: Optional labels.
        """
        body: dict[str, Any] = {"type": type, "title": title, "priority": priority}
        for key, value in (("assigned_to", assigned_to), ("project", project), ("params", params),
                           ("context", context), ("tags", tags)):
            if value is not None:
                body[key] = value
        try:
            return {"ok": True, "data": client.post("/api/tasks", body=body)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def claim_task(capabilities: list[str]) -> dict[str, Any]:
        """Claim the highest-priority pending, unassigned task this agent can do.

        The hub matches the task's type against the capabilities given. Returns
        {"task": {...}} with the task now in_progress and assigned to this agent,
        or {"task": null} when nothing matches.

        Args:
            capabilities: What this agent can do, e.g. ["build", "python"].
        """
        try:
            return {"ok": True, "data": client.post("/api/tasks/claim", body={"capabilities": capabilities})}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def complete_task(task_id: int, result: str | None = None, failed: bool = False) -> dict[str, Any]:
        """Finish a task: mark it completed (or failed) with an optional result.

        Marking it failed lets the hub retry it later (up to its max_retries).

        Args:
            task_id: The task's id (from create_task, claim_task or list_tasks).
            result: What was done, or why it failed.
            failed: True if the work did not succeed.
        """
        body: dict[str, Any] = {"status": "failed" if failed else "completed"}
        if result is not None:
            body["result"] = result
        try:
            return {"ok": True, "data": client.patch(f"/api/tasks/{int(task_id)}", body=body)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    # ---- Knowledge and cron (task 6.11b) ----

    @mcp.tool()
    def add_knowledge(
        body: str,
        title: str = "",
        tags: list[str] | None = None,
        source: str = "manual",
        project: str | None = None,
    ) -> dict[str, Any]:
        """Add an entry to the shared knowledge base (searchable by meaning).

        The entry's agent is this agent (from its token).

        Args:
            body: The knowledge itself: a fact, decision, how-to or note.
            title: Short title.
            tags: Optional labels.
            source: Where it came from, e.g. "manual", "agent_log", "document".
            project: Optional project slug to put the entry in; search_knowledge
                can then be limited to that project.
        """
        payload: dict[str, Any] = {"body": body, "title": title, "source": source, "tags": tags or []}
        if project:
            payload["project"] = project
        try:
            return {"ok": True, "data": client.post("/api/knowledge", body=payload)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def create_cron_job(
        name: str,
        schedule: str,
        schedule_human: str = "",
        description: str = "",
        assigned_to: str | None = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        """Register a scheduled job with the hub.

        Args:
            name: Short name, e.g. "nightly lead sync".
            schedule: Cron expression, e.g. "0 2 * * *" (every day at 02:00).
            schedule_human: The same schedule in words, shown on the dashboard.
            description: What the job does.
            assigned_to: The agent that runs it.
            project: Optional project slug to put the job in.
        """
        payload: dict[str, Any] = {"name": name, "schedule": schedule, "schedule_human": schedule_human,
                                   "description": description}
        for key, value in (("assigned_to", assigned_to), ("project", project)):
            if value:
                payload[key] = value
        try:
            return {"ok": True, "data": client.post("/api/cron", body=payload)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    # ---- Issues (task 6.11c) ----

    @mcp.tool()
    def report_issue(
        type: str,
        subject: str,
        severity: str = "warning",
        detail: str = "",
        source: str | None = None,
    ) -> dict[str, Any]:
        """Report an operational problem to the hub's Issues page.

        Repeat reports of the same source + type + subject are merged into one open
        issue with a count, so it's safe to report the same thing again.

        Args:
            type: Short machine-style kind, e.g. "missing_api_endpoint", "broken_dependency".
            subject: One line saying what is wrong.
            severity: info, warning, error or critical. Default warning.
            detail: Evidence, steps, proposed fix.
            source: Where it comes from; defaults to this agent's name.
        """
        payload = {"source": source or agent_name.lower(), "type": type, "subject": subject,
                   "severity": severity, "detail": detail}
        try:
            return {"ok": True, "data": client.post("/api/issues", body=payload)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def update_issue_status(issue_id: int, action: str, resolution: str = "") -> dict[str, Any]:
        """Move an issue along: acknowledge it, suppress it, or resolve it.

        Args:
            issue_id: The issue's id (from the Issues page or GET /api/issues).
            action: "acknowledge" (seen, being handled), "suppress" (hide from counts)
                or "resolve" (fixed).
            resolution: For resolve: what fixed it.
        """
        if action not in ("acknowledge", "suppress", "resolve"):
            return {"ok": False, "error": "validation_error",
                    "message": "action must be acknowledge, suppress or resolve", "status": None}
        body = {"resolution": resolution} if action == "resolve" and resolution else {}
        try:
            return {"ok": True, "data": client.post(f"/api/issues/{int(issue_id)}/{action}", body=body)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    # ---- Vault and token rotation (task 6.11d) ----

    @mcp.tool()
    def get_secret(name: str) -> dict[str, Any]:
        """Read a secret's value from the vault (only secrets this agent may access).

        Use the value directly in the work that needs it. Never repeat it in a
        message, an issue, a knowledge entry, a task result or a reply.

        Args:
            name: The secret's name (see list_secrets).
        """
        try:
            data = client.get(f"/api/vault/secrets/{quote(name, safe='')}")
            return {"ok": True, "data": data}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def put_secret(name: str, value: str, description: str = "",
                   access_scope: list[str] | None = None) -> dict[str, Any]:
        """Store a new secret, encrypted, in the vault. Returns metadata, never the value.

        Names are unique: storing an existing name fails (conflict). Replacing a
        secret's value isn't supported yet.

        Args:
            name: Unique name, e.g. "openai_api_key".
            value: The secret.
            description: What it's for.
            access_scope: Agent names allowed to read it; empty means every agent.
        """
        body: dict[str, Any] = {"name": name, "value": value, "description": description}
        if access_scope:
            body["access_scope"] = access_scope
        try:
            return {"ok": True, "data": client.post("/api/vault/secrets", body=body)}
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}

    @mcp.tool()
    def rotate_token() -> dict[str, Any]:
        """Replace this agent's bearer token (e.g. after it may have leaked).

        The old token stops working at once. The new token is saved to this MCP
        server's token file and used immediately; it is never shown to you.
        Other processes still holding the OLD token (for example the agent's
        join.py heartbeat loop) will start failing and must be restarted.
        """
        try:
            new = client.patch(f"/api/agents/{quote(agent_name, safe='')}/token")["token"]
        except ImuaClientError as e:
            return {"ok": False, "error": e.type, "message": e.message, "status": e.status}
        except (KeyError, TypeError):
            return {"ok": False, "error": "bad_response", "message": "hub did not return a new token", "status": None}

        notes = [f"The vault copy '{agent_name}_token' (if any) still holds the OLD token; the vault can't "
                 "replace secrets yet.",
                 "Restart any other process using the old token (e.g. join.py's heartbeat)."]
        try:
            token_file.write(new)
            return {"ok": True, "data": {"rotated": True, "token_file_updated": True, "notes": notes}}
        except Exception:
            # The old token is already dead. Keep working on the new one, and leave a
            # recoverable copy in the vault under a fresh name.
            client.use_token(new)
            backup = f"{agent_name}_token_rotated_{datetime.utcnow():%Y%m%d%H%M%S}"
            try:
                client.post("/api/vault/secrets", body={"name": backup, "value": new,
                                                        "description": "rotate_token: token file write failed"})
                where = f"vault secret '{backup}'"
            except ImuaClientError:
                where = "this MCP server's memory only (vault backup also failed)"
            return {"ok": False, "error": "token_file_write_failed",
                    "message": f"Token rotated, but the token file could not be written. The new token is in "
                               f"{where}. This server keeps working until it restarts; fix the token file "
                               f"from that copy before then.", "status": None}
