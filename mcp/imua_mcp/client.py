"""Thin httpx client for the Imua REST API.

Maps HTTP and network errors to a stable envelope (per spec §3.3):

    Success:  {"ok": true,  "data": <response_body>}
    Failure:  {"ok": false, "error": "<type>", "message": "...", "status": <http_code>}

Error types (stable string enum):
    unauthorized     (401)
    forbidden        (403)
    not_found        (404)
    conflict         (409)
    validation_error (422, plus other 4xx)
    internal_error   (5xx)
    hub_unreachable  (network)
    hub_timeout      (network — exceeded --timeout)

The client never echoes the bearer token in error messages or request URLs.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx


# Defensive: any 64-char hex substring (optionally preceded by "Bearer ") is
# almost certainly a leaked token. Imua tokens are 64 lowercase hex chars per
# secrets.token_hex(32); we match 64+ hex to be safe across encodings.
_LEAK_RE = re.compile(r"(?:Bearer\s+)?[a-fA-F0-9]{64}\b", re.IGNORECASE)

# Cap hub-supplied message length to bound what reaches the LLM
_MAX_MESSAGE_LEN = 200


class ImuaClientError(Exception):
    """Stable-shape error envelope. Fields: type (str), message (str), status (int|None)."""

    def __init__(self, error_type: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.type = error_type
        self.message = message
        self.status = status


class ImuaClient:
    """Stateless httpx client for the Imua hub.

    One instance per MCP server process. The bearer token is held in
    private state and is never logged, never echoed in error messages,
    and never included in any property that gets inspected externally.
    """

    _ERROR_TYPE_BY_STATUS: dict[int, str] = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
    }

    def __init__(self, base_url: str, token, timeout: float = 30.0) -> None:
        """token: the bearer token, or a callable returning it (e.g. TokenFile.read),
        so a rotated token file is picked up on the next request without a restart."""
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def use_token(self, token: str) -> None:
        """Pin this token in memory (rotate_token's fallback when the file can't be written)."""
        self._token = token

    def _headers(self) -> dict[str, str]:
        # Authorization header is set per-request inside _request to keep
        # the secret out of any shared state.
        return {
            "Authorization": f"Bearer {self._token() if callable(self._token) else self._token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = self._headers()
        data = json.dumps(body).encode() if body is not None else None
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(method, url, headers=headers, content=data)
        except httpx.TimeoutException:
            raise ImuaClientError(
                "hub_timeout",
                f"hub did not respond within {self._timeout}s",
            )
        except httpx.ConnectError:
            raise ImuaClientError(
                "hub_unreachable",
                f"could not connect to hub at {self._base_url}",
            )
        except httpx.HTTPError as e:
            # Catch-all for other httpx errors (read/write failures, etc.)
            raise ImuaClientError(
                "hub_unreachable",
                f"network error talking to hub: {type(e).__name__}",
            )
        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        # 2xx — success path
        if 200 <= response.status_code < 300:
            if not response.content:
                return {}
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"raw": response.text}
        # 5xx — internal error
        if response.status_code >= 500:
            raise ImuaClientError(
                "internal_error",
                f"hub returned {response.status_code}",
                status=response.status_code,
            )
        # 4xx — map to known types, defaulting to validation_error
        error_type = self._ERROR_TYPE_BY_STATUS.get(
            response.status_code, "validation_error"
        )
        hub_msg = self._extract_hub_message(response)
        raise ImuaClientError(
            error_type,
            hub_msg or f"hub returned {response.status_code}",
            status=response.status_code,
        )

    @staticmethod
    def _extract_hub_message(response: httpx.Response) -> str:
        """Pull a human-readable message from a hub error response.

        Defensive filters applied before returning:
          1. Strip any "Bearer <hex>" or raw 64-char hex substrings (likely a
             leaked token — Imua tokens are 64 hex chars).
          2. Cap length at _MAX_MESSAGE_LEN to bound what reaches the LLM.
        """
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return ""
        if not isinstance(body, dict):
            return ""
        msg = body.get("message") or body.get("error") or ""
        if not isinstance(msg, str):
            msg = str(msg)
        # Strip token-shaped substrings (substitute with [REDACTED] so context
        # like "Authorization:" remains visible but the secret is removed)
        msg = _LEAK_RE.sub("[REDACTED]", msg)
        # Cap length
        if len(msg) > _MAX_MESSAGE_LEN:
            msg = msg[:_MAX_MESSAGE_LEN] + "..."
        return msg

    # ---- High-level methods (PR1b will add tool wrappers around these) ----

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", path, body=body)

    def patch(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("PATCH", path, body=body)

    def delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    def __repr__(self) -> str:
        return f"ImuaClient(base_url={self._base_url}, timeout={self._timeout})"
