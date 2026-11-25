"""
CSRF protection for signed-in browsers (task 5.5, admin plan D6).

Every state-changing request (POST/PUT/PATCH/DELETE) that is NOT authenticated
by a bearer token must carry this session's CSRF token, as the `csrf_token`
form field or the `X-CSRF-Token` header. Otherwise it is refused with 403.

Bearer-token requests (agents, the operator key, scripts) are exempt: a browser
never attaches an Authorization header on its own, so another site can't forge
one. The session cookie is also SameSite=Strict (task 5.4); this is the second
layer the plan asks for.

Pages get the token from `csrf_token()` (a Jinja global): a hidden form field,
or `<meta name="csrf-token">` in base.html for scripts.
"""

import hmac
import secrets

from flask import jsonify, request, session

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FAILED = "Form expired or invalid. Reload the page and try again."


def csrf_token() -> str:
    """This session's token, created on first use. sign_in/sign_out clear the
    session, so a fresh token is issued at every sign-in."""
    token = session.get("csrf")
    if not token:
        token = session["csrf"] = secrets.token_urlsafe(32)
    return token


def _sent_token() -> str:
    return request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""


def check_request():
    """before_request hook: None to continue, or a 403 response."""
    if request.method not in UNSAFE_METHODS:
        return None
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return None
    # Only session-authenticated requests and the sign-in/out forms need it. Open
    # endpoints called without any session (e.g. agent registration) don't use
    # the cookie, so forging them gains nothing.
    if "admin_id" not in session and request.path not in ("/login", "/logout"):
        return None
    expected = session.get("csrf", "")
    if expected and hmac.compare_digest(_sent_token(), expected):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "csrf_failed", "message": FAILED}), 403
    return FAILED, 403


def init_app(app) -> None:
    app.before_request(check_request)
    app.jinja_env.globals["csrf_token"] = csrf_token
