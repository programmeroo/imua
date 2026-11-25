"""Tests for imua_mcp.client.ImuaClient.

Per spec §8.1, must cover:
- HTTP status -> error type mapping (401/403/404/409/422/5xx)
- Network errors -> hub_unreachable / hub_timeout
- Success path returns parsed JSON
- Token never appears in error messages
- Timeout respects --timeout flag
"""

import json
import unittest

import httpx

from imua_mcp.client import ImuaClient, ImuaClientError


# Use httpx MockTransport so we don't touch the real network.
# Test setup is in-memory; no live hub needed for PR1a.


def _mock_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    if json_body is not None:
        return httpx.Response(status_code, json=json_body)
    return httpx.Response(status_code, text=text)


class _MockClient(ImuaClient):
    """Subclass that injects a mock transport so we don't hit the network."""

    def __init__(self, transport: httpx.MockTransport, timeout: float = 30.0) -> None:
        # Skip parent __init__ to avoid storing a token we won't use
        self._base_url = "http://mock.test"
        self._token = "test-token-NEVER-LEAK"
        self._timeout = timeout
        self._transport = transport

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode() if body is not None else None
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
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
            raise ImuaClientError(
                "hub_unreachable",
                f"network error talking to hub: {type(e).__name__}",
            )
        return self._parse_response(response)


class SuccessPath(unittest.TestCase):
    def test_200_with_json_body(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "agents": ["SLK"]})
        client = _MockClient(httpx.MockTransport(handler))
        result = client.get("/api/agents")
        self.assertEqual(result, {"ok": True, "agents": ["SLK"]})

    def test_200_empty_body(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(204)
        client = _MockClient(httpx.MockTransport(handler))
        result = client.patch("/api/agents/SLK/heartbeat")
        self.assertEqual(result, {})


class ErrorStatusMapping(unittest.TestCase):
    def test_401_unauthorized(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized", "message": "token expired"})
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents/SLK")
        self.assertEqual(ctx.exception.type, "unauthorized")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("token expired", ctx.exception.message)

    def test_403_forbidden(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "forbidden", "message": "wrong agent"})
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.patch("/api/agents/SLK/heartbeat")
        self.assertEqual(ctx.exception.type, "forbidden")

    def test_404_not_found(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not_found", "message": "no such agent"})
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents/NOPE")
        self.assertEqual(ctx.exception.type, "not_found")

    def test_409_conflict(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"error": "conflict", "message": "duplicate"})
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.post("/api/agents/register", {"name": "SLK"})
        self.assertEqual(ctx.exception.type, "conflict")

    def test_422_validation_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"error": "validation_error", "message": "name required"})
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.post("/api/agents/register", {})
        self.assertEqual(ctx.exception.type, "validation_error")

    def test_500_internal_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents")
        self.assertEqual(ctx.exception.type, "internal_error")
        self.assertEqual(ctx.exception.status, 500)


class NetworkErrors(unittest.TestCase):
    def test_connection_refused_maps_to_hub_unreachable(self):
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=req)
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents")
        self.assertEqual(ctx.exception.type, "hub_unreachable")

    def test_timeout_maps_to_hub_timeout(self):
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("read timed out", request=req)
        client = _MockClient(httpx.MockTransport(handler), timeout=0.001)
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents")
        self.assertEqual(ctx.exception.type, "hub_timeout")


class NoTokenLeak(unittest.TestCase):
    def test_repr_does_not_leak_token(self):
        client = ImuaClient(base_url="http://mock.test", token="secret-1234", timeout=30.0)
        rep = repr(client)
        self.assertIn("http://mock.test", rep)
        self.assertNotIn("secret-1234", rep)

    def test_extract_message_drops_token_like_blobs(self):
        """Defensive: if the hub echoes a token-shaped string in a message, drop it."""
        long_msg = ("Authorization: Bearer " + "a" * 64)  # contains "token"-ish word + >50 chars
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": "unauthorized", "message": long_msg},
            )
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents")
        # The token-shaped substring was dropped — error message is empty
        self.assertNotIn("a" * 64, ctx.exception.message)
        self.assertNotIn("Bearer", ctx.exception.message)

    def test_extract_message_keeps_short_safe_text(self):
        """Short, non-token messages pass through unchanged."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": "unauthorized", "message": "token expired"},
            )
        client = _MockClient(httpx.MockTransport(handler))
        with self.assertRaises(ImuaClientError) as ctx:
            client.get("/api/agents")
        # Short, safe text preserved
        self.assertEqual(ctx.exception.message, "token expired")


if __name__ == "__main__":
    unittest.main()


class TokenProvider(unittest.TestCase):
    """Task 6.11d: the client can follow the token file (callable token) and be pinned."""

    def test_callable_token_is_read_per_request(self):
        from imua_mcp.client import ImuaClient
        current = {"t": "a" * 64}
        client = ImuaClient("http://hub", token=lambda: current["t"])
        self.assertEqual(client._headers()["Authorization"], "Bearer " + "a" * 64)
        current["t"] = "b" * 64
        self.assertEqual(client._headers()["Authorization"], "Bearer " + "b" * 64)

    def test_use_token_pins(self):
        from imua_mcp.client import ImuaClient
        client = ImuaClient("http://hub", token=lambda: "a" * 64)
        client.use_token("c" * 64)
        self.assertEqual(client._headers()["Authorization"], "Bearer " + "c" * 64)
