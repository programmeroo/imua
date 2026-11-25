"""
REST message routes (task 4.8): GET / PATCH / DELETE /api/messages/<id>
and DELETE /api/messages?before=<date>.
"""

from datetime import datetime, timedelta

import pytest

from app.models.message import messages

OPERATOR_KEY = "op-test-key"
OPERATOR = {"Authorization": f"Bearer {OPERATOR_KEY}"}


@pytest.fixture
def agents(app, client):
    app.config["OPERATOR_KEY"] = OPERATOR_KEY
    headers = {}
    for name in ("AKM", "SVY", "SLK"):
        token = client.post("/api/agents/register", json={"name": name}).get_json()["token"]
        headers[name] = {"Authorization": f"Bearer {token}"}
    return headers


def _send(client, headers, to, body="hi"):
    resp = client.post("/api/messages", json={"to": to, "body": body}, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    return data if isinstance(data, list) else [data]


def _status(client, agent, msg_id):
    msgs = client.get(f"/api/messages?to={agent}&limit=500").get_json()["messages"]
    return next((m["status"] for m in msgs if m["id"] == msg_id), None)


def _backdate(app, msg_id, days):
    with app.config["DB_ENGINE"].begin() as conn:
        conn.execute(messages.update().where(messages.c.id == msg_id)
                     .values(created_at=datetime.utcnow() - timedelta(days=days)))


class TestGetOne:
    def test_recipient_reading_marks_read(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM", "hello")[0]
        resp = client.get(f"/api/messages/{msg['id']}", headers=agents["AKM"])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["body"] == "hello" and data["status"] == "read"
        assert _status(client, "AKM", msg["id"]) == "read"

    def test_operator_reads_without_marking(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.get(f"/api/messages/{msg['id']}", headers=OPERATOR)
        assert resp.status_code == 200 and resp.get_json()["status"] == "pending"
        assert _status(client, "AKM", msg["id"]) == "pending"

    def test_non_recipient_404(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        for intruder in ("SVY", "SLK"):
            assert client.get(f"/api/messages/{msg['id']}", headers=agents[intruder]).status_code == 404
        assert _status(client, "AKM", msg["id"]) == "pending"

    def test_requires_token(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        assert client.get(f"/api/messages/{msg['id']}").status_code == 401

    def test_missing_id_404(self, client, agents):
        assert client.get("/api/messages/99999", headers=agents["AKM"]).status_code == 404


class TestPatch:
    def test_recipient_sets_read_then_back(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        for status in ("read", "delivered"):
            resp = client.patch(f"/api/messages/{msg['id']}", json={"status": status}, headers=agents["AKM"])
            assert resp.status_code == 200 and resp.get_json()["status"] == status
            assert _status(client, "AKM", msg["id"]) == status

    def test_operator_can_set(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.patch(f"/api/messages/{msg['id']}", json={"status": "read"}, headers=OPERATOR)
        assert resp.status_code == 200
        assert _status(client, "AKM", msg["id"]) == "read"

    @pytest.mark.parametrize("body", [{}, {"status": "done"}, {"status": 1}, {"body": "x"}])
    def test_invalid_body_422(self, client, agents, body):
        msg = _send(client, agents["SVY"], "AKM")[0]
        assert client.patch(f"/api/messages/{msg['id']}", json=body, headers=agents["AKM"]).status_code == 422

    def test_non_recipient_404(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.patch(f"/api/messages/{msg['id']}", json={"status": "read"}, headers=agents["SLK"])
        assert resp.status_code == 404
        assert _status(client, "AKM", msg["id"]) == "pending"


class TestDeleteOne:
    def test_admin_deletes(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.delete(f"/api/messages/{msg['id']}", headers=OPERATOR)
        assert resp.status_code == 200 and resp.get_json() == {"deleted": 1}
        assert _status(client, "AKM", msg["id"]) is None

    def test_agents_forbidden_even_recipient(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        for agent in ("AKM", "SVY", "SLK"):
            assert client.delete(f"/api/messages/{msg['id']}", headers=agents[agent]).status_code == 403
        assert _status(client, "AKM", msg["id"]) == "pending"

    def test_missing_id_404(self, client, agents):
        assert client.delete("/api/messages/99999", headers=OPERATOR).status_code == 404

    def test_requires_token(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        assert client.delete(f"/api/messages/{msg['id']}").status_code == 401


class TestDeleteBefore:
    def test_operator_prunes_all_old(self, app, client, agents):
        old_a = _send(client, agents["SVY"], "AKM")[0]
        old_b = _send(client, agents["AKM"], "SLK")[0]
        new = _send(client, agents["SVY"], "AKM")[0]
        _backdate(app, old_a["id"], 40)
        _backdate(app, old_b["id"], 40)
        cutoff = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
        resp = client.delete(f"/api/messages?before={cutoff}", headers=OPERATOR)
        assert resp.status_code == 200 and resp.get_json() == {"deleted": 2}
        assert _status(client, "AKM", old_a["id"]) is None
        assert _status(client, "SLK", old_b["id"]) is None
        assert _status(client, "AKM", new["id"]) == "pending"

    def test_agent_forbidden(self, app, client, agents):
        mine = _send(client, agents["SVY"], "AKM")[0]
        _backdate(app, mine["id"], 40)
        resp = client.delete("/api/messages?before=" + datetime.utcnow().isoformat(), headers=agents["AKM"])
        assert resp.status_code == 403
        assert _status(client, "AKM", mine["id"]) == "pending"

    @pytest.mark.parametrize("query", ["", "?before=", "?before=yesterday"])
    def test_bad_or_missing_date_422(self, client, agents, query):
        assert client.delete(f"/api/messages{query}", headers=OPERATOR).status_code == 422

    def test_requires_token(self, client, agents):
        assert client.delete("/api/messages?before=2026-01-01").status_code == 401

    def test_offset_datetime_converted_to_utc(self, app, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        _backdate(app, msg["id"], 0)  # created "now" (UTC)
        # 1h from now in UTC, written as local time at +05:00: must still delete the message.
        cutoff = (datetime.utcnow() + timedelta(hours=1, minutes=300)).strftime("%Y-%m-%dT%H:%M:%S+05:00")
        assert client.delete(f"/api/messages?before={cutoff.replace('+', '%2B')}",
                             headers=OPERATOR).get_json() == {"deleted": 1}
