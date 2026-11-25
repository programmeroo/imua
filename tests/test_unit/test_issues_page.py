"""
PR 2c — page route + integration test.
"""
import os
os.environ["IMUA_TESTING"] = "1"


import unittest
from app.server import create_app
from conftest import sign_in_admin  # tests/ is on sys.path via pytest's rootdir conftest


class TestIssuesPage(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        # In-memory DB, so signing in doesn't write an admin into the real dev database
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        from app.models import init_db
        init_db(self.app)
        self.client = sign_in_admin(self.app, self.app.test_client())

    def test_issues_page_renders(self):
        resp = self.client.get("/issues")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("Operational Issues", body)
        self.assertIn('id="status-filter"', body)
        self.assertIn('id="severity-filter"', body)
        self.assertIn('id="source-filter"', body)
        self.assertIn("issues.js", body)

    def test_sidebar_includes_issues_link(self):
        resp = self.client.get("/")
        body = resp.get_data(as_text=True)
        self.assertIn('href="/issues"', body)
        # link text has a newline after "Issues" before the closing tag
        self.assertRegex(body, r'<span class="nav-icon">[^<]+</span>\s*Issues')

    def test_no_operator_key_kept_in_the_browser(self):
        """Task 5.9: issue actions use the signed-in session; no operator-key UI or storage."""
        for page, script in (("/settings", "settings.js"), ("/issues", "issues.js")):
            body = self.client.get(page).get_data(as_text=True)
            self.assertNotIn("operator-key", body)
            js = self.client.get(f"/static/js/{script}").get_data(as_text=True)
            self.assertNotIn("localStorage.setItem('imua-operator-key'", js)
            self.assertIn("localStorage.removeItem('imua-operator-key')", js)
            self.assertNotIn("Authorization", js)

    def test_full_issue_lifecycle_via_api(self):
        """Create -> acknowledge -> resolve -> list shows resolved."""
        self.client = self.app.test_client()  # API only: agent/operator tokens, no browser session
        self.app.config["OPERATOR_KEY"] = "test-op-key-pr2c"
        op_key = self.app.config["OPERATOR_KEY"]

        # Register an agent
        import time
        agent_name = f"pr2c-test-{int(time.time())}"
        reg = self.client.post("/api/agents/register", json={
            "name": agent_name,
            "role": "worker",
            "capabilities": ["test"],
        })
        self.assertIn(reg.status_code, (200, 201), f"register failed: {reg.status_code}")
        agent_token = reg.get_json().get("token")
        self.assertIsNotNone(agent_token)

        # Report an issue
        rep = self.client.post(
            "/api/issues",
            json={
                "source": "test",
                "type": "pr2c_lifecycle",
                "severity": "warning",
                "subject": "smoke test issue",
                "detail": "created by PR 2c smoke test",
            },
            headers={"Authorization": f"Bearer {agent_token}"},
        )
        self.assertEqual(rep.status_code, 201, f"report failed: {rep.status_code} {rep.get_data(as_text=True)}")
        issue_id = rep.get_json()["id"]

        # Acknowledge as operator
        ack = self.client.post(
            f"/api/issues/{issue_id}/acknowledge",
            headers={"Authorization": f"Bearer {op_key}"},
        )
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.get_json()["issue"]["status"], "acknowledged")

        # Resolve as operator
        res = self.client.post(
            f"/api/issues/{issue_id}/resolve",
            json={"resolution": "PR 2c smoke test passed"},
            headers={"Authorization": f"Bearer {op_key}"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["issue"]["status"], "resolved")

        # Verify list with status=resolved returns it
        listed = self.client.get("/api/issues?status=resolved").get_json()
        ids = [i["id"] for i in listed["issues"]]
        self.assertIn(issue_id, ids)

        # Suppress attempt on resolved issue should fail with 409
        sup = self.client.post(
            f"/api/issues/{issue_id}/suppress",
            headers={"Authorization": f"Bearer {op_key}"},
        )
        self.assertEqual(sup.status_code, 409)


if __name__ == "__main__":
    unittest.main()