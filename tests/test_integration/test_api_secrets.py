"""
Integration tests for the Secrets Vault API endpoints.

Tests POST/GET /api/vault/secrets with real Flask test client + in-memory SQLite.
"""


def _register(client, name):
    resp = client.post("/api/agents/register", json={"name": name})
    return resp.get_json()["token"]


class TestStoreSecretApi:
    """POST /api/vault/secrets — store a secret. Requires a valid agent
    bearer token or the operator key."""

    def test_store_valid_secret(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/vault/secrets",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "name": "mailgun-key",
                                "value": "key-abc123def456",
                                "description": "Mailgun API key",
                            })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "stored"
        assert data["name"] == "mailgun-key"
        assert data["encrypted"] is True

    def test_store_without_token_returns_401(self, client):
        resp = client.post("/api/vault/secrets", json={
            "name": "mailgun-key",
            "value": "key-abc123def456",
        })
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "unauthorized"

    def test_store_with_operator_key(self, app, client):
        app.config["OPERATOR_KEY"] = "op-secret-123"

        resp = client.post("/api/vault/secrets",
                            headers={"Authorization": "Bearer op-secret-123"},
                            json={"name": "operator-key-secret", "value": "v"})
        assert resp.status_code == 201

    def test_store_missing_name(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/vault/secrets",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"value": "some-value"})
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["error"] == "validation_error"

    def test_store_missing_value(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/vault/secrets",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"name": "my-key"})
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["error"] == "validation_error"

    def test_store_with_access_scope(self, client):
        token = _register(client, "akm")

        resp = client.post("/api/vault/secrets",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "name": "gemini-key",
                                "value": "AIzaSy...",
                                "access_scope": ["akm", "slk"],
                            })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "stored"

    def test_store_duplicate_name(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/api/vault/secrets", headers=headers,
                     json={"name": "dup-key", "value": "first"})
        resp = client.post("/api/vault/secrets", headers=headers,
                            json={"name": "dup-key", "value": "second"})
        assert resp.status_code == 409
        data = resp.get_json()
        assert data["error"] == "conflict"


class TestRetrieveSecretApi:
    """GET /api/vault/secrets/<name> — retrieve a secret. Requires a valid
    agent bearer token or the operator key (which bypasses access_scope)."""

    def test_retrieve_allowed(self, client):
        akm_token = _register(client, "akm")
        svy_token = _register(client, "svy")

        client.post("/api/vault/secrets",
                     headers={"Authorization": f"Bearer {akm_token}"},
                     json={
                         "name": "my-api-key",
                         "value": "sk-12345",
                         "access_scope": ["svy"],
                     })

        resp = client.get("/api/vault/secrets/my-api-key",
                           headers={"Authorization": f"Bearer {svy_token}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "my-api-key"
        assert data["value"] == "sk-12345"

    def test_retrieve_denied(self, client):
        akm_token = _register(client, "akm")
        svy_token = _register(client, "svy")

        client.post("/api/vault/secrets",
                     headers={"Authorization": f"Bearer {akm_token}"},
                     json={
                         "name": "admin-secret",
                         "value": "admin-value",
                         "access_scope": ["akm"],
                     })

        resp = client.get("/api/vault/secrets/admin-secret",
                           headers={"Authorization": f"Bearer {svy_token}"})
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "access_denied"

    def test_retrieve_nonexistent(self, client):
        token = _register(client, "svy")

        resp = client.get("/api/vault/secrets/does-not-exist",
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "not_found"

    def test_retrieve_without_token_returns_401(self, client):
        resp = client.get("/api/vault/secrets/some-key")
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"] == "unauthorized"

    def test_retrieve_with_operator_key_bypasses_scope(self, app, client):
        akm_token = _register(client, "akm")
        app.config["OPERATOR_KEY"] = "op-secret-123"

        client.post("/api/vault/secrets",
                     headers={"Authorization": f"Bearer {akm_token}"},
                     json={
                         "name": "akm-only-secret",
                         "value": "top-secret",
                         "access_scope": ["akm"],
                     })

        resp = client.get("/api/vault/secrets/akm-only-secret",
                           headers={"Authorization": "Bearer op-secret-123"})
        assert resp.status_code == 200
        assert resp.get_json()["value"] == "top-secret"


class TestListSecretsApi:
    """GET /api/vault/secrets — list available secrets. Stays open (no auth)
    by design — see docs/superpowers/specs/2026-06-30-agent-token-auth-design.md."""

    def test_list_empty(self, client):
        resp = client.get("/api/vault/secrets?agent=svy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0

    def test_list_with_secrets(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}
        client.post("/api/vault/secrets", headers=headers,
                     json={"name": "key-1", "value": "val-1"})
        client.post("/api/vault/secrets", headers=headers,
                     json={"name": "key-2", "value": "val-2"})

        resp = client.get("/api/vault/secrets?agent=svy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 2
        names = [s["name"] for s in data["secrets"]]
        assert "key-1" in names
        assert "key-2" in names
        # Values should NOT be in the list response
        for s in data["secrets"]:
            assert "value" not in s

    def test_list_scoped(self, client):
        token = _register(client, "akm")
        headers = {"Authorization": f"Bearer {token}"}
        client.post("/api/vault/secrets", headers=headers,
                     json={"name": "public-key", "value": "pub"})
        client.post("/api/vault/secrets", headers=headers,
                     json={"name": "akm-only", "value": "secret", "access_scope": ["akm"]})

        resp = client.get("/api/vault/secrets?agent=svy")
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["secrets"]]
        assert "public-key" in names
        assert "akm-only" not in names
