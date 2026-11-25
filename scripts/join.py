#!/usr/bin/env python3
"""
Imua Join Script — one-command agent onboarding.

Usage:
    # First-time registration:
    python scripts/join.py --name AKM --hub http://10.0.0.10:47280 --capabilities builder flask cron

    # Token rotation (recovery when current token is leaked/lost):
    # Pipe the current token on stdin so it never appears on a command line:
    python scripts/join.py --name AKM --hub http://10.0.0.10:47280 --rotate < /path/to/current_token.txt

This registers the agent (or rotates its token), stores the token in Imua's vault,
and starts a continuous heartbeat loop. Run it and leave it running — it handles
reconnection on its own.

Requirements: Python 3.10+, urllib (stdlib), time (stdlib).
"""

import argparse
import json
import os
import sys
import time
import urllib.error

# Windows consoles often default to a legacy codepage (cp1252) that can't
# encode the emoji used in status output below, crashing before the script
# ever reaches the network call. Force UTF-8 stdout/stderr so this works the
# same on every platform.
if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding is not None and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _request(method: str, base_url: str, path: str,
             body: dict | None = None, token: str | None = None) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(f"  ❌ {method} {path}: HTTP {e.code} — {detail}", flush=True)
        raise SystemExit(1)


def register(base_url: str, name: str, capabilities: list[str],
             host: str = "", port: int = 0) -> str:
    """Register agent, return bearer token."""
    print(f"  ✓ Registering '{name}' on {base_url}...", flush=True)
    data = _request("POST", base_url, "/api/agents/register", body={
        "name": name,
        "capabilities": capabilities,
        "host": host,
        "port": port,
    })
    token = data["token"]
    print(f"  ✓ Registered! Token: {token[:16]}...{token[-8:]}", flush=True)
    return token


def store_token(base_url: str, name: str, token: str):
    """Store agent token in Imua vault."""
    print(f"  ✓ Storing token in vault as '{name}_token'...", flush=True)
    _request("POST", base_url, "/api/vault/secrets", body={
        "name": f"{name}_token",
        "value": token,
    }, token=token)
    print(f"  ✓ Token stored securely", flush=True)


def rotate(base_url: str, name: str, current_token: str) -> str:
    """Rotate the agent's bearer token. Returns the new token.

    current_token must come from stdin or a file (NEVER a command-line arg,
    NEVER an env var) so it doesn't end up in shell history, ps output, or
    terminal transcripts.
    """
    print(f"  ✓ Rotating token for '{name}' on {base_url}...", flush=True)
    data = _request("PATCH", base_url, f"/api/agents/{name}/token",
                    token=current_token)
    new_token = data["token"]
    print(f"  ✓ Rotated! New token: {new_token[:16]}...{new_token[-8:]}", flush=True)
    print(f"  ⚠ Old token is now invalid. Capture the new one to disk immediately.", flush=True)
    return new_token


def heartbeat_loop(base_url: str, name: str, token: str,
                   interval: int = 60):
    """Run heartbeat every `interval` seconds. Stays alive."""
    print(f"  ✓ Heartbeat started (every {interval}s). Press Ctrl+C to stop.", flush=True)
    while True:
        try:
            _request("PATCH", base_url, f"/api/agents/{name}/heartbeat",
                     token=token)
        except Exception as e:
            print(f"  ⚠ Heartbeat failed: {e}", flush=True)
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser(description="Join an agent to the Imua hub.")
    ap.add_argument("--name", required=True, help="Agent name (e.g. AKM, SVY, SLK)")
    ap.add_argument("--hub", default="http://localhost:47280",
                    help="Imua hub URL (default: http://localhost:47280)")
    ap.add_argument("--capabilities", nargs="*", default=[],
                    help="Capability tags (e.g. builder architect operator)")
    ap.add_argument("--host", default="", help="This machine's LAN IP / hostname")
    ap.add_argument("--port", type=int, default=0, help="Agent's API port")
    ap.add_argument("--no-vault", action="store_true",
                    help="Skip storing token in vault")
    ap.add_argument("--no-heartbeat", action="store_true",
                    help="Register only, don't start heartbeat loop")
    ap.add_argument("--rotate", action="store_true",
                    help="Rotate the existing token instead of registering a new agent. "
                         "Reads the CURRENT token from stdin so it never appears on a command line.")
    args = ap.parse_args()

    print(f"\n🚀 {'Rotating' if args.rotate else 'Joining'} '{args.name}' "
          f"{'on' if args.rotate else 'to'} Imua hub at {args.hub}\n", flush=True)

    if args.rotate:
        # Read current token from stdin. Never from --token, never from env var.
        # The shell pipe `< /path/to/current_token.txt` keeps the value out of history
        # and out of any ps-visible args.
        current = sys.stdin.read().strip()
        if not current:
            print("  ❌ --rotate requires the current token on stdin.", flush=True)
            print("     Example: python scripts/join.py --name X --hub URL --rotate < current_token.txt",
                  file=sys.stderr, flush=True)
            raise SystemExit(2)
        token = rotate(args.hub, args.name, current)
    else:
        token = register(args.hub, args.name, args.capabilities,
                         host=args.host, port=args.port)

    if not args.no_vault:
        try:
            store_token(args.hub, args.name, token)
        except Exception as e:
            print(f"  ⚠ Could not store token: {e}", flush=True)
            print(f"  📝 Save this token: {token}", flush=True)
    else:
        print(f"  📝 Save this token: {token}", flush=True)

    if not args.no_heartbeat:
        heartbeat_loop(args.hub, args.name, token)
    else:
        if args.rotate:
            print(f"\n✅ '{args.name}' token rotated. Old token invalidated.", flush=True)
        else:
            print(f"\n✅ '{args.name}' registered. Token saved.", flush=True)


if __name__ == "__main__":
    main()
