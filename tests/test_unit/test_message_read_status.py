"""
Message read status — hub issue #1 (docs/issues 11-8-26.md).

POST /api/messages/<id>/read, POST /api/messages/read (bulk),
GET /api/messages ?status= / ?unread=, and per-recipient broadcast visibility.
"""

import pytest

OPERATOR_KEY = "op-test-key"


@pytest.fixture
def agents(app, client):
    """Register AKM, SVY, SLK; return {name: auth headers}. Enables the operator key."""
    app.config["OPERATOR_KEY"] = OPERATOR_KEY
    headers = {}
    for name in ("AKM", "SVY", "SLK"):
        token = client.post("/api/agents/register", json={"name": name}).get_json()["token"]
        headers[name] = {"Authorization": f"Bearer {token}"}
    return headers


OPERATOR = {"Authorization": f"Bearer {OPERATOR_KEY}"}


def _send(client, headers, to, body="hi"):
    resp = client.post("/api/messages", json={"to": to, "body": body}, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    return data if isinstance(data, list) else [data]


def _inbox(client, agent, query=""):
    resp = client.get(f"/api/messages?to={agent}{query}")
    assert resp.status_code == 200
    return resp.get_json()["messages"]


class TestMarkSingleRead:
    def test_recipient_marks_own_message_read(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.post(f"/api/messages/{msg['id']}/read", headers=agents["AKM"])
        assert resp.status_code == 200
        assert resp.get_json() == {"id": msg["id"], "status": "read"}
        assert _inbox(client, "AKM")[0]["status"] == "read"

    def test_idempotent(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        for _ in range(2):
            resp = client.post(f"/api/messages/{msg['id']}/read", headers=agents["AKM"])
            assert resp.status_code == 200

    def test_non_recipient_gets_404_and_status_unchanged(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        # The sender is not the recipient either.
        for intruder in ("SLK", "SVY"):
            resp = client.post(f"/api/messages/{msg['id']}/read", headers=agents[intruder])
            assert resp.status_code == 404
        assert _inbox(client, "AKM")[0]["status"] == "pending"

    def test_unknown_id_404(self, client, agents):
        resp = client.post("/api/messages/99999/read", headers=agents["AKM"])
        assert resp.status_code == 404

    def test_requires_token(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.post(f"/api/messages/{msg['id']}/read")
        assert resp.status_code == 401

    def test_operator_can_mark_any_message(self, client, agents):
        msg = _send(client, agents["SVY"], "AKM")[0]
        resp = client.post(f"/api/messages/{msg['id']}/read", headers=OPERATOR)
        assert resp.status_code == 200
        assert _inbox(client, "AKM")[0]["status"] == "read"


class TestMarkBulkRead:
    def test_marks_own_and_skips_others(self, client, agents):
        mine = [_send(client, agents["SVY"], "AKM", f"m{i}")[0]["id"] for i in range(2)]
        theirs = _send(client, agents["AKM"], "SLK")[0]["id"]
        resp = client.post("/api/messages/read", json={"ids": mine + [theirs, 99999]},
                           headers=agents["AKM"])
        assert resp.status_code == 200
        assert resp.get_json() == {"marked": sorted(mine), "skipped": [theirs, 99999]}
        assert {m["status"] for m in _inbox(client, "AKM")} == {"read"}
        assert _inbox(client, "SLK")[0]["status"] == "pending"

    def test_broadcast_marks_only_callers_copy(self, client, agents):
        rows = _send(client, agents["SVY"], "all", "announcement")
        ids = [r["id"] for r in rows]
        assert len(ids) == 3
        resp = client.post("/api/messages/read", json={"ids": ids}, headers=agents["AKM"])
        body = resp.get_json()
        assert len(body["marked"]) == 1 and len(body["skipped"]) == 2
        assert _inbox(client, "AKM")[0]["status"] == "read"
        assert _inbox(client, "SLK")[0]["status"] == "pending"

    def test_operator_bulk(self, client, agents):
        ids = [r["id"] for r in _send(client, agents["SVY"], "all")]
        resp = client.post("/api/messages/read", json={"ids": ids}, headers=OPERATOR)
        assert resp.get_json() == {"marked": sorted(ids), "skipped": []}

    @pytest.mark.parametrize("payload", [
        {}, {"ids": []}, {"ids": "1"}, {"ids": [1, "x"]}, {"ids": [True]},
        {"ids": list(range(1, 502))},
    ])
    def test_validation(self, client, agents, payload):
        resp = client.post("/api/messages/read", json=payload, headers=agents["AKM"])
        assert resp.status_code == 422

    def test_requires_token(self, client, agents):
        resp = client.post("/api/messages/read", json={"ids": [1]})
        assert resp.status_code == 401


class TestListFilters:
    def _setup(self, client, agents):
        a, b = (_send(client, agents["SVY"], "AKM", body)[0]["id"] for body in ("a", "b"))
        client.post(f"/api/messages/{a}/read", headers=agents["AKM"])
        return a, b

    def test_status_filter(self, client, agents):
        a, b = self._setup(client, agents)
        assert [m["id"] for m in _inbox(client, "AKM", "&status=read")] == [a]
        assert [m["id"] for m in _inbox(client, "AKM", "&status=pending")] == [b]

    def test_unread_filter(self, client, agents):
        a, b = self._setup(client, agents)
        assert [m["id"] for m in _inbox(client, "AKM", "&unread=true")] == [b]
        assert len(_inbox(client, "AKM", "&unread=false")) == 2

    def test_filter_applies_before_limit(self, client, agents):
        """limit must count matching rows, not be applied first and filtered after."""
        old = _send(client, agents["SVY"], "AKM", "old")[0]["id"]
        for i in range(3):
            newer = _send(client, agents["SVY"], "AKM", f"new{i}")[0]["id"]
            client.post(f"/api/messages/{newer}/read", headers=agents["AKM"])
        assert [m["id"] for m in _inbox(client, "AKM", "&unread=true&limit=2")] == [old]

    def test_invalid_status_422(self, client, agents):
        resp = client.get("/api/messages?to=AKM&status=bogus")
        assert resp.status_code == 422


class TestBroadcastVisibility:
    def test_agent_sees_only_its_own_broadcast_copy(self, client, agents):
        _send(client, agents["SVY"], "all", "announcement")
        inbox = _inbox(client, "AKM")
        assert len(inbox) == 1
        assert inbox[0]["recipient"] == "AKM"
