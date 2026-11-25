"""
Admin sign-in and sign-out (task 5.4, docs/imua_admin_security_plan_v1.md).

    GET  /login    sign-in form (?next=/some/page to return there afterwards)
    POST /login    username + password → session cookie, redirect to next
    POST /logout   end the session, back to /login

Every failure shows the same message, so the form can't be used to find out
which usernames exist or which accounts are disabled.
"""

from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request

from app.models.admin_user import admin_users
from app.services import admin_session, audit
from app.services.admin_accounts import count_admins, verify_login

auth_bp = Blueprint("auth", __name__)

BAD_LOGIN = "Wrong username or password."
LOCKED_OUT = "Too many failed sign-ins. Try again in 15 minutes."


def _safe_next(target: str | None) -> str:
    """Only same-site paths: '/tasks' yes; '//evil.com', 'http://…', '/\\evil' no."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return "/"
    return target


def _form(error: str | None = None, username: str = "", status: int = 200):
    with current_app.config["DB_ENGINE"].connect() as conn:
        no_admins = count_admins(conn) == 0
    return render_template("login.html", title="Imua · Sign in", error=error, username=username,
                           no_admins=no_admins, next=_safe_next(request.values.get("next"))), status


@auth_bp.get("/login")
def login_page():
    if admin_session.current_admin():
        return redirect(_safe_next(request.args.get("next")))
    return _form()


@auth_bp.post("/login")
def login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    ip = request.remote_addr or ""

    if admin_session.is_locked_out(ip, username):
        audit.record(username or "?", "sign_in_refused", detail="too many failed sign-ins", status=429)
        return _form(LOCKED_OUT, username, 429)

    with current_app.config["DB_ENGINE"].begin() as conn:
        admin = verify_login(conn, username, password)
        if admin:
            conn.execute(admin_users.update().where(admin_users.c.id == admin["id"])
                         .values(last_login_at=datetime.utcnow()))

    if not admin:
        admin_session.record_failure(ip, username)
        audit.record(username or "?", "sign_in_failed", status=401)
        return _form(BAD_LOGIN, username, 401)

    admin_session.clear_failures(ip, username)
    admin_session.sign_in(admin)
    audit.record(admin["username"], "sign_in", status=302)
    return redirect(_safe_next(request.form.get("next")))


@auth_bp.post("/logout")
def logout():
    admin = admin_session.current_admin()
    if admin:
        audit.record(admin["username"], "sign_out", status=302)
    admin_session.sign_out()
    return redirect("/login")
