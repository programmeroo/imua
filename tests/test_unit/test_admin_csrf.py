"""
CSRF protection, session admins on admin-only routes, and the operator-key
switch — task 5.5 (docs/imua_admin_security_plan_v1.md, D6 and D10).
"""

import re

import pytest

from app.services.admin_accounts import create_admin

PASSWORD = "correct horse battery"
OPERATOR_KEY = "op-test-key"
OPERATOR = {"Authorization": f"Bearer {OPERATOR_KEY}"}


def _page_token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html) or re.search(r'name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else None


@pytest.fixture
def signed_in(app, client):
    """A browser signed in as admin; returns the CSRF token its pages carry."""
    app.config["OPERATOR_KEY"] = OPERATOR_KEY
    with app.config["DB_ENGINE"].begin() as conn:
        create_admin(conn, "admin", PASSWORD)
    r = client.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": _page_token(client)})
    assert r.status_code == 302
    return _page_token(client, "/")


@pytest.fixture
def agent(app, client):
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestForms:
    def test_login_needs_the_token(self, app, client):
        with app.config["DB_ENGINE"].begin() as conn:
            create_admin(conn, "admin", PASSWORD)
        assert _page_token(client)  # embedded in the form
        for token in (None, "wrong"):
            data = {"username": "admin", "password": PASSWORD, **({"csrf_token": token} if token else {})}
            assert client.post("/login", data=data).status_code == 403

    def test_token_changes_at_sign_in(self, app, client):
        before = _page_token(client)
        with app.config["DB_ENGINE"].begin() as conn:
            create_admin(conn, "admin", PASSWORD)
        client.post("/login", data={"username": "admin", "password": PASSWORD, "csrf_token": before})
        assert _page_token(client, "/") not in (None, before)

    def test_logout_needs_the_token(self, client, signed_in):
        assert client.post("/logout").status_code == 403
        assert client.post("/logout", data={"csrf_token": signed_in}).status_code == 302

    def test_meta_tag_and_fetch_helper_only_when_signed_in(self, client):
        assert 'name="csrf-token"' not in client.get("/").get_data(as_text=True)

    def test_signed_in_page_attaches_token_to_fetch(self, client, signed_in):
        assert "X-CSRF-Token" in client.get("/tasks").get_data(as_text=True)


class TestSessionAdmin:
    def test_session_admin_with_token(self, client, signed_in):
        r = client.post("/api/projects", json={"name": "Alpha"}, headers={"X-CSRF-Token": signed_in})
        assert r.status_code == 201 and r.get_json()["created_by"] == "admin"
        assert client.delete("/api/projects/alpha", headers={"X-CSRF-Token": signed_in}).status_code == 200

    def test_session_write_without_token_refused(self, client, signed_in):
        r = client.post("/api/projects", json={"name": "Alpha"})
        assert r.status_code == 403 and r.get_json()["error"] == "csrf_failed"
        assert client.post("/api/projects", json={"name": "Alpha"},
                           headers={"X-CSRF-Token": "forged"}).status_code == 403

    def test_no_session_no_token_is_401(self, client):
        assert client.post("/api/projects", json={"name": "Alpha"}).status_code == 401

    def test_session_reads_need_no_token(self, client, signed_in):
        assert client.get("/api/projects").status_code == 200


class TestBearer:
    def test_operator_key_needs_no_csrf(self, app, client):
        app.config["OPERATOR_KEY"] = OPERATOR_KEY
        assert client.post("/api/projects", json={"name": "Alpha"}, headers=OPERATOR).status_code == 201

    def test_agent_token_still_forbidden_even_from_signed_in_browser(self, client, agent, signed_in):
        assert client.post("/api/projects", json={"name": "Alpha"}, headers=agent).status_code == 403

    def test_signed_in_browser_writes_need_the_token_everywhere(self, client, signed_in):
        assert client.post("/api/agents/register", json={"name": "SVY"}).status_code == 403
        assert client.post("/api/agents/register", json={"name": "SVY"},
                           headers={"X-CSRF-Token": signed_in}).status_code == 201

    def test_agent_writes_unaffected(self, client, agent):
        r = client.post("/api/tasks", json={"type": "build", "assigned_to": "AKM"}, headers=agent)
        assert r.status_code == 201

    def test_open_registration_unaffected(self, client):
        assert client.post("/api/agents/register", json={"name": "SVY"}).status_code == 201


class TestOperatorKeySwitch:
    def test_disabled_key_fails_everywhere(self, app, client):
        app.config["OPERATOR_KEY"] = OPERATOR_KEY
        app.config["OPERATOR_KEY_ENABLED"] = False
        assert client.post("/api/projects", json={"name": "Alpha"}, headers=OPERATOR).status_code == 401
        assert client.post("/api/tasks", json={"type": "build"}, headers=OPERATOR).status_code == 401

    def test_switch_read_from_config(self, tmp_path, monkeypatch):
        from app.server import create_app
        monkeypatch.setenv("IMUA_TESTING", "1")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("auth:\n  operator_key_enabled: false\n")
        assert create_app(config_path=str(cfg)).config["OPERATOR_KEY_ENABLED"] is False
        monkeypatch.setenv("IMUA_OPERATOR_KEY_ENABLED", "true")
        assert create_app(config_path=str(cfg)).config["OPERATOR_KEY_ENABLED"] is True
