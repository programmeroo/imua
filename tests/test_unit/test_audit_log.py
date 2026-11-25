"""
Audit log — task 5.6 (docs/imua_admin_security_plan_v1.md): every admin action,
including sign-in and failed sign-in, with who / what / which item / when / IP.
"""

import pytest

from app.services import admin_session
from app.services.admin_accounts import create_admin

OPERATOR = {"Authorization": "Bearer op-test-key"}
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _setup(app):
    app.config["OPERATOR_KEY"] = "op-test-key"
    admin_session._failures.clear()
    with app.config["DB_ENGINE"].begin() as conn:
        create_admin(conn, "admin", PASSWORD)
    yield
    admin_session._failures.clear()


def _entries(client, **params):
    r = client.get("/api/audit", query_string=params, headers=OPERATOR)
    assert r.status_code == 200
    return r.get_json()["entries"]


def _csrf(client):
    client.get("/login")
    with client.session_transaction() as s:
        return s["csrf"]


def _login(client, password=PASSWORD):
    return client.post("/login", data={"username": "admin", "password": password, "csrf_token": _csrf(client)})


class TestSignInEvents:
    def test_success_failure_and_sign_out(self, client):
        _login(client, "wrong password!!")
        _login(client)
        with client.session_transaction() as s:
            token = s.get("csrf") or s.setdefault("csrf", "t")
        client.post("/logout", data={"csrf_token": token})
        got = [(e["actor"], e["action"], e["status"]) for e in _entries(client, actor="admin")]
        assert got == [("admin", "sign_out", 302), ("admin", "sign_in", 302), ("admin", "sign_in_failed", 401)]
        assert all(e["ip"] == "127.0.0.1" and e["at"] for e in _entries(client, actor="admin"))

    def test_lockout_is_recorded(self, client):
        for _ in range(admin_session.MAX_FAILURES):
            _login(client, "wrong password!!")
        _login(client)
        assert _entries(client, actor="admin")[0]["action"] == "sign_in_refused"

    def test_unknown_username_is_recorded_as_tried(self, client):
        client.post("/login", data={"username": "mallory", "password": "x" * 12, "csrf_token": _csrf(client)})
        assert _entries(client, actor="mallory")[0]["action"] == "sign_in_failed"


class TestAdminWrites:
    def test_operator_key_write_is_recorded_with_target(self, client):
        client.post("/api/projects", json={"name": "Lead Gen"}, headers=OPERATOR)
        client.delete("/api/projects/lead-gen", headers=OPERATOR)
        got = [(e["actor"], e["action"], e["target"], e["status"]) for e in _entries(client)[:2]]
        assert got == [("operator", "DELETE /api/projects/<slug>", "/api/projects/lead-gen", 200),
                       ("operator", "POST /api/projects", "/api/projects", 201)]

    def test_session_write_records_the_admin(self, client):
        _login(client)
        with client.session_transaction() as s:
            token = s.setdefault("csrf", "t")
        client.post("/api/tasks", json={"type": "build"}, headers={"X-CSRF-Token": token})
        assert (_entries(client)[0]["actor"], _entries(client)[0]["action"]) == ("admin", "POST /api/tasks")

    def test_refused_admin_write_is_still_recorded(self, client):
        client.post("/api/projects", json={"name": "Alpha"}, headers=OPERATOR)
        client.post("/api/projects", json={"name": "Alpha"}, headers=OPERATOR)  # duplicate → 409
        assert _entries(client)[0]["status"] == 409

    def test_agent_actions_and_reads_are_not_admin_actions(self, client):
        token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
        client.post("/api/tasks", json={"type": "build"}, headers={"Authorization": f"Bearer {token}"})
        client.get("/api/projects", headers=OPERATOR)
        assert _entries(client) == []


class TestApi:
    def test_admin_only(self, client):
        assert client.get("/api/audit").status_code == 401
        token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
        assert client.get("/api/audit", headers={"Authorization": f"Bearer {token}"}).status_code == 403

    def test_paging(self, client):
        for name in ("A1", "A2", "A3"):
            client.post("/api/projects", json={"name": name}, headers=OPERATOR)
        first = _entries(client, limit=2)
        rest = _entries(client, limit=2, before=first[-1]["id"])
        assert len(first) == 2 and len(rest) == 1 and rest[0]["id"] < first[-1]["id"]

    def test_bad_params(self, client):
        assert client.get("/api/audit?limit=x", headers=OPERATOR).status_code == 400


def test_settings_page_has_audit_panel(app, admin_client):
    """Task 5.6b: the log is viewable in Settings (panel + script; data via /api/audit)."""
    html = admin_client.get("/settings").get_data(as_text=True)
    assert 'id="audit-panel"' in html and 'id="audit-table"' in html and "audit.js" in html


def test_settings_session_can_read_the_log(app, admin_client):
    """The panel fetches /api/audit with the signed-in session (no token in the browser)."""
    admin_client.post("/api/projects", json={"name": "Lead Gen"}, headers=OPERATOR)
    r = admin_client.get("/api/audit")
    assert r.status_code == 200 and r.get_json()["entries"][0]["action"] == "POST /api/projects"
