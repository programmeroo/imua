"""
Vault master key persistence — task 4.7.

Before this fix, create_app() generated a fresh random VAULT_KEY on every start
unless one was configured, so every hub restart/rebuild made all stored secrets
undecryptable. The auto-generated key is now persisted next to the database.
"""

import os
import stat

import pytest
from cryptography.fernet import Fernet

from app.server import create_app


def _make_app(tmp_path, monkeypatch, extra_cfg=""):
    monkeypatch.delenv("IMUA_TESTING", raising=False)
    monkeypatch.delenv("IMUA_VAULT_KEY", raising=False)
    db = (tmp_path / "database" / "imua.db").as_posix()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f'database:\n  path: "{db}"\n{extra_cfg}')
    return create_app(config_path=str(cfg))


def _key_file(tmp_path):
    return tmp_path / "database" / "vault.key"


def test_key_is_generated_once_and_reused_across_restarts(tmp_path, monkeypatch):
    first = _make_app(tmp_path, monkeypatch).config["VAULT_KEY"]
    second = _make_app(tmp_path, monkeypatch).config["VAULT_KEY"]
    assert first == second
    assert _key_file(tmp_path).read_text().strip() == first
    Fernet(first)  # valid Fernet key


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_key_file_is_owner_only(tmp_path, monkeypatch):
    _make_app(tmp_path, monkeypatch)
    assert stat.S_IMODE(_key_file(tmp_path).stat().st_mode) == 0o600


def test_secret_survives_restart(tmp_path, monkeypatch):
    """End to end: store via the API, 'restart' the hub, retrieve via the API."""
    app = _make_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/vault/secrets", json={"name": "k", "value": "v1"},
                       headers=auth).status_code == 201

    restarted = _make_app(tmp_path, monkeypatch).test_client()
    resp = restarted.get("/api/vault/secrets/k", headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()["value"] == "v1"


def test_configured_key_wins_and_no_file_is_written(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, 'app:\n  vault_key: "configured-key"\n')
    assert app.config["VAULT_KEY"] == "configured-key"
    assert not _key_file(tmp_path).exists()


def test_env_key_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("IMUA_TESTING", raising=False)
    monkeypatch.setenv("IMUA_VAULT_KEY", "env-key")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f'database:\n  path: "{(tmp_path / "database" / "imua.db").as_posix()}"\n')
    assert create_app(config_path=str(cfg)).config["VAULT_KEY"] == "env-key"
    assert not _key_file(tmp_path).exists()


def test_empty_key_file_refuses_to_start(tmp_path, monkeypatch):
    """An empty key file means the key was lost/truncated — silently generating a new
    one would orphan every secret, so fail loudly instead."""
    _key_file(tmp_path).parent.mkdir(parents=True)
    _key_file(tmp_path).write_text("")
    with pytest.raises(RuntimeError, match="vault key file"):
        _make_app(tmp_path, monkeypatch)


def test_secret_from_old_key_returns_409_not_500(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = client.post("/api/agents/register", json={"name": "AKM"}).get_json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    client.post("/api/vault/secrets", json={"name": "old", "value": "x"}, headers=auth)

    _key_file(tmp_path).write_text(Fernet.generate_key().decode())  # simulate a lost key
    resp = _make_app(tmp_path, monkeypatch).test_client().get("/api/vault/secrets/old", headers=auth)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "undecryptable"
