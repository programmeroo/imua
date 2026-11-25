"""
`project` on tasks and cron jobs — task 6.4 (docs/imua_projects_plan_v1.md §5.2).
"""

import pytest

from app.models.cron import cron_jobs
from app.models.task import tasks
from sqlalchemy import func, select

ADMIN = {"Authorization": "Bearer op-test-key"}


@pytest.fixture
def akm(app, client):
    app.config["OPERATOR_KEY"] = "op-test-key"
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    client.post("/api/projects", json={"name": "Lead Gen"}, headers=ADMIN)
    return {"Authorization": f"Bearer {token}"}


def _count(app, table):
    with app.config["DB_ENGINE"].connect() as c:
        return c.execute(select(func.count()).select_from(table)).scalar()


def _task(client, headers, **extra):
    return client.post("/api/tasks", json={"type": "build", "assigned_to": "AKM", **extra}, headers=headers)


def _cron(client, headers, **extra):
    return client.post("/api/cron", json={"name": "nightly", "schedule": "0 2 * * *", **extra}, headers=headers)


class TestTasks:
    def test_create_in_a_project(self, client, akm):
        r = _task(client, akm, project="lead-gen")
        assert r.status_code == 201 and r.get_json()["project"] == "lead-gen"
        tid = r.get_json()["id"]
        assert client.get(f"/api/tasks/{tid}").get_json()["project"] == "lead-gen"
        assert [t["project"] for t in client.get("/api/tasks").get_json()["tasks"]] == ["lead-gen"]
        items = client.get("/api/projects/lead-gen/items?type=task").get_json()["items"]
        assert [i["id"] for i in items] == [tid]

    def test_without_project_works_as_before(self, client, akm):
        r = _task(client, akm)
        assert r.status_code == 201 and r.get_json()["project"] is None

    @pytest.mark.parametrize("project,status", [("nope", 404), (123, 400)])
    def test_bad_project_creates_nothing(self, app, client, akm, project, status):
        assert _task(client, akm, project=project).status_code == status
        assert _count(app, tasks) == 0

    def test_archived_project_refused(self, app, client, akm):
        client.patch("/api/projects/lead-gen", json={"status": "archived"}, headers=ADMIN)
        assert _task(client, akm, project="lead-gen").status_code == 409
        assert _count(app, tasks) == 0

    def test_patch_keeps_project(self, client, akm):
        tid = _task(client, akm, project="lead-gen").get_json()["id"]
        r = client.patch(f"/api/tasks/{tid}", json={"priority": 1}, headers=akm)
        assert r.get_json()["project"] == "lead-gen"


class TestCron:
    def test_create_in_a_project(self, client, akm):
        r = _cron(client, akm, project="lead-gen")
        assert r.status_code == 201 and r.get_json()["project"] == "lead-gen"
        jid = r.get_json()["id"]
        assert client.get(f"/api/cron/{jid}").get_json()["project"] == "lead-gen"
        assert client.get("/api/cron").get_json()["cron_jobs"][0]["project"] == "lead-gen"
        assert client.patch(f"/api/cron/{jid}", json={"status": "paused"}, headers=akm).get_json()["project"] == "lead-gen"

    def test_bad_project_creates_nothing(self, app, client, akm):
        assert _cron(client, akm, project="nope").status_code == 404
        assert _count(app, cron_jobs) == 0

    def test_delete_removes_the_link(self, client, akm):
        jid = _cron(client, akm, project="lead-gen").get_json()["id"]
        assert client.delete(f"/api/cron/{jid}", headers=akm).status_code == 200
        assert client.get("/api/projects/lead-gen").get_json()["counts"]["cron"] == 0
        assert client.delete("/api/projects/lead-gen", headers=ADMIN).status_code == 200  # now empty
