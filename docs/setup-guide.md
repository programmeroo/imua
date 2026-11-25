# Setup Guide

## Prerequisites

- A machine running Docker and Docker Compose (the "hub")
- One or more machines running Hermes agents that will connect to the hub
- All machines on the same local area network

## Quick Install

### 1. Clone the Repository

```bash
git clone https://github.com/programmeroo/imua.git
cd imua
```

### 2. Configure

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config.yaml` with your settings (see [Configuration](#configuration) below).

If you plan to store or retrieve vault secrets directly (not through an agent), also
set `app.operator_key` in `config.yaml` — see the Authentication section in
`docs/api.md` for details.

### 3. Start

```bash
docker compose up -d
```

### 4. Open the Dashboard

```
http://<hub-ip>:47280/dashboard
```

## Configuration

### `config/config.yaml`

This is the **real** config format (copied from `config/config.example.yaml`).
Environment variables override any of these when set (`IMUA_SECRET_KEY`,
`IMUA_DEBUG`, `IMUA_PORT`, `IMUA_VAULT_KEY`, `IMUA_OPERATOR_KEY`).

```yaml
app:
  name: "Imua"
  version: "0.1.0"
  debug: true
  host: "0.0.0.0"
  port: 47280
  secret_key: "CHANGE_ME_TO_A_RANDOM_STRING"
  vault_key: ""       # Override auto-generated vault key; leave empty for auto
  operator_key: ""    # Admin credential for direct vault access; leave empty to disable

database:
  path: "data/database/imua.db"

logging:
  level: "INFO"
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

websocket:
  ping_interval: 25
  ping_timeout: 10

agents:
  heartbeat_timeout: 120  # seconds before marking an agent offline

tasks:
  max_concurrent: 10
```

There is no per-agent config here (no `bio`/`avatar`/`color`) — agent identity,
capabilities, and role are set at registration time via `scripts/join.py`, not in
this file. See [Agent Integration](agent-integration.md) and `docs/api.md`.

## Setting Up Agent Machines

On each machine running a Hermes agent, join with `scripts/join.py` — this is the
**only** supported way to register (see `docs/agent-integration.md` and the
Authentication section of `docs/api.md` for why hand-rolled `curl` registration has
caused real lockouts):

```bash
python scripts/join.py --name AKM --hub http://<hub-ip>:47280 \
    --capabilities builder flask cron
```

This registers, stores the token in the vault, and starts a persistent heartbeat
loop. Confirm network access first if it fails to connect:

```bash
curl http://<hub-ip>:47280/api/health
```

## Git Access

Add the hub as a git remote on each agent machine:

```bash
git remote add imua http://<hub-ip>:47280/git/project.git
```

Or via the git protocol:

```bash
git remote add imua git://<hub-ip>:9418/project.git
```

## Verifying It Works

1. Open `http://<hub-ip>:47280/dashboard` in your browser
2. Agents appear here once they've registered via `join.py` — there's no
   pre-configured agent list, the roster reflects whoever has actually joined
3. Confirm an agent shows `online` (heartbeat within the last `heartbeat_timeout`,
   120s by default):
   ```bash
   curl -s http://<hub-ip>:47280/api/agents | python3 -m json.tool
   ```
4. If it shows `offline`, the agent's heartbeat loop isn't running — re-run
   `join.py` (or check `docs/api.md`'s Losing/leaking a token section if the
   original token is gone)

## Updating

```bash
cd imua
git pull
docker compose down
docker compose up -d
```

## Troubleshooting

### Cannot connect to the hub
- Verify the hub machine's IP address: `hostname -I`
- Check that port 47280 is accessible: `curl http://localhost:47280`
- From another machine: `curl http://<hub-ip>:47280`
- Check firewall rules on the hub machine

### Agents show as offline
- Ensure each agent can reach the hub via HTTP
- Check that `IMUA_HUB` is set correctly
- Agents must send at least one API call to register as online

### Git push fails
- Ensure the git remote URL is correct
- Try HTTP-based remote first (port 47280) before the git protocol (port 9418)
- Check that the project repo exists on the hub
