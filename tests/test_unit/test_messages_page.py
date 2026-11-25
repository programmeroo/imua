"""
Messages page admin controls — task 5.14 (docs/imua_admin_security_plan_v1.md).
Behaviour is browser-tested; this checks the controls are on the page and that
the signed-in session can do what they do.
"""

import pytest

from conftest import sign_in_admin


@pytest.fixture
def browser(app, client):
    sign_in_admin(app, client, "admin")
    with client.session_transaction() as s:
        s["csrf"] = "page-token"
    return client, {"X-CSRF-Token": "page-token"}


def _send(client, sender_token, to="SVY", body="hi"):
    r = client.post("/api/messages", json={"to": to, "body": body},
                    headers={"Authorization": f"Bearer {sender_token}"})
    assert r.status_code == 201
    return r.get_json()["id"]


@pytest.fixture
def ids(app, client):
    tokens = {n: client.post("/api/agents/register", json={"name": n}).get_json()["token"] for n in ("AKM", "SVY")}
    return [_send(client, tokens["AKM"], body=f"m{i}") for i in range(3)]


def test_page_has_the_controls(browser):
    client, _ = browser
    html = client.get("/messages").get_data(as_text=True)
    for control in ("btn-mark-selected", "btn-delete-selected", "prune-before", "btn-prune", "msg-select-all",
                    "message-detail-actions"):
        assert f'id="{control}"' in html


def test_session_marks_read_deletes_and_prunes(ids, browser):
    client, csrf = browser
    r = client.post("/api/messages/read", json={"ids": ids[:2]}, headers=csrf)
    assert r.status_code == 200 and sorted(r.get_json()["marked"]) == sorted(ids[:2])
    assert client.delete(f"/api/messages/{ids[0]}", headers=csrf).status_code == 200
    r = client.delete("/api/messages?before=2999-01-01", headers=csrf)
    assert r.status_code == 200 and r.get_json()["deleted"] == 2
    assert client.get("/api/messages?to=SVY").get_json()["messages"] == []


def test_session_actions_need_the_csrf_token(ids, browser):
    client, _ = browser
    assert client.post("/api/messages/read", json={"ids": ids}).status_code == 403
    assert client.delete(f"/api/messages/{ids[0]}").status_code == 403
