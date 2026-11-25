"""
Editing knowledge entries — task 5.18 (docs/imua_admin_security_plan_v1.md):
PATCH title / body / tags; a changed body is re-indexed so search finds the new text.
"""

import uuid

import pytest

from app.services import knowledge_base as kb
from conftest import sign_in_admin

OPERATOR = {"Authorization": "Bearer op-test-key"}


@pytest.fixture
def agents(app, client):
    app.config["OPERATOR_KEY"] = "op-test-key"
    kb.init_knowledge_base(app)  # in-memory store (IMUA_TESTING), never data/chroma
    return {n: {"Authorization": "Bearer " + client.post("/api/agents/register", json={"name": n}).get_json()["token"]}
            for n in ("AKM", "SVY")}


def _add(client, headers, body, **extra):
    r = client.post("/api/knowledge", json={"body": body, **extra}, headers=headers)
    assert r.status_code == 201
    return r.get_json()


def _hit_ids(client, query, project=None):
    url = f"/api/knowledge?q={query}&n=50" + (f"&project={project}" if project else "")
    return {h["id"]: h for h in client.get(url).get_json()["hits"]}


class TestEdit:
    def test_new_body_is_searchable_old_is_not(self, client, agents):
        old_word, new_word = "zq" + uuid.uuid4().hex[:8], "zq" + uuid.uuid4().hex[:8]
        entry = _add(client, agents["AKM"], f"{old_word} pricing note", title="Pricing")
        r = client.patch(f"/api/knowledge/{entry['id']}", json={"body": f"{new_word} pricing note, revised"},
                         headers=agents["AKM"])
        assert r.status_code == 200 and r.get_json()["body"].startswith(new_word)
        hit = _hit_ids(client, new_word)[entry["id"]]
        assert hit["body"].startswith(new_word) and hit["title"] == "Pricing"
        # the stored text is the new one; searching for the old word returns the new body, not the old
        old_hit = _hit_ids(client, old_word).get(entry["id"])
        assert old_hit is None or old_word not in old_hit["body"]

    def test_title_and_tags_only(self, client, agents):
        entry = _add(client, agents["AKM"], "body stays", title="Old", tags=["a"])
        r = client.patch(f"/api/knowledge/{entry['id']}", json={"title": "New", "tags": ["x", " y "]},
                         headers=agents["AKM"])
        data = r.get_json()
        assert (data["title"], data["body"], data["tags"]) == ("New", "body stays", '["x", "y"]')

    def test_project_survives_edit(self, client, agents):
        client.post("/api/projects", json={"name": "Alpha"}, headers=OPERATOR)
        word = "zq" + uuid.uuid4().hex[:8]
        entry = _add(client, agents["AKM"], f"{word} alpha fact", project="alpha")
        client.patch(f"/api/knowledge/{entry['id']}", json={"body": f"{word} alpha fact v2"}, headers=agents["AKM"])
        assert entry["id"] in _hit_ids(client, word, project="alpha")
        assert client.get(f"/api/knowledge/{entry['id']}").get_json()["project"] == "alpha"


class TestRules:
    def test_only_creator_or_admin(self, app, client, agents):
        entry = _add(client, agents["AKM"], "akm's note")
        r = client.patch(f"/api/knowledge/{entry['id']}", json={"title": "x"}, headers=agents["SVY"])
        assert r.status_code == 403
        sign_in_admin(app, client)
        with client.session_transaction() as s:
            s["csrf"] = "t"
        r = client.patch(f"/api/knowledge/{entry['id']}", json={"title": "edited by admin"},
                         headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200 and r.get_json()["title"] == "edited by admin"

    @pytest.mark.parametrize("payload", [{"body": "   "}, {"source": "x"}, {"tags": "not-a-list"}, {"title": 5}])
    def test_validation(self, client, agents, payload):
        entry = _add(client, agents["AKM"], "valid")
        assert client.patch(f"/api/knowledge/{entry['id']}", json=payload, headers=agents["AKM"]).status_code == 422
        assert client.get(f"/api/knowledge/{entry['id']}").get_json()["body"] == "valid"

    def test_unknown_entry_and_no_token(self, client, agents):
        assert client.patch("/api/knowledge/999", json={"title": "x"}, headers=agents["AKM"]).status_code == 404
        assert client.patch("/api/knowledge/999", json={"title": "x"}).status_code == 401


def test_page_has_edit_form(app, client):
    sign_in_admin(app, client)
    html = client.get("/knowledge").get_data(as_text=True)
    assert 'id="edit-entry"' in html and 'id="edit-body"' in html
