"""
Admin sign-in sessions (task 5.4, docs/imua_admin_security_plan_v1.md).

The session is Flask's signed cookie (key from task 5.3). It holds only the
admin's id and two timestamps; the admin row is re-checked on every request, so
disabling or deleting an admin signs them out at once.

Timeouts (D4): signed out after IDLE_TIMEOUT without a request, and after
ABSOLUTE_TIMEOUT since sign-in no matter what.

Login limits (D7): MAX_FAILURES failed sign-ins for the same IP + username
within FAILURE_WINDOW refuse further attempts until the window passes. Kept in
memory: the hub runs one worker (Dockerfile), and a restart clearing it is fine.
"""

import threading
import time

from urllib.parse import urlencode

from flask import current_app, g, redirect, request, session
from flask.sessions import SecureCookieSessionInterface
from sqlalchemy import select

from app.models.admin_user import admin_users

IDLE_TIMEOUT = 8 * 3600
ABSOLUTE_TIMEOUT = 24 * 3600
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60

_failures: dict[tuple[str, str], list[float]] = {}
_failures_lock = threading.Lock()


class AdminSessionInterface(SecureCookieSessionInterface):
    """Marks the cookie Secure whenever the request came in over HTTPS (D4),
    or always if SESSION_COOKIE_SECURE is set."""

    def get_cookie_secure(self, app) -> bool:
        return bool(app.config.get("SESSION_COOKIE_SECURE")) or request.is_secure


def configure(app) -> None:
    app.session_interface = AdminSessionInterface()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["SESSION_COOKIE_NAME"] = "imua_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = ABSOLUTE_TIMEOUT
    app.before_request(page_gate)


def _key(ip: str, username: str) -> tuple[str, str]:
    return (ip or "?", (username or "").strip().lower())


def _recent(key, now: float) -> list[float]:
    times = [t for t in _failures.get(key, []) if now - t < FAILURE_WINDOW]
    if times:
        _failures[key] = times
    else:
        _failures.pop(key, None)
    return times


def is_locked_out(ip: str, username: str) -> bool:
    with _failures_lock:
        return len(_recent(_key(ip, username), time.time())) >= MAX_FAILURES


def record_failure(ip: str, username: str) -> None:
    with _failures_lock:
        key = _key(ip, username)
        now = time.time()
        _failures[key] = _recent(key, now) + [now]


def clear_failures(ip: str, username: str) -> None:
    with _failures_lock:
        _failures.pop(_key(ip, username), None)


def sign_in(admin: dict) -> None:
    """Start a fresh session for this admin (old session contents are dropped)."""
    now = int(time.time())
    session.clear()
    session.permanent = True
    session["admin_id"] = admin["id"]
    session["login_at"] = now
    session["seen_at"] = now


def sign_out() -> None:
    session.clear()


def current_admin() -> dict | None:
    """The signed-in, enabled admin for this request, or None. Expired sessions
    are cleared. Cached on flask.g for the rest of the request."""
    if "admin" in g:
        return g.admin
    g.admin = None
    admin_id = session.get("admin_id")
    if admin_id is None:
        return None
    now = int(time.time())
    if (now - session.get("login_at", 0) > ABSOLUTE_TIMEOUT
            or now - session.get("seen_at", 0) > IDLE_TIMEOUT):
        session.clear()
        return None
    with current_app.config["DB_ENGINE"].connect() as conn:
        row = conn.execute(select(admin_users.c.id, admin_users.c.username, admin_users.c.disabled)
                           .where(admin_users.c.id == admin_id)).one_or_none()
    if not row or row.disabled:
        session.clear()
        return None
    if now - session.get("seen_at", 0) > 60:  # avoid re-sending the cookie on every request
        session["seen_at"] = now
    g.admin = {"id": row.id, "username": row.username}
    return g.admin


# --- Dashboard pages need a signed-in admin (task 5.7) ---
# Gated by default, so new pages are covered without remembering to add a check.
# Open: the API (agents use tokens; reads become token/session-only in 5.21),
# static files, the sign-in/out routes, Socket.IO, and the git site at /project/.
OPEN_PREFIXES = ("/api/", "/static/", "/project/", "/socket.io")
OPEN_PATHS = ("/login", "/logout", "/favicon.ico")


def page_gate():
    """before_request hook: redirect to /login unless the page is open or an admin is signed in."""
    path = request.path
    if path in OPEN_PATHS or path.startswith(OPEN_PREFIXES) or current_admin():
        return None
    target = request.full_path.rstrip("?") if request.query_string else path
    return redirect(f"/login?{urlencode({'next': target})}")
