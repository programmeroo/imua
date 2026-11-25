"""
Unit tests for the Secrets Vault service layer.
"""

import json
from unittest.mock import patch, MagicMock

import pytest
from cryptography.fernet import Fernet

from app.services.secrets_vault import (
    store_secret, retrieve_secret, list_available_secrets, _get_cipher
)

TEST_KEY = Fernet.generate_key().decode()


class TestGetCipher:
    """Test Fernet cipher initialization."""

    def test_with_valid_key(self):
        cipher = _get_cipher(TEST_KEY)
        assert cipher is not None
        # Should be able to encrypt/decrypt
        token = cipher.encrypt(b"test")
        assert cipher.decrypt(token) == b"test"

    def test_with_string_key(self):
        cipher = _get_cipher("my-weak-key")
        token = cipher.encrypt(b"hello")
        assert cipher.decrypt(token) == b"hello"

    def test_missing_key_raises(self):
        """No silent per-call random key: anything encrypted with one could never
        be decrypted again."""
        with pytest.raises(ValueError):
            _get_cipher()


class TestStoreSecret:
    """Test storing encrypted secrets."""

    def test_store_minimal(self, mock_conn):
        mock_conn.execute.return_value.inserted_primary_key = [1]

        result = store_secret(mock_conn, name="mailgun-key",
                               value="key-abc123", master_key=TEST_KEY)

        assert result["status"] == "stored"
        assert result["name"] == "mailgun-key"
        assert result["encrypted"] is True

    def test_store_with_scope(self, mock_conn):
        mock_conn.execute.return_value.inserted_primary_key = [2]

        result = store_secret(mock_conn, name="gemini-key",
                               value="AIzaSy...",
                               access_scope=["akm", "slk"],
                               master_key=TEST_KEY)

        assert result["status"] == "stored"
        assert result["name"] == "gemini-key"


class TestRetrieveSecret:
    """Test retrieving and decrypting secrets."""

    def test_retrieve_allowed_agent(self, mock_conn):
        # Encrypt a value first
        cipher = Fernet(TEST_KEY)
        encrypted = cipher.encrypt(b"key-abc123").decode()
        scope = json.dumps(["akm", "svy"])

        mock_row = MagicMock(_asdict=lambda: {
            "name": "mailgun-key",
            "encrypted_value": encrypted,
            "description": "Mailgun API key",
            "access_scope": scope,
            "last_access": None,
        })
        mock_conn.execute.return_value.one_or_none.return_value = mock_row

        result = retrieve_secret(mock_conn, "mailgun-key",
                                  agent_name="akm", master_key=TEST_KEY)

        assert result is not None
        assert result["name"] == "mailgun-key"
        assert result["value"] == "key-abc123"
        assert result["description"] == "Mailgun API key"

    def test_retrieve_denied_agent(self, mock_conn):
        cipher = Fernet(TEST_KEY)
        encrypted = cipher.encrypt(b"secret-value").decode()
        scope = json.dumps(["akm"])

        mock_row = MagicMock(_asdict=lambda: {
            "name": "admin-secret",
            "encrypted_value": encrypted,
            "description": "Admin only",
            "access_scope": scope,
            "last_access": None,
        })
        mock_conn.execute.return_value.one_or_none.return_value = mock_row

        result = retrieve_secret(mock_conn, "admin-secret",
                                  agent_name="svy", master_key=TEST_KEY)

        assert result is None  # Access denied

    def test_retrieve_nonexistent(self, mock_conn):
        mock_conn.execute.return_value.one_or_none.return_value = None

        result = retrieve_secret(mock_conn, "does-not-exist",
                                  agent_name="akm", master_key=TEST_KEY)

        assert result is None

    def test_retrieve_with_bypass_scope_ignores_restriction(self, mock_conn):
        cipher = Fernet(TEST_KEY)
        encrypted = cipher.encrypt(b"secret-value").decode()
        scope = json.dumps(["akm"])

        mock_row = MagicMock(_asdict=lambda: {
            "name": "admin-secret",
            "encrypted_value": encrypted,
            "description": "Admin only",
            "access_scope": scope,
            "last_access": None,
        })
        mock_conn.execute.return_value.one_or_none.return_value = mock_row

        result = retrieve_secret(mock_conn, "admin-secret",
                                  agent_name=None, master_key=TEST_KEY,
                                  bypass_scope=True)

        assert result is not None
        assert result["value"] == "secret-value"


class TestListSecrets:
    """Test listing available secrets."""

    def test_list_no_scope_returns_all(self, mock_conn):
        cipher = Fernet(TEST_KEY)
        encrypted = cipher.encrypt(b"val").decode()

        mock_conn.execute.return_value.fetchall.side_effect = [
            [("key-1",), ("key-2",)],   # list_secret_names
        ]
        mock_conn.execute.return_value.one_or_none.side_effect = [
            MagicMock(_asdict=lambda: {
                "name": "key-1", "encrypted_value": encrypted,
                "description": "Key 1", "access_scope": "[]",
            }),
            MagicMock(_asdict=lambda: {
                "name": "key-2", "encrypted_value": encrypted,
                "description": "Key 2", "access_scope": "[]",
            }),
        ]

        result = list_available_secrets(mock_conn, agent_name="svy")
        assert len(result) == 2
        assert result[0]["name"] == "key-1"
        assert result[1]["name"] == "key-2"

    def test_list_scoped_filters(self, mock_conn):
        cipher = Fernet(TEST_KEY)
        encrypted = cipher.encrypt(b"val").decode()

        mock_conn.execute.return_value.fetchall.side_effect = [
            [("akm-only",), ("public",)],
        ]
        mock_conn.execute.return_value.one_or_none.side_effect = [
            MagicMock(_asdict=lambda: {
                "name": "akm-only", "encrypted_value": encrypted,
                "description": "AKM only", "access_scope": '["akm"]',
            }),
            MagicMock(_asdict=lambda: {
                "name": "public", "encrypted_value": encrypted,
                "description": "Public", "access_scope": "[]",
            }),
        ]

        result = list_available_secrets(mock_conn, agent_name="svy")
        # svy should only see "public", not "akm-only"
        names = [s["name"] for s in result]
        assert "public" in names
        assert "akm-only" not in names

    def test_list_with_bypass_scope_returns_all(self, mock_conn):
        cipher = Fernet(TEST_KEY)
        encrypted = cipher.encrypt(b"val").decode()

        mock_conn.execute.return_value.fetchall.side_effect = [
            [("akm-only",), ("public",)],
        ]
        mock_conn.execute.return_value.one_or_none.side_effect = [
            MagicMock(_asdict=lambda: {
                "name": "akm-only", "encrypted_value": encrypted,
                "description": "AKM only", "access_scope": '["akm"]',
            }),
            MagicMock(_asdict=lambda: {
                "name": "public", "encrypted_value": encrypted,
                "description": "Public", "access_scope": "[]",
            }),
        ]

        result = list_available_secrets(mock_conn, agent_name=None, bypass_scope=True)
        names = [s["name"] for s in result]
        assert "akm-only" in names
        assert "public" in names
