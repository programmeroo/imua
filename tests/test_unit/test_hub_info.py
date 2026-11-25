"""Tests for LAN-IP detection and the /api/health hub_url field.

Client-side code (agents.js's invite command, settings.js's host
display) used to read location.hostname, which reflects whatever the
operator typed in their own browser — "localhost" if they're on the
hub machine — not the address other machines on the LAN need to
actually reach the hub. This makes the server the source of truth.
"""

import re

from app.server import _detect_lan_ip, create_app
from conftest import sign_in_admin  # dashboard pages need a signed-in admin (task 5.7)


def test_detect_lan_ip_returns_an_ip_address():
    ip = _detect_lan_ip()
    assert re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip)


def test_health_includes_hub_url(client):
    resp = client.get("/api/health")
    data = resp.get_json()
    assert "hub_url" in data
    assert re.match(r"^http://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", data["hub_url"])


def test_advertise_host_overridable_via_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("app:\n  advertise_host: \"10.0.0.42\"\n")

    app = create_app(config_path=str(config_file))

    assert app.config["ADVERTISE_HOST"] == "10.0.0.42"


def test_version_defaults_to_0_1_0_without_config():
    app = create_app(config_path="does-not-exist.yaml")
    assert app.config["VERSION"] == "0.1.0"


def test_version_overridable_via_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("app:\n  version: \"1.1.0\"\n")

    app = create_app(config_path=str(config_file))

    assert app.config["VERSION"] == "1.1.0"


def test_health_version_matches_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("app:\n  version: \"1.1.0\"\n")
    app = create_app(config_path=str(config_file))
    app.config["TESTING"] = True

    resp = app.test_client().get("/api/health")

    assert resp.get_json()["version"] == "1.1.0"


def test_sidebar_shows_configured_version(tmp_path, monkeypatch):
    """The sidebar's version tag (base.html) must track app.config["VERSION"],
    not a hardcoded string — this regressed once already (v0.1.0 baked into
    the template while config.yaml's version field was silently unused)."""
    from app.models import init_db

    monkeypatch.setenv("IMUA_TESTING", "1")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("app:\n  version: \"1.1.0\"\n")
    app = create_app(config_path=str(config_file))
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["DOCS_STORAGE_DIR"] = str(tmp_path / "docs")
    init_db(app)

    resp = sign_in_admin(app, app.test_client()).get("/")

    assert b"v1.1.0" in resp.data


def test_dashboard_has_no_hardcoded_version(tmp_path, monkeypatch):
    """Every version string on the dashboard must come from config — the activity
    feed's placeholder and the JS 'Dashboard loaded' entry hardcoded v0.1.0."""
    from pathlib import Path
    from app.models import init_db

    monkeypatch.setenv("IMUA_TESTING", "1")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("app:\n  version: \"9.8.7\"\n")
    app = create_app(config_path=str(config_file))
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["DOCS_STORAGE_DIR"] = str(tmp_path / "docs")
    init_db(app)

    html = sign_in_admin(app, app.test_client()).get("/").data
    assert b"v0.1.0" not in html
    assert html.count(b"v9.8.7") >= 2  # sidebar + activity feed placeholder

    main_js = Path(app.static_folder, "js", "main.js").read_text(encoding="utf-8")
    assert "v0.1.0" not in main_js
