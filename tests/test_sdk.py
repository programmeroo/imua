"""Tests for the Hermes SDK (ImuaClient).

register()/heartbeat()/store_secret()/get_secret() are tested against a
mocked HTTP transport — the routes they call (Agent Registry, Secrets Vault)
don't exist on main yet. send_message()/check_messages() are tested against
the real Flask app (Message Bus is implemented) via a live local server.
"""

import io
import json
import threading
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.serving import make_server

from app.models import init_db
from app.server import create_app
from sdk.imua import ImuaClient, ImuaError


@pytest.fixture
def live_server(tmp_path):
    """Run the real Flask app on a local port for true HTTP round-trip tests.

    Uses a temp-file SQLite DB rather than :memory: — the live server
    handles requests on a background thread, and SQLAlchemy's sqlite
    in-memory mode is thread-local, so a second thread would see an
    empty, table-less database.
    """
    application = create_app(config_path=None)
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'imua_test.db'}"
    init_db(application)

    server = make_server("127.0.0.1", 0, application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


def _mock_response(status: int, body: dict):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.status = status
    resp.read.return_value = json.dumps(body).encode()
    return resp


class TestRegister:
    @patch("sdk.imua.urlopen")
    def test_register_returns_token_and_stores_state(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            201,
            {
                "status": "registered",
                "name": "akm",
                "token": "imua_tkn_abc123",
                "agent": {"name": "akm", "online": True},
            },
        )

        client = ImuaClient(base_url="http://hub:5000")
        token = client.register("akm", capabilities=["code.write"], host="10.0.0.5", port=9000)

        assert token == "imua_tkn_abc123"
        assert client.token == "imua_tkn_abc123"
        assert client.name == "akm"

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "http://hub:5000/api/agents/register"
        assert request.get_method() == "POST"
        sent_body = json.loads(request.data)
        assert sent_body == {
            "name": "akm",
            "capabilities": ["code.write"],
            "host": "10.0.0.5",
            "port": 9000,
        }


class TestHeartbeat:
    @patch("sdk.imua.urlopen")
    def test_heartbeat_patches_with_auth_header_and_returns_response(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            200,
            {
                "status": "ok",
                "next_heartbeat_in": 60,
                "last_seen": "2026-06-20T12:01:00Z",
            },
        )

        client = ImuaClient(base_url="http://hub:5000", name="akm", token="imua_tkn_abc123")
        result = client.heartbeat()

        assert result == {
            "status": "ok",
            "next_heartbeat_in": 60,
            "last_seen": "2026-06-20T12:01:00Z",
        }

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "http://hub:5000/api/agents/akm/heartbeat"
        assert request.get_method() == "PATCH"
        assert request.headers["Authorization"] == "Bearer imua_tkn_abc123"


class TestSecretsVault:
    @patch("sdk.imua.urlopen")
    def test_store_secret_posts_name_and_value(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            201,
            {
                "status": "stored",
                "name": "mailgun-api-key",
                "encrypted": True,
                "created_at": "2026-06-20T12:10:00Z",
            },
        )

        client = ImuaClient(base_url="http://hub:5000", name="akm", token="imua_tkn_abc123")
        result = client.store_secret("mailgun-api-key", "key-abc123def456")

        assert result["status"] == "stored"

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "http://hub:5000/api/vault/secrets"
        assert request.get_method() == "POST"
        assert json.loads(request.data) == {
            "name": "mailgun-api-key",
            "value": "key-abc123def456",
        }

    @patch("sdk.imua.urlopen")
    def test_get_secret_returns_decrypted_value(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            200,
            {
                "name": "mailgun-api-key",
                "value": "key-abc123def456",
                "last_access": "2026-06-20T12:10:00Z",
            },
        )

        client = ImuaClient(base_url="http://hub:5000", name="akm", token="imua_tkn_abc123")
        value = client.get_secret("mailgun-api-key")

        assert value == "key-abc123def456"

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "http://hub:5000/api/vault/secrets/mailgun-api-key"
        assert request.get_method() == "GET"


class TestSendMessageLive:
    def test_send_message_returns_message_id(self, live_server):
        client = ImuaClient(base_url=live_server)
        client.register("akm")

        msg_id = client.send_message("svy", "Can you review my PR?")

        assert isinstance(msg_id, int)


class TestCheckMessagesLive:
    def test_check_messages_returns_sent_message(self, live_server):
        sender = ImuaClient(base_url=live_server)
        sender.register("akm")
        receiver = ImuaClient(base_url=live_server, name="svy")
        sender.send_message("svy", "Can you review my PR?")

        messages = receiver.check_messages()

        assert len(messages) == 1
        assert messages[0]["body"] == "Can you review my PR?"
        assert messages[0]["sender"] == "akm"

    def test_check_messages_empty_when_none_sent(self, live_server):
        receiver = ImuaClient(base_url=live_server, name="svy")

        messages = receiver.check_messages()

        assert messages == []


class TestMarkReadLive:
    def test_unread_then_mark_read_round_trip(self, live_server):
        sender = ImuaClient(base_url=live_server)
        sender.register("akm")
        receiver = ImuaClient(base_url=live_server)
        receiver.register("svy")
        ids = [sender.send_message("svy", f"m{i}") for i in range(3)]

        assert len(receiver.check_messages(unread=True)) == 3

        result = receiver.mark_read(ids[:2])
        assert result == {"marked": sorted(ids[:2]), "skipped": []}
        assert [m["id"] for m in receiver.check_messages(unread=True)] == [ids[2]]

        receiver.mark_read(ids[2])  # a single id is accepted too
        assert receiver.check_messages(unread=True) == []
        assert len(receiver.check_messages()) == 3  # default still returns everything

    def test_cannot_mark_someone_elses_message(self, live_server):
        sender = ImuaClient(base_url=live_server)
        sender.register("akm")
        other = ImuaClient(base_url=live_server)
        other.register("slk")
        msg_id = sender.send_message("svy", "not for slk")

        assert other.mark_read([msg_id]) == {"marked": [], "skipped": [msg_id]}


class TestRegisterAndHeartbeatLive:
    def test_register_then_heartbeat_against_real_endpoints(self, live_server):
        client = ImuaClient(base_url=live_server)

        token = client.register("akm", capabilities=["code.write"], host="10.0.0.5", port=9000)
        result = client.heartbeat()

        assert token
        assert result["status"] == "online"
        assert result["agent"] == "akm"


class TestSecretsVaultRoundTripLive:
    def test_store_then_get_secret_returns_original_value(self, live_server):
        client = ImuaClient(base_url=live_server)
        client.register("akm")
        client.store_secret("mailgun-api-key", "key-abc123def456")

        value = client.get_secret("mailgun-api-key")

        assert value == "key-abc123def456"


class TestRequestErrorHandling:
    @patch("sdk.imua.urlopen")
    def test_non_2xx_response_raises_imua_error_with_status_code(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://hub:5000/api/agents/register",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=io.BytesIO(json.dumps({"error": "duplicate_name"}).encode()),
        )

        client = ImuaClient(base_url="http://hub:5000")

        with pytest.raises(ImuaError) as exc_info:
            client.register("akm")

        assert exc_info.value.status_code == 409


def test_projects_empty_and_unknown(live_server):
    """Task 6.9: no projects yet → []; an unknown slug raises ImuaError with 404."""
    agent = ImuaClient(base_url=live_server)
    agent.register("AKM")
    assert agent.list_projects() == []

    with pytest.raises(ImuaError) as exc:
        agent.get_project("nope")
    assert exc.value.status_code == 404


def test_projects_with_data(tmp_path):
    """list_projects / get_project / list_project_items with a project, an agent and a task."""
    application = create_app(config_path=None)
    application.config["TESTING"] = True
    application.config["OPERATOR_KEY"] = "op-key"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'imua_test.db'}"
    init_db(application)
    server = make_server("127.0.0.1", 0, application)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        admin = ImuaClient(base_url=url, token="op-key")
        admin._request("POST", "/api/projects", body={"name": "Lead Gen"})
        agent = ImuaClient(base_url=url)
        agent.register("AKM")
        admin._request("PUT", "/api/projects/lead-gen/agents/AKM")
        task = agent._request("POST", "/api/tasks", body={"type": "build", "title": "Hero",
                                                          "assigned_to": "AKM", "project": "lead-gen"})

        assert [p["slug"] for p in agent.list_projects()] == ["lead-gen"]
        assert agent.list_projects(status="archived") == []
        project = agent.get_project("Lead-Gen")
        assert project["agents"] == ["AKM"] and project["counts"]["task"] == 1
        assert [t["id"] for t in agent.list_project_items("lead-gen", "task")] == [task["id"]]
    finally:
        server.shutdown()
