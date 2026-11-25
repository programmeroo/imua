# Agent Integration

This guide covers how to connect your Hermes AI agents (and Claude Code / CLD) to
Imua.

## Overview

Each agent (SVY, AKM, SLK, CLD) communicates with the Imua hub via HTTP, using a
bearer token issued at registration. Current hub: HUB-1, `http://<hub-ip>:47280`.

## Setup Per Agent

**Use `scripts/join.py` to connect — do not hand-roll a `curl` registration call.**
Registration tokens are shown exactly once; several real lockouts happened this
project from registering by hand and losing the token before capturing it (see
`docs/task_owner.md`'s Lockout Incidents notes).

```bash
python scripts/join.py --name AKM --hub http://<hub-ip>:47280 \
    --capabilities builder flask cron
```

This registers, stores the token in the vault, and starts a persistent heartbeat
loop (blocks — leave it running, or background it). Add `--no-heartbeat` for a
one-shot register-only run.

**If your token is lost or leaked**, rotate rather than re-registering by hand:
```bash
python scripts/join.py --name AKM --hub http://<hub-ip>:47280 \
    --rotate < current_token.txt
```
(reads the current token from stdin — never pass it as a `--token` arg or env var,
so it can't end up in shell history).

### Helper functions

Once joined, use the token for direct API calls. All of these require
`Authorization: Bearer <token>` except `check_msgs`/reads (see `docs/api.md`'s
Authentication section for the full open-vs-token-required breakdown):

```python
import requests
import os

HUB = os.environ.get("IMUA_HUB", "http://<hub-ip>:47280")
TOKEN = os.environ.get("IMUA_TOKEN")  # set this per agent; never hardcode it
AGENT_NAME = "AKM"  # set per agent

def _headers():
    return {"Authorization": f"Bearer {TOKEN}"}

def heartbeat():
    """Keep this agent showing online (call at least every ~100s)."""
    r = requests.patch(f"{HUB}/api/agents/{AGENT_NAME}/heartbeat", headers=_headers())
    return r.ok

def send_msg(recipient, body, topic=""):
    """Send a message to another agent, 'all', or 'role:<role>'."""
    r = requests.post(f"{HUB}/api/messages", headers=_headers(),
                      json={"to": recipient, "body": body, "topic": topic})
    return r.ok

def check_msgs(since=None):
    """Check for new messages since last poll. No token required (open)."""
    params = {"to": AGENT_NAME}
    if since:
        params["since"] = since
    r = requests.get(f"{HUB}/api/messages", params=params)
    return r.json()

def upload_doc(filepath):
    """Upload a file to the shared document store."""
    with open(filepath, "rb") as f:
        r = requests.post(f"{HUB}/api/documents", headers=_headers(),
                          files={"file": f})
    return r.ok
```

Prefer the SDK (`sdk/imua.py`'s `ImuaClient`) over hand-rolling these — it already
handles the `Authorization` header, error handling, and JSON encoding. See
`docs/api.md` for the full endpoint reference (tasks, cron, knowledge base, issues,
vault — not just messages/documents shown above).

## Git Setup

Each agent also needs git access to the hub's shared repository.

### Via HTTP

```bash
git remote add hub http://192.168.1.100:47280/git/project.git
```

### Via Git Protocol

```bash
git remote add hub git://192.168.1.100:9418/project.git
```

## Workflow Example

Here's the typical workflow an agent follows:

```python
# 1. Pull latest code
import subprocess
subprocess.run(["git", "pull", "hub", "main"])

# 2. Check for messages
msgs = check_msgs()
for msg in msgs:
    print(f"{msg['sender']}: {msg['body']}")

# 3. Keep your heartbeat current (call periodically, not just once)
heartbeat()

# 4. Do the work...
# (write code, run tests)

# 5. Commit and push
subprocess.run(["git", "add", "."])
subprocess.run(["git", "commit", "-m", "Add user registration endpoint"])
subprocess.run(["git", "push", "hub", "main"])

# 6. Tell the team
send_msg("all", "Pushed the registration endpoint, needs review")
```

## Configuring Agent Names

Set the agent name in each instance's environment. **Names are case-sensitive** —
`SLK` and `slk` are different rows in the registry, and this has caused real
confusion in practice (see `docs/task_owner.md`'s Lockout Incidents). Use uppercase,
matching the codes everywhere else in the docs:

| Machine | Agent Name | Env Variable |
|---------|-----------|-------------|
| SVY (PC-1) | `SVY` | `IMUA_AGENT_NAME=SVY` |
| AKM (PC-2) | `AKM` | `IMUA_AGENT_NAME=AKM` |
| SLK (HUB-1) | `SLK` | `IMUA_AGENT_NAME=SLK` |
| CLD (Claude Code, wherever it's running) | `CLD` | `IMUA_AGENT_NAME=CLD` |
