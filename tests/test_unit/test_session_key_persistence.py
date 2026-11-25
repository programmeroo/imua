"""
Session signing key persistence — task 5.3 (docs/imua_admin_security_plan_v1.md).

Flask signs session cookies with SECRET_KEY. It used to be random per start,
which would sign every admin out on each restart. Now: config → env → a
session.key file next to the database, generated once.
"""

import os
import stat

import pytest

from app.server import create_app


def _make_app(tmp_path, monkeypatch, extra_cfg=""):
    monkeypatch.delenv("IMUA_TESTING", raising=False)
    monkeypatch.delenv("IMUA_SECRET_KEY", raising=False)
    db = (tmp_path / "database" / "imua.db").as_posix()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f'database:\n  path: "{db}"\n{extra_cfg}')
    return create_app(config_path=str(cfg))


def _key_file(tmp_path):
    return tmp_path / "database" / "session.key"


def test_generated_once_and_reused_across_restarts(tmp_path, monkeypatch):
    first = _make_app(tmp_path, monkeypatch).config["SECRET_KEY"]
    second = _make_app(tmp_path, monkeypatch).config["SECRET_KEY"]
    assert first == second and len(first) == 64
    assert _key_file(tmp_path).read_text().strip() == first


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_key_file_is_owner_only(tmp_path, monkeypatch):
    _make_app(tmp_path, monkeypatch)
    assert stat.S_IMODE(_key_file(tmp_path).stat().st_mode) == 0o600


def test_signed_session_survives_restart(tmp_path, monkeypatch):
    """A cookie signed before a restart is still accepted after it."""
    app = _make_app(tmp_path, monkeypatch)
    cookie = app.session_interface.get_signing_serializer(app).dumps({"admin_id": 1})
    restarted = _make_app(tmp_path, monkeypatch)
    assert restarted.session_interface.get_signing_serializer(restarted).loads(cookie) == {"admin_id": 1}


def test_configured_key_wins_and_no_file_is_written(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, 'app:\n  secret_key: "configured-secret"\n')
    assert app.config["SECRET_KEY"] == "configured-secret"
    assert not _key_file(tmp_path).exists()


def test_placeholder_in_config_is_ignored(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, 'app:\n  secret_key: "CHANGE_ME_TO_A_RANDOM_STRING"\n')
    assert app.config["SECRET_KEY"] != "CHANGE_ME_TO_A_RANDOM_STRING"
    assert _key_file(tmp_path).exists()


def test_env_key_wins(tmp_path, monkeypatch):
    _make_app(tmp_path, monkeypatch)  # clears env; then set it
    monkeypatch.setenv("IMUA_SECRET_KEY", "env-secret")
    cfg = tmp_path / "config.yaml"
    assert create_app(config_path=str(cfg)).config["SECRET_KEY"] == "env-secret"


def test_empty_key_file_refuses_to_start(tmp_path, monkeypatch):
    _key_file(tmp_path).parent.mkdir(parents=True)
    _key_file(tmp_path).write_text("")
    with pytest.raises(RuntimeError, match="session key file"):
        _make_app(tmp_path, monkeypatch)
