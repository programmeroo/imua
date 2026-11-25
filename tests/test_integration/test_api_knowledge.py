"""Integration tests for the Knowledge Base API."""

import os

import pytest

# ChromaDB downloads an embedding model on first use. Skip these tests
# if running offline / on a machine that can't reach the model host.
try:
    import chromadb  # noqa: F401
except ImportError:
    pytest.skip("chromadb not installed", allow_module_level=True)


def _register(client, name="akm"):
    resp = client.post("/api/agents/register", json={"name": name})
    return resp.get_json()["token"]


class TestAddKnowledgeEntryApi:
    def test_add_returns_201_with_metadata(self, client):
        token = _register(client)
        resp = client.post(
            "/api/knowledge",
            json={"body": "The capital of Hawaii is Honolulu.", "title": "Hawaii fact"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["body"] == "The capital of Hawaii is Honolulu."
        assert data["title"] == "Hawaii fact"
        assert data["agent"] == "akm"
        assert data["source"] == "manual"
        assert data["chroma_id"]

    def test_add_missing_body_returns_422(self, client):
        token = _register(client)
        resp = client.post("/api/knowledge", json={},
                            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    def test_add_without_token_returns_401(self, client):
        resp = client.post("/api/knowledge", json={"body": "x"})
        assert resp.status_code == 401

    def test_add_with_tags_stores_tags_json(self, client):
        token = _register(client)
        resp = client.post(
            "/api/knowledge",
            json={"body": "Tagged fact", "tags": ["geo", "usa"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        import json as _json
        assert _json.loads(resp.get_json()["tags"]) == ["geo", "usa"]


class TestSearchKnowledgeApi:
    def test_search_returns_relevant_hits(self, client):
        token = _register(client)
        client.post("/api/knowledge",
                    json={"body": "Python is a programming language."},
                    headers={"Authorization": f"Bearer {token}"})
        client.post("/api/knowledge",
                    json={"body": "Hawaii has 137 islands."},
                    headers={"Authorization": f"Bearer {token}"})

        resp = client.get("/api/knowledge?q=islands")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1
        # The Hawaii entry should be the top hit
        assert any("Hawaii" in (h.get("body") or "") for h in data["hits"])

    def test_search_missing_query_returns_422(self, client):
        resp = client.get("/api/knowledge")
        assert resp.status_code == 422

    def test_search_n_parameter_limits_results(self, client):
        token = _register(client)
        for i in range(5):
            client.post("/api/knowledge",
                        json={"body": f"fact number {i}"},
                        headers={"Authorization": f"Bearer {token}"})

        resp = client.get("/api/knowledge?q=fact&n=2")
        data = resp.get_json()
        assert data["count"] <= 2

    def test_search_open_no_token_required(self, client):
        # Search must work without auth — it powers the dashboard's search box.
        token = _register(client)
        client.post("/api/knowledge",
                    json={"body": "searchable fact"},
                    headers={"Authorization": f"Bearer {token}"})
        resp = client.get("/api/knowledge?q=searchable")
        assert resp.status_code == 200


class TestGetEntryApi:
    def test_get_returns_entry(self, client):
        token = _register(client)
        create = client.post("/api/knowledge",
                             json={"body": "fetchable"},
                             headers={"Authorization": f"Bearer {token}"})
        eid = create.get_json()["id"]
        resp = client.get(f"/api/knowledge/{eid}")
        assert resp.status_code == 200
        assert resp.get_json()["body"] == "fetchable"

    def test_get_unknown_returns_404(self, client):
        resp = client.get("/api/knowledge/9999")
        assert resp.status_code == 404


class TestDeleteEntryApi:
    def test_creator_can_delete_their_entry(self, client):
        token = _register(client, "akm")
        create = client.post("/api/knowledge",
                             json={"body": "mine to delete"},
                             headers={"Authorization": f"Bearer {token}"})
        eid = create.get_json()["id"]
        resp = client.delete(f"/api/knowledge/{eid}",
                             headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert client.get(f"/api/knowledge/{eid}").status_code == 404

    def test_other_agent_cannot_delete(self, client):
        token = _register(client, "akm")
        create = client.post("/api/knowledge",
                             json={"body": "not yours"},
                             headers={"Authorization": f"Bearer {token}"})
        eid = create.get_json()["id"]

        other = _register(client, "svy")
        resp = client.delete(f"/api/knowledge/{eid}",
                             headers={"Authorization": f"Bearer {other}"})
        assert resp.status_code == 403

    def test_delete_without_token_returns_401(self, client):
        token = _register(client)
        create = client.post("/api/knowledge",
                             json={"body": "x"},
                             headers={"Authorization": f"Bearer {token}"})
        eid = create.get_json()["id"]
        resp = client.delete(f"/api/knowledge/{eid}")
        assert resp.status_code == 401

    def test_delete_unknown_returns_404(self, client):
        token = _register(client)
        resp = client.delete("/api/knowledge/9999",
                             headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404


class TestKnowledgeStatsApi:
    def test_stats_returns_count(self, client):
        token = _register(client)
        for i in range(3):
            client.post("/api/knowledge",
                        json={"body": f"stat fact {i}"},
                        headers={"Authorization": f"Bearer {token}"})
        resp = client.get("/api/knowledge/stats")
        assert resp.status_code == 200
        assert resp.get_json()["entry_count"] >= 3


class TestKnowledgeRecentApi:
    def test_recent_lists_added_entries(self, client):
        token = _register(client)
        client.post("/api/knowledge",
                    json={"body": "first", "title": "One"},
                    headers={"Authorization": f"Bearer {token}"})
        client.post("/api/knowledge",
                    json={"body": "second", "title": "Two"},
                    headers={"Authorization": f"Bearer {token}"})
        resp = client.get("/api/knowledge/recent")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 2
        titles = [e["title"] for e in data["entries"]]
        assert "One" in titles and "Two" in titles