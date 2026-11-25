"""
Unit tests for token rotation (task 1.10).

PATCH /api/agents/<name>/token — self-service rotation.
"""
import os
os.environ["IMUA_TESTING"] = "1"


import time
import unittest

from app.server import create_app


class TestTokenRotation(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        # Use a unique agent name per test run to avoid 409 across reruns.
        self.agent_name = f"rot-test-{int(time.time() * 1000)}"

    def _register(self, name):
        resp = self.client.post("/api/agents/register", json={
            "name": name,
            "role": "worker",
            "capabilities": ["test"],
        })
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
        return resp.get_json()["token"]

    def test_rotate_without_token_returns_401(self):
        resp = self.client.patch(f"/api/agents/{self.agent_name}/token")
        self.assertEqual(resp.status_code, 401)

    def test_rotate_with_other_agents_token_returns_403(self):
        # Register two agents
        token_a = self._register(self.agent_name)
        token_b = self._register(f"rot-other-{self.agent_name}")

        # Try to rotate A using B's token
        resp = self.client.patch(
            f"/api/agents/{self.agent_name}/token",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("forbidden", resp.get_json()["error"])

    def test_rotate_with_correct_token_returns_new_token(self):
        old_token = self._register(self.agent_name)

        resp = self.client.patch(
            f"/api/agents/{self.agent_name}/token",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["agent"], self.agent_name)
        self.assertIn("token", body)
        new_token = body["token"]
        # Sanity: new token is different from old
        self.assertNotEqual(new_token, old_token)
        self.assertGreaterEqual(len(new_token), 32)

    def test_old_token_invalid_after_rotation(self):
        old_token = self._register(self.agent_name)

        # Rotate
        resp = self.client.patch(
            f"/api/agents/{self.agent_name}/token",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        new_token = resp.get_json()["token"]

        # Old token must no longer authenticate
        old_resp = self.client.patch(
            f"/api/agents/{self.agent_name}/heartbeat",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        self.assertEqual(old_resp.status_code, 401,
                         f"old token should be invalid, got {old_resp.status_code}")

        # New token must work for subsequent operations
        new_resp = self.client.patch(
            f"/api/agents/{self.agent_name}/heartbeat",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        self.assertEqual(new_resp.status_code, 200)

    def test_rotate_with_operator_key_works_for_any_agent(self):
        token = self._register(self.agent_name)
        self.app.config["OPERATOR_KEY"] = "test-op-key"

        # Operator rotates the agent's token
        resp = self.client.patch(
            f"/api/agents/{self.agent_name}/token",
            headers={"Authorization": "Bearer test-op-key"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.get_json())

        # Verify the new token works
        new_token = resp.get_json()["token"]
        new_resp = self.client.patch(
            f"/api/agents/{self.agent_name}/heartbeat",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        self.assertEqual(new_resp.status_code, 200)

    def test_rotate_nonexistent_agent_returns_404(self):
        self.app.config["OPERATOR_KEY"] = "test-op-key"
        resp = self.client.patch(
            "/api/agents/does-not-exist/token",
            headers={"Authorization": "Bearer test-op-key"},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()