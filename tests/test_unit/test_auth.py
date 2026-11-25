"""Tests for app.services.auth — bearer token verification and operator key."""

from app.services.auth import hash_token, authenticate


class TestHashToken:
    def test_same_input_same_hash(self):
        assert hash_token("abc123") == hash_token("abc123")

    def test_different_input_different_hash(self):
        assert hash_token("abc123") != hash_token("xyz789")


def _authenticate_with_headers(app, headers):
    with app.test_request_context(headers=headers):
        conn = app.config["DB_ENGINE"].connect()
        try:
            return authenticate(conn)
        finally:
            conn.close()


class TestAuthenticate:
    def test_valid_agent_token(self, app, client):
        resp = client.post("/api/agents/register", json={"name": "akm"})
        token = resp.get_json()["token"]

        agent_name, is_operator = _authenticate_with_headers(
            app, {"Authorization": f"Bearer {token}"}
        )

        assert agent_name == "akm"
        assert is_operator is False

    def test_missing_header(self, app):
        agent_name, is_operator = _authenticate_with_headers(app, {})

        assert agent_name is None
        assert is_operator is False

    def test_malformed_header(self, app):
        agent_name, is_operator = _authenticate_with_headers(
            app, {"Authorization": "not-a-bearer-token"}
        )

        assert agent_name is None
        assert is_operator is False

    def test_unknown_token(self, app):
        agent_name, is_operator = _authenticate_with_headers(
            app, {"Authorization": "Bearer nonexistent-token"}
        )

        assert agent_name is None
        assert is_operator is False

    def test_operator_key_match(self, app):
        app.config["OPERATOR_KEY"] = "op-secret-123"

        agent_name, is_operator = _authenticate_with_headers(
            app, {"Authorization": "Bearer op-secret-123"}
        )

        assert agent_name is None
        assert is_operator is True

    def test_operator_key_configured_but_wrong_value(self, app):
        app.config["OPERATOR_KEY"] = "op-secret-123"

        agent_name, is_operator = _authenticate_with_headers(
            app, {"Authorization": "Bearer wrong-value"}
        )

        assert agent_name is None
        assert is_operator is False
