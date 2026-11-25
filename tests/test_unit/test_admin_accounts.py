"""
Admin accounts — task 5.2 (docs/imua_admin_security_plan_v1.md).
Service rules (app/services/admin_accounts.py) and scripts/create_admin.py.
"""

import io
import os
import sys

import pytest
from sqlalchemy import create_engine

from app.models.admin_user import metadata as admin_meta
from app.services.admin_accounts import (AdminAccountError, count_admins, create_admin,
                                         get_admin, set_password, verify_login)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import create_admin as script  # noqa: E402

GOOD = "correct horse battery"


@pytest.fixture
def conn():
    engine = create_engine("sqlite:///:memory:")
    admin_meta.create_all(engine)
    with engine.begin() as c:
        yield c


class TestService:
    def test_create_and_verify(self, conn):
        admin = create_admin(conn, "Admin", GOOD)
        assert admin["username"] == "admin"  # case-insensitive, stored lowercase
        assert verify_login(conn, "ADMIN", GOOD)["id"] == admin["id"]
        assert count_admins(conn) == 1

    def test_password_stored_as_scrypt_hash_only(self, conn):
        create_admin(conn, "admin", GOOD)
        stored = get_admin(conn, "admin")["password_hash"]
        assert stored.startswith("scrypt:") and GOOD not in stored

    def test_wrong_password_or_unknown_user(self, conn):
        create_admin(conn, "admin", GOOD)
        assert verify_login(conn, "admin", GOOD + "x") is None
        assert verify_login(conn, "nobody", GOOD) is None
        assert verify_login(conn, "admin", None) is None

    @pytest.mark.parametrize("password", ["short", "x" * 11, "x" * 257, None])
    def test_password_policy(self, conn, password):
        with pytest.raises(AdminAccountError):
            create_admin(conn, "admin", password)

    @pytest.mark.parametrize("username", ["", "ab", "-admin", "ad min", "a" * 65, "admin!"])
    def test_username_rules(self, conn, username):
        with pytest.raises(AdminAccountError):
            create_admin(conn, username, GOOD)

    def test_duplicate_rejected(self, conn):
        create_admin(conn, "admin", GOOD)
        with pytest.raises(AdminAccountError, match="already exists"):
            create_admin(conn, "ADMIN", GOOD)

    def test_disabled_admin_cannot_log_in_until_reset(self, conn):
        admin = create_admin(conn, "admin", GOOD)
        from app.models.admin_user import admin_users
        conn.execute(admin_users.update().where(admin_users.c.id == admin["id"]).values(disabled=True))
        assert verify_login(conn, "admin", GOOD) is None
        set_password(conn, "admin", "a brand new password", enable=True)
        assert verify_login(conn, "admin", GOOD) is None
        assert verify_login(conn, "admin", "a brand new password")

    def test_set_password_unknown_admin(self, conn):
        with pytest.raises(AdminAccountError, match="No admin"):
            set_password(conn, "ghost", GOOD)


class TestScript:
    @pytest.fixture
    def db(self, tmp_path):
        path = tmp_path / "imua.db"
        create_engine(f"sqlite:///{path}").connect().close()  # an existing hub database
        return str(path)

    def _run(self, monkeypatch, db, password, *args):
        monkeypatch.setattr(sys, "stdin", io.StringIO(password + "\n"))
        return script.main(["--db", db, "--password-stdin", *args])

    def _conn(self, db):
        return create_engine(f"sqlite:///{db}").connect()

    def test_creates_admin(self, monkeypatch, db):
        assert self._run(monkeypatch, db, GOOD, "--username", "admin") == 0
        with self._conn(db) as c:
            assert verify_login(c, "admin", GOOD)

    def test_reset_password(self, monkeypatch, db):
        self._run(monkeypatch, db, GOOD, "--username", "admin")
        assert self._run(monkeypatch, db, "another long password", "--username", "admin", "--reset") == 0
        with self._conn(db) as c:
            assert verify_login(c, "admin", "another long password")

    def test_weak_password_fails_and_creates_nothing(self, monkeypatch, db, capsys):
        assert self._run(monkeypatch, db, "short", "--username", "admin") == 1
        assert "at least 12" in capsys.readouterr().err
        with self._conn(db) as c:
            assert count_admins(c) == 0

    def test_missing_database(self, monkeypatch, tmp_path):
        assert self._run(monkeypatch, str(tmp_path / "nope.db"), GOOD, "--username", "admin") == 2

    def test_mismatched_prompt(self, monkeypatch, db):
        answers = iter([GOOD, GOOD + "x"])
        monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": next(answers))
        assert script.main(["--db", db, "--username", "admin"]) == 1


def test_hub_creates_admin_table(app):
    with app.config["DB_ENGINE"].connect() as c:
        assert count_admins(c) == 0  # table exists, no default account
