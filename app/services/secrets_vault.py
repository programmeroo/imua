"""
Secrets Vault — encrypted secret storage with scoped access.

Uses Fernet symmetric encryption (from the `cryptography` library)
with a configurable master key. The master key is auto-generated
on first run if not provided in config.

Future: can be swapped for age encryption (CLI-based) by replacing
the _encrypt / _decrypt helpers.
"""

import json
from datetime import datetime
from cryptography.fernet import Fernet
from app.models.secret import secrets, get_secret_by_name, list_secret_names


def _get_cipher(master_key: str | None = None) -> Fernet:
    """Get a Fernet cipher from the master key. A key is required: a per-call random
    key would encrypt secrets that could never be decrypted again."""
    if not master_key:
        raise ValueError("Vault master key is not configured")
    # Ensure the key is valid Fernet format (base64, 32 bytes)
    if len(master_key) != 44 or not master_key.endswith("="):
        # Hash the key into valid Fernet format
        import hashlib
        import base64
        key = base64.urlsafe_b64encode(
            hashlib.sha256(master_key.encode()).digest()
        )
        return Fernet(key)
    return Fernet(master_key)


def store_secret(conn, name: str, value: str,
                 description: str = "",
                 access_scope: list[str] | None = None,
                 master_key: str | None = None) -> dict:
    """Encrypt and store a secret. Returns metadata (not the value)."""
    cipher = _get_cipher(master_key)
    encrypted = cipher.encrypt(value.encode()).decode()

    scope_json = json.dumps(access_scope or [])

    stmt = secrets.insert().values(
        name=name,
        encrypted_value=encrypted,
        description=description,
        access_scope=scope_json,
        created_at=datetime.utcnow(),
    )
    result = conn.execute(stmt)
    msg_id = result.inserted_primary_key[0]

    return {
        "status": "stored",
        "name": name,
        "encrypted": True,
        "created_at": datetime.utcnow().isoformat(),
    }


def retrieve_secret(conn, name: str, agent_name: str | None = None,
                    master_key: str | None = None, bypass_scope: bool = False) -> dict | None:
    """Decrypt and return a secret if the agent has access, or if bypass_scope
    is set (operator key). Returns None if not found or access denied."""
    row = get_secret_by_name(conn, name)
    if not row:
        return None

    # Check access scope
    scope = json.loads(row["access_scope"] or "[]")
    if scope and not bypass_scope and agent_name not in scope:
        return None  # Access denied

    cipher = _get_cipher(master_key)
    decrypted = cipher.decrypt(row["encrypted_value"].encode()).decode()

    # Update last_access
    conn.execute(
        secrets.update()
        .where(secrets.c.name == name)
        .values(last_access=datetime.utcnow())
    )

    return {
        "name": row["name"],
        "value": decrypted,
        "description": row["description"] or "",
        "last_access": (row["last_access"].isoformat()
                        if row.get("last_access") else None),
    }


def list_available_secrets(conn, agent_name: str | None = None,
                            bypass_scope: bool = False) -> list[dict]:
    """List secret names (and descriptions) visible to an agent, or all
    secrets if bypass_scope is set (operator key)."""
    names = list_secret_names(conn)
    result = []
    for n in names:
        row = get_secret_by_name(conn, n)
        if not row:
            continue
        scope = json.loads(row["access_scope"] or "[]")
        if scope and not bypass_scope and agent_name and agent_name not in scope:
            continue
        result.append({
            "name": row["name"],
            "description": row["description"] or "",
        })
    return result


def _is_scope_match(row: dict, agent_name: str) -> bool:
    """Check if an agent is in the access scope of a secret."""
    scope = json.loads(row.get("access_scope") or "[]")
    return not scope or agent_name in scope
