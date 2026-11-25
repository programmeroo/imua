"""
Projects API — task 6.3 (docs/imua_projects_plan_v1.md §5.1).
Service rules are covered in test_projects_service.py; this checks HTTP shape and auth.
"""

import pytest

OPERATOR_KEY = "op-test-key"
ADMIN = {"Authorization": f"Bearer {OPERATOR_KEY}"}


@pytest.fixture
def akm(app, client):
    """AKM's agent-token header."""
    app.config["OPERATOR_KEY"] = OPERATOR_KEY
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alpha(client, akm):
    resp = client.post("/api/projects", json={"name": "Alpha", "description": "first"}, headers=ADMIN)
    assert resp.status_code == 201
    return resp.get_json()


def _task(client, akm, title="t"):
    return client.post("/api/tasks", json={"type": "build", "title": title, "assigned_to": "AKM"},
                       headers=akm).get_json()["id"]


class TestProjects:
    def test_create_get_list(self, client, alpha):
        assert alpha["slug"] == "alpha" and alpha["created_by"] == "operator"
        assert client.get("/api/projects/alpha").get_json()["description"] == "first"
        listed = client.get("/api/projects").get_json()
        assert listed["count"] == 1 and listed["projects"][0]["counts"]["task"] == 0

    def test_errors(self, client, alpha):
        assert client.post("/api/projects", json={"name": "Alpha"}, headers=ADMIN).status_code == 409
        assert client.post("/api/projects", json={}, headers=ADMIN).status_code == 400
        resp = client.get("/api/projects/nope")
        assert resp.status_code == 404 and resp.get_json()["error"] == "not_found"

    def test_patch_and_status_filter(self, client, alpha):
        resp = client.patch("/api/projects/alpha", json={"status": "archived", "name": "A"}, headers=ADMIN)
        assert resp.status_code == 200 and resp.get_json()["name"] == "A"
        assert client.get("/api/projects?status=active").get_json()["count"] == 0
        assert client.get("/api/projects?status=archived").get_json()["count"] == 1

    def test_patch_refuses_other_fields(self, client, alpha):
        assert client.patch("/api/projects/alpha", json={"slug": "beta"}, headers=ADMIN).status_code == 400

    def test_delete(self, client, alpha):
        assert client.delete("/api/projects/alpha", headers=ADMIN).status_code == 200
        assert client.get("/api/projects/alpha").status_code == 404


class TestItemsAndAgents:
    def test_put_list_remove_item(self, client, akm, alpha):
        tid = _task(client, akm, "ship it")
        resp = client.put(f"/api/projects/alpha/items/task/{tid}", headers=ADMIN)
        assert resp.status_code == 200 and resp.get_json()["counts"]["task"] == 1
        items = client.get("/api/projects/alpha/items?type=task").get_json()
        assert items["count"] == 1 and items["items"][0]["title"] == "ship it"
        assert client.delete("/api/projects/alpha", headers=ADMIN).status_code == 409  # not empty
        assert client.delete(f"/api/projects/alpha/items/task/{tid}", headers=ADMIN).status_code == 200
        assert client.delete(f"/api/projects/alpha/items/task/{tid}", headers=ADMIN).status_code == 404

    def test_item_errors(self, client, akm, alpha):
        assert client.put("/api/projects/alpha/items/task/999", headers=ADMIN).status_code == 404
        assert client.put("/api/projects/alpha/items/message/1", headers=ADMIN).status_code == 400
        assert client.get("/api/projects/alpha/items?type=bogus").status_code == 400
        client.patch("/api/projects/alpha", json={"status": "archived"}, headers=ADMIN)
        assert client.put(f"/api/projects/alpha/items/task/{_task(client, akm)}", headers=ADMIN).status_code == 409

    def test_members(self, client, alpha):
        assert client.put("/api/projects/alpha/agents/AKM", headers=ADMIN).get_json()["agents"] == ["AKM"]
        assert client.put("/api/projects/alpha/agents/GHOST", headers=ADMIN).status_code == 404
        assert client.delete("/api/projects/alpha/agents/AKM", headers=ADMIN).get_json()["agents"] == []


class TestAuth:
    WRITES = [("post", "/api/projects"), ("patch", "/api/projects/alpha"), ("delete", "/api/projects/alpha"),
              ("put", "/api/projects/alpha/items/task/1"), ("delete", "/api/projects/alpha/items/task/1"),
              ("put", "/api/projects/alpha/agents/AKM"), ("delete", "/api/projects/alpha/agents/AKM")]

    @pytest.mark.parametrize("method,path", WRITES)
    def test_writes_need_admin(self, client, akm, alpha, method, path):
        call = getattr(client, method)
        assert call(path, json={"name": "x"}).status_code == 401
        assert call(path, json={"name": "x"}, headers=akm).status_code == 403

    def test_reads_are_open(self, client, alpha):
        for path in ("/api/projects", "/api/projects/alpha", "/api/projects/alpha/items?type=task"):
            assert client.get(path).status_code == 200

    def test_git_site_route_unaffected(self, client):
        assert client.get("/api/project/status").status_code == 200
