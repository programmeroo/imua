"""
Admin sign-in, sign-out, session timeouts and login limits — task 5.4
(docs/imua_admin_security_plan_v1.md, decisions D4 and D7).
"""

import time

import pytest

from app.models.admin_user import admin_users
from app.routes.auth import BAD_LOGIN, LOCKED_OUT
from app.services import admin_session
from app.services.admin_accounts import create_admin

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _reset_limits():
    admin_session._failures.clear()
    yield
    admin_session._failures.clear()


@pytest.fixture
def admin(app):
    with app.config["DB_ENGINE"].begin() as conn:
        return create_admin(conn, "admin", PASSWORD)


def _csrf(client, base_url="http://localhost"):
    """This test client's CSRF token, as a page would have embedded it (task 5.5)."""
    client.get("/login", base_url=base_url)
    with client.session_transaction() as s:
        return s.get("csrf") or s.setdefault("csrf", "test-csrf-token")


def _login(client, username="admin", password=PASSWORD, **extra):
    return client.post("/login", data={"username": username, "password": password,
                                       "csrf_token": _csrf(client), **extra})


def _logout(client):
    return client.post("/logout", data={"csrf_token": _csrf(client)})


def _signed_in(client):
    with client.session_transaction() as s:
        return "admin_id" in s


class TestSignIn:
    def test_form_renders(self, client):
        r = client.get("/login")
        assert r.status_code == 200 and b'name="password"' in r.data

    def test_success_sets_session_and_redirects(self, client, admin, app):
        r = _login(client)
        assert r.status_code == 302 and r.headers["Location"] == "/"
        assert _signed_in(client)
        with app.config["DB_ENGINE"].connect() as c:
            assert c.execute(admin_users.select()).one().last_login_at is not None

    def test_username_is_case_insensitive(self, client, admin):
        assert _login(client, username="  ADMIN ").status_code == 302

    @pytest.mark.parametrize("username,password", [("admin", "wrong password!!"), ("nobody", PASSWORD)])
    def test_failures_give_one_generic_error(self, client, admin, username, password):
        r = _login(client, username, password)
        assert r.status_code == 401 and BAD_LOGIN.encode() in r.data
        assert not _signed_in(client)

    def test_disabled_admin_gets_same_error(self, client, admin, app):
        with app.config["DB_ENGINE"].begin() as c:
            c.execute(admin_users.update().values(disabled=True))
        r = _login(client)
        assert r.status_code == 401 and BAD_LOGIN.encode() in r.data

    @pytest.mark.parametrize("target,expected", [
        ("/tasks?x=1", "/tasks?x=1"), ("//evil.com", "/"), ("http://evil.com", "/"),
        ("/\\evil.com", "/"), ("", "/"),
    ])
    def test_next_redirect_stays_on_site(self, client, admin, target, expected):
        assert _login(client, next=target).headers["Location"] == expected

    def test_cookie_flags(self, client, admin):
        cookie = _login(client).headers["Set-Cookie"]
        assert "imua_session=" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
        assert "Secure" not in cookie  # plain HTTP on the LAN

    def test_cookie_secure_over_https(self, client, admin):
        r = client.post("/login", data={"username": "admin", "password": PASSWORD,
                                        "csrf_token": _csrf(client, "https://localhost")},
                        base_url="https://localhost")
        assert "Secure" in r.headers["Set-Cookie"]

    def test_sidebar_shows_signed_in_admin(self, client, admin):
        assert client.get("/").status_code == 302  # signed out: no page at all (task 5.7)
        _login(client)
        page = client.get("/").data
        assert b"admin" in page and b"Sign out" in page

    def test_login_page_redirects_when_already_signed_in(self, client, admin):
        _login(client)
        assert client.get("/login?next=/tasks").headers["Location"] == "/tasks"


class TestSignOut:
    def test_logout_clears_session(self, client, admin):
        _login(client)
        r = _logout(client)
        assert r.status_code == 302 and r.headers["Location"] == "/login"
        assert not _signed_in(client)

    def test_logout_is_post_only(self, client):
        assert client.get("/logout").status_code == 405


class TestSessionLifetime:
    def _age(self, client, login_ago=0, seen_ago=0):
        now = int(time.time())
        with client.session_transaction() as s:
            s["login_at"] = now - login_ago
            s["seen_at"] = now - seen_ago

    def test_active_session_kept(self, client, admin):
        _login(client)
        self._age(client, login_ago=3600, seen_ago=600)
        assert b"Sign out" in client.get("/").data

    def test_idle_timeout(self, client, admin):
        _login(client)
        self._age(client, login_ago=9 * 3600, seen_ago=admin_session.IDLE_TIMEOUT + 1)
        assert b"Sign out" not in client.get("/").data
        assert not _signed_in(client)

    def test_absolute_timeout_even_when_active(self, client, admin):
        _login(client)
        self._age(client, login_ago=admin_session.ABSOLUTE_TIMEOUT + 1, seen_ago=0)
        assert b"Sign out" not in client.get("/").data

    def test_disabling_admin_ends_session(self, client, admin, app):
        _login(client)
        with app.config["DB_ENGINE"].begin() as c:
            c.execute(admin_users.update().values(disabled=True))
        assert b"Sign out" not in client.get("/").data

    def test_session_cookie_is_signed(self, client, admin):
        client.set_cookie("imua_session", '{"admin_id": 1}')
        assert b"Sign out" not in client.get("/").data


class TestLoginLimits:
    def test_sixth_failure_refused_even_with_right_password(self, client, admin):
        for _ in range(admin_session.MAX_FAILURES):
            assert _login(client, password="wrong password!!").status_code == 401
        r = _login(client)
        assert r.status_code == 429 and LOCKED_OUT.encode() in r.data
        assert not _signed_in(client)

    def test_limit_is_per_username(self, client, admin, app):
        with app.config["DB_ENGINE"].begin() as c:
            create_admin(c, "second", PASSWORD)
        for _ in range(admin_session.MAX_FAILURES):
            _login(client, password="wrong password!!")
        assert _login(client, username="second").status_code == 302

    def test_window_expires(self, client, admin, monkeypatch):
        for _ in range(admin_session.MAX_FAILURES):
            _login(client, password="wrong password!!")
        later = time.time() + admin_session.FAILURE_WINDOW + 1
        monkeypatch.setattr(admin_session.time, "time", lambda: later)
        assert _login(client).status_code == 302

    def test_success_resets_count(self, client, admin):
        for _ in range(admin_session.MAX_FAILURES - 1):
            _login(client, password="wrong password!!")
        _login(client)
        _logout(client)
        for _ in range(admin_session.MAX_FAILURES - 1):
            assert _login(client, password="wrong password!!").status_code == 401
        assert _login(client).status_code == 302
