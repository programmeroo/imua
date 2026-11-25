"""
Task controls — task 5.16 (docs/imua_admin_security_plan_v1.md): admin delete,
prune finished tasks only, status validation, and the Tasks page controls.
"""

from datetime import datetime, timedelta

import pytest

from app.models.task import tasks
from conftest import sign_in_admin

OPERATOR = {"Authorization": "Bearer op-test-key"}


@pytest.fixture
def agent(app, client):
    app.config["OPERATOR_KEY"] = "op-test-key"
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _task(client, agent, status=None, project=None):
    body = {"type": "build", "assigned_to": "AKM", **({"project": project} if project else {})}
    tid = client.post("/api/tasks", json=body, headers=agent).get_json()["id"]
    if status:
        assert client.patch(f"/api/tasks/{tid}", json={"status": status}, headers=agent).status_code == 200
    return tid


def _age(app, tid, days):
    with app.config["DB_ENGINE"].begin() as conn:
        old = datetime.utcnow() - timedelta(days=days)
        conn.execute(tasks.update().where(tasks.c.id == tid).values(created_at=old, completed_at=old))


def _ids(client):
    return sorted(t["id"] for t in client.get("/api/tasks").get_json()["tasks"])


class TestStatus:
    def test_unknown_status_refused(self, client, agent):
        tid = _task(client, agent)
        r = client.patch(f"/api/tasks/{tid}", json={"status": "done"}, headers=agent)
        assert r.status_code == 422
        assert client.get(f"/api/tasks/{tid}").get_json()["status"] == "pending"

    def test_session_can_change_status(self, app, client, agent):
        tid = _task(client, agent)
        sign_in_admin(app, client)
        with client.session_transaction() as s:
            s["csrf"] = "t"
        r = client.patch(f"/api/tasks/{tid}", json={"status": "cancelled"}, headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200 and r.get_json()["status"] == "cancelled"


class TestDelete:
    def test_admin_deletes_and_project_link_goes(self, client, agent):
        client.post("/api/projects", json={"name": "Alpha"}, headers=OPERATOR)
        tid = _task(client, agent, project="alpha")
        assert client.delete(f"/api/tasks/{tid}", headers=OPERATOR).status_code == 200
        assert tid not in _ids(client)
        assert client.get("/api/projects/alpha").get_json()["counts"]["task"] == 0
        assert client.delete(f"/api/tasks/{tid}", headers=OPERATOR).status_code == 404

    def test_agents_cannot_delete(self, client, agent):
        tid = _task(client, agent)
        assert client.delete(f"/api/tasks/{tid}", headers=agent).status_code == 403
        assert client.delete(f"/api/tasks/{tid}").status_code == 401


class TestPrune:
    def test_only_old_finished_tasks_are_deleted(self, app, client, agent):
        keep = {s: _task(client, agent, s) for s in ("pending", "in_progress")}
        gone = {s: _task(client, agent, s) for s in ("completed", "failed", "cancelled")}
        recent_done = _task(client, agent, "completed")
        for tid in list(keep.values()) + list(gone.values()):
            _age(app, tid, 30)
        before = (datetime.utcnow() - timedelta(days=7)).date().isoformat()
        r = client.delete(f"/api/tasks?before={before}", headers=OPERATOR)
        # "failed" may have been re-queued by the hub's retry logic; only truly finished ones go
        remaining = _ids(client)
        assert keep["pending"] in remaining and keep["in_progress"] in remaining and recent_done in remaining
        assert gone["completed"] not in remaining and gone["cancelled"] not in remaining
        assert r.status_code == 200 and r.get_json()["deleted"] >= 2

    def test_bad_date_and_auth(self, client, agent):
        assert client.delete("/api/tasks?before=soon", headers=OPERATOR).status_code == 422
        assert client.delete("/api/tasks?before=2999-01-01", headers=agent).status_code == 403


def test_page_has_the_controls(app, client, agent):
    sign_in_admin(app, client)
    html = client.get("/tasks").get_data(as_text=True)
    assert 'id="task-prune-before"' in html and 'id="btn-task-prune"' in html
