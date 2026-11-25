#!/usr/bin/env python3
"""Heartbeat script for Imua — silence on success, error on fail.

Called by Hermes cron job (no_agent mode). If the heartbeat succeeds,
script exits with empty stdout (no message sent to user). On failure,
prints the error so the cron job reports it.
"""
import os
import sys
import json
import urllib.request
import urllib.error

HUB = os.environ.get("IMUA_HUB", "http://localhost:47280")
NAME = os.environ.get("IMUA_AGENT_NAME", "AKM")
TOKEN = os.environ.get("IMUA_TOKEN")

if not TOKEN:
    print("HEARTBEAT FAILED: IMUA_TOKEN environment variable is not set", flush=True)
    sys.exit(1)

url = f"{HUB.rstrip('/')}/api/agents/{NAME}/heartbeat"
req = urllib.request.Request(url, method="PATCH")
req.add_header("Authorization", f"Bearer {TOKEN}")
req.add_header("Content-Type", "application/json")

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read()
    # Silent on success — no message sent to user
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="replace")
    print(f"HEARTBEAT FAILED: HTTP {e.code} — {detail}", flush=True)
    sys.exit(1)
except Exception as e:
    print(f"HEARTBEAT FAILED: {e}", flush=True)
    sys.exit(1)
