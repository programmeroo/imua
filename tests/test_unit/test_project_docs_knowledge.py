"""
`project` on documents and knowledge, and project-filtered knowledge search —
task 6.5 (docs/imua_projects_plan_v1.md §5.2, D6).
"""

import io
import uuid

import pytest
from sqlalchemy import func, select

from app.models.document import documents
from app.services import knowledge_base as kb

ADMIN = {"Authorization": "Bearer op-test-key"}


@pytest.fixture
def akm(app, client):
    app.config["OPERATOR_KEY"] = "op-test-key"
    kb.init_knowledge_base(app)  # in-memory store (IMUA_TESTING), never data/chroma
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    for name in ("Alpha", "Beta"):
        client.post("/api/projects", json={"name": name}, headers=ADMIN)
    return {"Authorization": f"Bearer {token}"}


def _upload(client, headers, **form):
    data = {"file": (io.BytesIO(b"hello"), "notes.txt"), **form}
    return client.post("/api/documents", data=data, headers=headers, content_type="multipart/form-data")


def _knowledge(client, headers, body, **extra):
    return client.post("/api/knowledge", json={"body": body, **extra}, headers=headers)


def _search_ids(client, query, project=None):
    url = f"/api/knowledge?q={query}&n=50" + (f"&project={project}" if project else "")
    return {h["id"] for h in client.get(url).get_json()["hits"]}


class TestDocuments:
    def test_upload_into_a_project(self, client, akm):
        r = _upload(client, akm, project="alpha")
        assert r.status_code == 201 and r.get_json()["project"] == "alpha"
        doc_id = r.get_json()["id"]
        assert client.get("/api/documents").get_json()["documents"][0]["project"] == "alpha"
        assert client.post(f"/api/documents/{doc_id}/archive", headers=akm).get_json()["project"] == "alpha"

    def test_without_project(self, client, akm):
        assert _upload(client, akm).get_json()["project"] is None

    def test_unknown_project_stores_nothing(self, app, client, akm):
        assert _upload(client, akm, project="nope").status_code == 404
        with app.config["DB_ENGINE"].connect() as c:
            assert c.execute(select(func.count()).select_from(documents)).scalar() == 0


class TestKnowledge:
    def test_add_get_recent_show_project(self, client, akm):
        r = _knowledge(client, akm, "Alpha launch notes", project="alpha")
        assert r.status_code == 201 and r.get_json()["project"] == "alpha"
        eid = r.get_json()["id"]
        assert client.get(f"/api/knowledge/{eid}").get_json()["project"] == "alpha"
        recent = client.get("/api/knowledge/recent").get_json()["entries"]
        assert next(e for e in recent if e["id"] == eid)["project"] == "alpha"

    def test_unknown_project_refused(self, client, akm):
        assert _knowledge(client, akm, "x", project="nope").status_code == 404
        assert client.get("/api/knowledge?q=x&project=nope").status_code == 404

    def test_search_filters_by_project(self, client, akm):
        word = uuid.uuid4().hex[:8]
        a = _knowledge(client, akm, f"{word} pricing for alpha", project="alpha").get_json()["id"]
        b = _knowledge(client, akm, f"{word} pricing for beta", project="beta").get_json()["id"]
        none = _knowledge(client, akm, f"{word} pricing, no project").get_json()["id"]
        assert {a, b, none} <= _search_ids(client, word)
        assert _search_ids(client, word, "alpha") & {a, b, none} == {a}
        hits = client.get(f"/api/knowledge?q={word}&project=beta").get_json()["hits"]
        assert all(h["project"] == "beta" for h in hits)

    def test_moving_an_entry_moves_it_in_search(self, client, akm):
        word = uuid.uuid4().hex[:8]
        eid = _knowledge(client, akm, f"{word} roadmap", project="alpha").get_json()["id"]
        client.put(f"/api/projects/beta/items/knowledge/{eid}", headers=ADMIN)
        assert eid in _search_ids(client, word, "beta") and eid not in _search_ids(client, word, "alpha")
        client.delete(f"/api/projects/beta/items/knowledge/{eid}", headers=ADMIN)
        assert eid not in _search_ids(client, word, "beta")
        assert client.get(f"/api/knowledge/{eid}").get_json()["project"] is None

    def test_delete_removes_the_link(self, client, akm):
        eid = _knowledge(client, akm, "short-lived", project="alpha").get_json()["id"]
        assert client.delete(f"/api/knowledge/{eid}", headers=akm).status_code == 200
        assert client.get("/api/projects/alpha").get_json()["counts"]["knowledge"] == 0
