"""
Admin account logic — create, verify and change admin passwords (task 5.2).

Usernames are case-insensitive (stored lowercase). Passwords: at least
MIN_PASSWORD_LENGTH characters, hashed with scrypt. Verification takes the same
time whether or not the username exists, so it can't be used to find usernames.
"""

import re
from datetime import datetime

from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.admin_user import admin_users

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_HASH_METHOD = "scrypt"
# Checked against when the username doesn't exist, so a miss costs the same as a hit.
_DUMMY_HASH = generate_password_hash("imua-dummy-password", method=_HASH_METHOD)


class AdminAccountError(ValueError):
    """Invalid username/password, or the account already exists / doesn't exist."""


def normalize_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise AdminAccountError("Username must be 3-64 characters: letters, digits, '.', '_' or '-', "
                                "starting with a letter or digit")
    return username


def check_password_policy(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise AdminAccountError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AdminAccountError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")


def get_admin(conn, username: str) -> dict | None:
    row = conn.execute(select(admin_users).where(
        admin_users.c.username == (username or "").strip().lower())).one_or_none()
    return row._asdict() if row else None


def count_admins(conn) -> int:
    return conn.execute(select(func.count()).select_from(admin_users)).scalar_one()


def create_admin(conn, username: str, password: str) -> dict:
    """Create an admin. Raises AdminAccountError if invalid or the name is taken."""
    username = normalize_username(username)
    check_password_policy(password)
    if get_admin(conn, username):
        raise AdminAccountError(f"Admin '{username}' already exists")
    conn.execute(admin_users.insert().values(
        username=username, password_hash=generate_password_hash(password, method=_HASH_METHOD),
        disabled=False, created_at=datetime.utcnow()))
    return get_admin(conn, username)


def set_password(conn, username: str, password: str, enable: bool = False) -> None:
    """Replace an admin's password (optionally re-enabling the account)."""
    check_password_policy(password)
    admin = get_admin(conn, username)
    if not admin:
        raise AdminAccountError(f"No admin '{(username or '').strip().lower()}'")
    values = {"password_hash": generate_password_hash(password, method=_HASH_METHOD)}
    if enable:
        values["disabled"] = False
    conn.execute(admin_users.update().where(admin_users.c.id == admin["id"]).values(**values))


def verify_login(conn, username: str, password: str) -> dict | None:
    """The admin row if username + password are right and the account is enabled, else None."""
    admin = get_admin(conn, username)
    ok = check_password_hash(admin["password_hash"] if admin else _DUMMY_HASH, password or "")
    if not admin or not ok or admin["disabled"]:
        return None
    return admin
