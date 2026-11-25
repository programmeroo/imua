"""
Integration tests for the Message Bus API endpoints.

Tests POST /api/messages and GET /api/messages with real Flask test client + in-memory SQLite.
"""


def _register(client, name):
    resp = client.post("/api/agents/register", json={"name": name})
    return resp.get_json()["token"]


class TestSendMessageApi:
    """POST /api/messages — send a message. Requires a valid agent bearer token;
    sender identity comes from the token, not the request body."""

    def test_send_valid_message(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/messages",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "to": "svy",
                                "type": "chat",
                                "body": "Can you review my PR?",
                            })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["sender"] == "akm"
        assert data["recipient"] == "svy"
        assert data["body"] == "Can you review my PR?"

    def test_send_without_token_returns_401(self, client):
        resp = client.post("/api/messages", json={
            "to": "svy",
            "body": "Hey!",
        })
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_send_sender_derived_from_token_ignores_body_from(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/messages",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "from": "svy",  # claiming to be someone else
                                "to": "slk",
                                "body": "Spoofed?",
                            })
        assert resp.status_code == 201
        assert resp.get_json()["sender"] == "akm"  # token identity wins, not the body claim

    def test_send_missing_to(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/messages",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"body": "Hey!"})
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["error"] == "validation_error"

    def test_send_broadcast(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/messages",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "to": "all",
                                "body": "Attention everyone!",
                            })
        assert resp.status_code == 201
        data = resp.get_json()
        # Broadcast returns a list (one entry per recipient)
        if isinstance(data, list):
            assert data[0]["sender"] == "akm"
            assert data[0]["msg_type"] == "broadcast"
        else:
            assert data["sender"] == "akm"
            assert data["msg_type"] == "broadcast"


class TestGetMessagesApi:
    """GET /api/messages — retrieve messages. Stays open (no auth) by design —
    see docs/superpowers/specs/2026-06-30-agent-token-auth-design.md."""

    def test_get_messages_empty(self, client):
        resp = client.get("/api/messages?to=svy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["messages"] == []

    def test_get_messages_after_sending(self, client):
        token = _register(client, "akm")
        client.post("/api/messages",
                     headers={"Authorization": f"Bearer {token}"},
                     json={"to": "svy", "body": "Test message"})

        resp = client.get("/api/messages?to=svy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 1
        assert data["messages"][0]["body"] == "Test message"

    def test_get_messages_missing_agent(self, client):
        resp = client.get("/api/messages")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "missing_param" in data["error"]
