#!/usr/bin/env python3
"""Create an Imua admin, or reset an admin's password (task 5.2).

Run on the hub's own machine, against the hub's database:

    python scripts/create_admin.py --username admin
    python scripts/create_admin.py --username admin --reset     # forgot password
    docker exec -it imua python scripts/create_admin.py --username admin

The password is always prompted for (or read from stdin with --password-stdin),
never passed on the command line, so it can't end up in shell history.
--reset also re-enables a disabled account, so an admin can't be locked out for good.
"""

import argparse
import getpass
import os
import sys

import yaml
from sqlalchemy import create_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.models.admin_user import metadata as admin_meta  # noqa: E402
from app.services.admin_accounts import (AdminAccountError, MIN_PASSWORD_LENGTH,  # noqa: E402
                                         create_admin, set_password)


def resolve_db_path(cli_db: str | None) -> str:
    """Same order as the hub: --db, then database.path in the config file, then the default."""
    if cli_db:
        return cli_db
    config_path = os.environ.get("IMUA_CONFIG", os.path.join(ROOT, "config", "config.yaml"))
    if os.path.exists(config_path):
        with open(config_path) as f:
            path = ((yaml.safe_load(f) or {}).get("database") or {}).get("path")
        if path:
            return path
    return os.path.join(ROOT, "data", "database", "imua.db")


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass(f"New password (min {MIN_PASSWORD_LENGTH} characters): ")
    if getpass.getpass("Repeat password: ") != first:
        raise AdminAccountError("Passwords don't match")
    return first


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    parser.add_argument("--reset", action="store_true", help="set a new password for an existing admin")
    parser.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    parser.add_argument("--db", help="path to imua.db (default: from config, as the hub does)")
    args = parser.parse_args(argv)

    db_path = resolve_db_path(args.db)
    if not os.path.exists(db_path):
        print(f"No Imua database at {db_path}. Start the hub once first, or pass --db.", file=sys.stderr)
        return 2
    engine = create_engine(f"sqlite:///{db_path}")
    admin_meta.create_all(engine)  # admin_users only; the hub creates everything else
    try:
        password = read_password(args.password_stdin)
        with engine.begin() as conn:
            if args.reset:
                set_password(conn, args.username, password, enable=True)
                print(f"Password reset for admin '{args.username.strip().lower()}'.")
            else:
                admin = create_admin(conn, args.username, password)
                print(f"Created admin '{admin['username']}'.")
    except AdminAccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
