"""Tests for imua_mcp.server.main() — the bootstrap glue code.

This path was never actually exercised end-to-end before (register_read_tools
and the individual client/auth units were tested in isolation, but main()
itself was not) and had three separate bugs that made it impossible to
start the server at all, on any platform:

1. `except TokenFileError as e: print(e.message)` — TokenFileError has no
   `.message` attribute, so a bad token file crashed with AttributeError
   instead of printing a clean diagnostic.
2. The startup health check called GET /health, but the hub only serves
   GET /api/health — the check 404'd unconditionally.
3. `ImuaClient(..., token=token_file.token, ...)` — TokenFile has no
   `.token` attribute, only `.read()`. This alone meant main() raised
   AttributeError on every single invocation, valid token or not.
"""

import sys
import tempfile
import unittest
from unittest.mock import patch

from imua_mcp import server
from imua_mcp.client import ImuaClient


VALID_TOKEN = "a" * 32 + "b" * 32


class BadTokenFile(unittest.TestCase):
    def test_missing_token_file_prints_clean_error_not_attributeerror(self):
        argv = [
            "imua-mcp",
            "--agent-name", "TEST",
            "--hub-url", "http://example.invalid:1",
            "--token-file", "/does/not/exist.token",
        ]
        with patch.object(sys, "argv", argv):
            with patch("sys.stderr") as mock_stderr:
                rc = server.main()
        self.assertEqual(rc, 1)
        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list if c.args)
        self.assertIn("ERROR", written)
        self.assertNotIn("AttributeError", written)


class HealthCheckPath(unittest.TestCase):
    def test_startup_health_check_hits_api_health(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name

        argv = [
            "imua-mcp",
            "--agent-name", "TEST",
            "--hub-url", "http://example.invalid:1",
            "--token-file", path,
        ]
        calls = []

        def fake_get(self, req_path):
            calls.append(req_path)
            return {"status": "ok", "version": "1.1.0"}

        with patch.object(sys, "argv", argv):
            with patch.object(ImuaClient, "get", fake_get):
                with patch("mcp.server.fastmcp.FastMCP.run"):
                    rc = server.main()

        self.assertEqual(rc, 0)
        self.assertIn("/api/health", calls)
        self.assertNotIn("/health", calls)


if __name__ == "__main__":
    unittest.main()
