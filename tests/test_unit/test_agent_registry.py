"""Tests for the Agent Registry — registration, heartbeat, offline detection."""

from datetime import datetime, timedelta

from app.models.agent import agents


def _set_last_heartbeat(app, name, when):
    conn = app.config["DB_ENGINE"].connect()
    conn.execute(agents.update().where(agents.c.name == name).values(last_heartbeat=when))
    conn.commit()
    conn.close()


class TestOfflineDetection:
    def test_agent_with_stale_heartbeat_shows_offline(self, app, client):
        client.post("/api/agents/register", json={"name": "akm"})
        _set_last_heartbeat(app, "akm", datetime.utcnow() - timedelta(seconds=200))

        resp = client.get("/api/agents")

        assert resp.get_json()["agents"][0]["status"] == "offline"

    def test_agent_with_recent_heartbeat_shows_online(self, app, client):
        client.post("/api/agents/register", json={"name": "akm"})
        _set_last_heartbeat(app, "akm", datetime.utcnow())

        resp = client.get("/api/agents")

        assert resp.get_json()["agents"][0]["status"] == "online"

    def test_freshly_registered_agent_with_no_heartbeat_yet_shows_online(self, app, client):
        client.post("/api/agents/register", json={"name": "akm"})

        resp = client.get("/api/agents")

        assert resp.get_json()["agents"][0]["status"] == "online"

    def test_single_agent_get_also_reflects_offline(self, app, client):
        client.post("/api/agents/register", json={"name": "akm"})
        _set_last_heartbeat(app, "akm", datetime.utcnow() - timedelta(seconds=200))

        resp = client.get("/api/agents/akm")

        assert resp.get_json()["status"] == "offline"


class TestHeartbeatAuth:
    def test_heartbeat_without_token_returns_401(self, client):
        client.post("/api/agents/register", json={"name": "akm"})

        resp = client.patch("/api/agents/akm/heartbeat")

        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_heartbeat_with_valid_token_returns_200(self, client):
        reg = client.post("/api/agents/register", json={"name": "akm"})
        token = reg.get_json()["token"]

        resp = client.patch("/api/agents/akm/heartbeat",
                             headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "online"

    def test_heartbeat_with_mismatched_agent_token_returns_403(self, client):
        client.post("/api/agents/register", json={"name": "akm"})
        reg_svy = client.post("/api/agents/register", json={"name": "svy"})
        svy_token = reg_svy.get_json()["token"]

        resp = client.patch("/api/agents/akm/heartbeat",
                             headers={"Authorization": f"Bearer {svy_token}"})

        assert resp.status_code == 403
        assert resp.get_json()["error"] == "forbidden"
