"""Test infrastructure — fixtures and configuration."""

import os

# Must run before anything imports app.server: its module-level `app = create_app()`
# runs at import time, and with no vault/session key configured it would persist a
# real vault.key / session.key into data/. (The key persistence tests unset these.)
os.environ.setdefault("IMUA_VAULT_KEY", "test-only-vault-key")
os.environ.setdefault("IMUA_SECRET_KEY", "test-only-session-key")

import pytest
from unittest.mock import MagicMock
from datetime import datetime
from app.server import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create a Flask app instance with in-memory SQLite for testing."""
    # IMUA_TESTING=1 skips git init + uses in-memory Chroma (no disk writes).
    monkeypatch.setenv("IMUA_TESTING", "1")
    application = create_app(config_path=None)
    application.config["TESTING"] = True
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    application.config["DOCS_STORAGE_DIR"] = str(tmp_path / "docs")
    # Re-init DB with in-memory path
    from app.models import init_db
    init_db(application)
    return application


@pytest.fixture
def client(app):
    """Test client for HTTP requests."""
    return app.test_client()


def sign_in_admin(app, client, username="testadmin"):
    """Give this test client a signed-in admin session (dashboard pages need one, task 5.7)."""
    import time
    from app.services.admin_accounts import create_admin, get_admin
    with app.config["DB_ENGINE"].begin() as conn:
        admin = get_admin(conn, username) or create_admin(conn, username, "test-admin-password")
    now = int(time.time())
    with client.session_transaction() as s:
        s.update(admin_id=admin["id"], login_at=now, seen_at=now)
    return client


@pytest.fixture
def admin_client(app, client):
    """A test client already signed in as an admin."""
    return sign_in_admin(app, client)


@pytest.fixture
def runner(app):
    """CLI test runner."""
    return app.test_cli_runner()


@pytest.fixture
def mock_conn():
    """A mock database connection for service-layer unit tests."""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    conn.execute.return_value.one_or_none.return_value = None
    conn.execute.return_value.one.return_value = MagicMock(
        _asdict=lambda: {"id": 0, "sender": "test", "recipient": "test",
                         "msg_type": "direct", "body": "", "status": "pending",
                         "created_at": datetime.utcnow()}
    )
    conn.execute.return_value.inserted_primary_key = [0]
    return conn
