"""
Integration tests for the Cron Job API auth enforcement.

POST/PATCH/DELETE /api/cron... require a valid bearer token (any
authenticated agent, or the operator key). GET routes stay open.
"""


def _register(client, name):
    resp = client.post("/api/agents/register", json={"name": name})
    return resp.get_json()["token"]


def _create_job(client, token):
    resp = client.post("/api/cron",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"name": "nightly-backup", "schedule": "0 2 * * *"})
    return resp.get_json()["id"]


class TestCreateJobAuth:
    def test_create_without_token_returns_401(self, client):
        resp = client.post("/api/cron", json={"name": "job", "schedule": "* * * * *"})
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_create_with_valid_token_succeeds(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/cron",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"name": "nightly-backup", "schedule": "0 2 * * *"})
        assert resp.status_code == 201
        assert resp.get_json()["name"] == "nightly-backup"


class TestUpdateJobAuth:
    def test_update_without_token_returns_401(self, client):
        token = _register(client, "akm")
        job_id = _create_job(client, token)

        resp = client.patch(f"/api/cron/{job_id}", json={"status": "paused"})
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_update_with_valid_token_succeeds(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}
        job_id = _create_job(client, token)

        resp = client.patch(f"/api/cron/{job_id}", headers=headers, json={"status": "paused"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "paused"


class TestTriggerJobAuth:
    def test_trigger_without_token_returns_401(self, client):
        token = _register(client, "akm")
        job_id = _create_job(client, token)

        resp = client.post(f"/api/cron/{job_id}/run")
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_trigger_with_valid_token_succeeds(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}
        job_id = _create_job(client, token)

        resp = client.post(f"/api/cron/{job_id}/run", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "triggered"


class TestDeleteJobAuth:
    def test_delete_without_token_returns_401(self, client):
        token = _register(client, "akm")
        job_id = _create_job(client, token)

        resp = client.delete(f"/api/cron/{job_id}")
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_delete_with_valid_token_succeeds(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}
        job_id = _create_job(client, token)

        resp = client.delete(f"/api/cron/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "deleted"


class TestCronReadsStayOpen:
    """GET /api/cron, GET /api/cron/<id>, GET /api/cron/<id>/history are
    unauthenticated by design."""

    def test_list_jobs_without_token(self, client):
        resp = client.get("/api/cron")
        assert resp.status_code == 200

    def test_get_job_without_token(self, client):
        token = _register(client, "akm")
        job_id = _create_job(client, token)

        resp = client.get(f"/api/cron/{job_id}")
        assert resp.status_code == 200

    def test_job_history_without_token(self, client):
        token = _register(client, "akm")
        job_id = _create_job(client, token)

        resp = client.get(f"/api/cron/{job_id}/history")
        assert resp.status_code == 200
