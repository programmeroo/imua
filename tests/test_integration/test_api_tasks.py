"""
Integration tests for the Task Queue API auth enforcement.

POST /api/tasks and PATCH /api/tasks/<id> require a valid bearer token
(any authenticated agent, or the operator key). GET routes stay open.
"""


def _register(client, name):
    resp = client.post("/api/agents/register", json={"name": name})
    return resp.get_json()["token"]


class TestCreateTaskAuth:
    def test_create_without_token_returns_401(self, client):
        resp = client.post("/api/tasks", json={"type": "code.write"})
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_create_with_valid_token_succeeds(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/tasks",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"type": "code.write", "title": "Fix the bug"})
        assert resp.status_code == 201
        assert resp.get_json()["title"] == "Fix the bug"


class TestUpdateTaskAuth:
    def test_update_without_token_returns_401(self, client):
        token = _register(client, "akm")
        created = client.post("/api/tasks",
                               headers={"Authorization": f"Bearer {token}"},
                               json={"type": "code.write"})
        task_id = created.get_json()["id"]

        resp = client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_update_with_valid_token_succeeds(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/tasks", headers=headers, json={"type": "code.write"})
        task_id = created.get_json()["id"]

        resp = client.patch(f"/api/tasks/{task_id}", headers=headers,
                             json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "in_progress"


class TestTaskReadsStayOpen:
    """GET /api/tasks and GET /api/tasks/<id> are unauthenticated by design."""

    def test_list_tasks_without_token(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200

    def test_get_task_without_token(self, client):
        token = _register(client, "akm")
        created = client.post("/api/tasks",
                               headers={"Authorization": f"Bearer {token}"},
                               json={"type": "code.write"})
        task_id = created.get_json()["id"]

        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
