"""Tests for app.server.create_app() config file loading."""

from app.server import create_app


def test_empty_vault_key_in_config_keeps_auto_generated_key(tmp_path):
    """An empty 'vault_key: \"\"' (as config.example.yaml recommends for
    'leave empty for auto') must not override the auto-generated key.

    Each call to _get_cipher() with a falsy master_key generates a brand
    new random Fernet key, so overwriting VAULT_KEY with "" breaks
    encrypt/decrypt round trips entirely.
    """
    config_file = tmp_path / "config.yaml"
    config_file.write_text('app:\n  vault_key: ""\n')

    app = create_app(config_path=str(config_file))

    assert app.config["VAULT_KEY"]


def test_operator_key_defaults_to_empty(tmp_path):
    """No operator_key configured means the operator-key auth path is disabled."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text('app:\n  vault_key: ""\n')

    app = create_app(config_path=str(config_file))

    assert app.config["OPERATOR_KEY"] == ""


def test_operator_key_from_config_is_applied(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text('app:\n  operator_key: "my-operator-secret"\n')

    app = create_app(config_path=str(config_file))

    assert app.config["OPERATOR_KEY"] == "my-operator-secret"
