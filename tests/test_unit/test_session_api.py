"""
API calls from a signed-in admin's browser — task 5.8
(docs/imua_admin_security_plan_v1.md). A session acts like the operator key,
with CSRF on every write, except that vault secret values never reach a browser (D12).
"""

import pytest

from conftest import sign_in_admin

OPERATOR = {"Authorization": "Bearer op-test-key"}


@pytest.fixture
def browser(app, client):
    """Signed-in admin client and the CSRF header its pages would send."""
    app.config["OPERATOR_KEY"] = "op-test-key"
    sign_in_admin(app, client, "admin")
    with client.session_transaction() as s:
        s["csrf"] = "page-token"
    return client, {"X-CSRF-Token": "page-token"}


def test_session_can_create_a_task(browser):
    client, csrf = browser
    r = client.post("/api/tasks", json={"type": "build", "assigned_to": "AKM"}, headers=csrf)
    assert r.status_code == 201 and r.get_json()["created_by"] == "admin"


def test_session_cron_write_and_delete(browser):
    client, csrf = browser
    job = client.post("/api/cron", json={"name": "nightly", "schedule": "0 2 * * *"}, headers=csrf).get_json()
    assert client.patch(f"/api/cron/{job['id']}", json={"status": "paused"}, headers=csrf).status_code == 200
    assert client.delete(f"/api/cron/{job['id']}", headers=csrf).status_code == 200


def test_session_write_without_csrf_refused(browser):
    client, _ = browser
    assert client.post("/api/tasks", json={"type": "build"}).status_code == 403


def test_no_session_no_token_still_401(client):
    assert client.post("/api/tasks", json={"type": "build"}).status_code == 401


def test_issue_actions_record_the_admin(browser):
    client, csrf = browser
    token = client.post("/api/agents/register", json={"name": "AKM"}, headers=csrf).get_json()["token"]
    issue = client.post("/api/issues", json={"source": "test", "type": "t", "severity": "warning",
                                             "subject": "s"}, headers={"Authorization": f"Bearer {token}"}).get_json()
    r = client.post(f"/api/issues/{issue['id']}/acknowledge", json={}, headers=csrf)
    assert r.status_code == 200 and "admin" in r.get_data(as_text=True)


class TestVault:
    def test_session_can_store_but_not_read_a_value(self, browser):
        client, csrf = browser
        r = client.post("/api/vault/secrets", json={"name": "api-key", "value": "s3cret"}, headers=csrf)
        assert r.status_code == 201
        r = client.get("/api/vault/secrets/api-key")
        assert r.status_code == 401 and b"s3cret" not in r.data

    def test_operator_key_still_reads_it(self, client, browser):
        _, csrf = browser
        client.post("/api/vault/secrets", json={"name": "api-key", "value": "s3cret"}, headers=csrf)
        assert client.get("/api/vault/secrets/api-key", headers=OPERATOR).get_json()["value"] == "s3cret"


def test_agents_unaffected(client):
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    agent = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/tasks", json={"type": "build", "assigned_to": "AKM"}, headers=agent).status_code == 201
    assert client.patch("/api/agents/AKM/heartbeat", json={}, headers=agent).status_code == 200
