"""Hermes SDK — Python client for the Imua hub API.

Lets any agent register, heartbeat, message other agents, and use the
secrets vault without writing raw HTTP calls.
"""

import json
import urllib.error
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ImuaError(Exception):
    """Raised when the Imua hub returns a non-2xx response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ImuaClient:
    """Client for an agent to talk to the Imua hub."""

    def __init__(self, base_url: str = "http://localhost:47280", name: str | None = None, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.token = token

    def register(self, name: str, capabilities: list[str] | None = None, host: str = "", port: int = 0) -> str:
        """POST /api/agents/register → returns agent token."""
        body = {
            "name": name,
            "capabilities": capabilities or [],
            "host": host,
            "port": port,
        }
        data = self._request("POST", "/api/agents/register", body=body)
        self.name = name
        self.token = data["token"]
        return self.token

    def heartbeat(self) -> dict:
        """PATCH /api/agents/<name>/heartbeat → returns server time."""
        return self._request("PATCH", f"/api/agents/{self.name}/heartbeat")

    def send_message(self, recipient: str, body: str, topic: str = "", msg_type: str = "direct") -> int:
        """POST /api/messages → returns message id."""
        data = self._request(
            "POST",
            "/api/messages",
            body={
                "from": self.name,
                "to": recipient,
                "type": msg_type,
                "body": body,
                "topic": topic,
            },
        )
        return data["id"]

    def check_messages(self, limit: int = 10, unread: bool = False) -> list:
        """GET /api/messages → this agent's messages, newest first.
        unread=True returns only messages not yet marked read (see mark_read)."""
        params = {"to": self.name, "limit": limit}
        if unread:
            params["unread"] = "true"
        data = self._request("GET", f"/api/messages?{urlencode(params)}")
        return data["messages"]

    def mark_read(self, ids: int | list[int]) -> dict:
        """POST /api/messages/read → {"marked": [...], "skipped": [...]}.
        Only this agent's own messages can be marked; others land in "skipped"."""
        ids = [ids] if isinstance(ids, int) else list(ids)
        return self._request("POST", "/api/messages/read", body={"ids": ids})

    def store_secret(self, name: str, value: str) -> dict:
        """POST /api/vault/secrets → stores encrypted secret."""
        return self._request("POST", "/api/vault/secrets", body={"name": name, "value": value})

    def get_secret(self, name: str) -> str:
        """GET /api/vault/secrets/<name> → returns decrypted value."""
        data = self._request("GET", f"/api/vault/secrets/{name}")
        return data["value"]

    # --- Projects (task 6.9). A project groups tasks, documents, knowledge and cron jobs. ---

    def list_projects(self, status: str | None = None) -> list:
        """GET /api/projects → projects with member agents and item counts.
        status: optional "active" or "archived"."""
        query = f"?{urlencode({'status': status})}" if status else ""
        return self._request("GET", f"/api/projects{query}")["projects"]

    def get_project(self, slug: str) -> dict:
        """GET /api/projects/<slug> → name, description, status, agents, counts."""
        return self._request("GET", f"/api/projects/{quote(slug, safe='')}")

    def list_project_items(self, slug: str, item_type: str) -> list:
        """GET /api/projects/<slug>/items → the project's items of one type
        (task, document, cron or knowledge)."""
        path = f"/api/projects/{quote(slug, safe='')}/items?{urlencode({'type': item_type})}"
        return self._request("GET", path)["items"]

    def _request(self, method: str, path: str, body: dict | None = None, extra_headers: dict | None = None) -> dict:
        """Single HTTP helper — JSON in, JSON out. Raises ImuaError on non-2xx."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update(extra_headers)

        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise ImuaError(f"{method} {path} failed: {e.code} {detail}", status_code=e.code) from e

        return json.loads(raw) if raw else {}
