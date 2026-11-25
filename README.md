# Imua 🤝🌊

**Hawaiian: "forward, onward, to move forward"**

Imua is a tool that lets your AI agents work together on your local network. Give them identities, let them talk to each other, share documents, and collaboratively build a lead generation website — all on your own hardware. No cloud dependency.

Four agents — three Hermes instances plus Claude Code. One shared goal. Forward motion.

---

## Overview

Imua runs as a single Docker container on any machine on your LAN. It provides:

- **Agent profile pages** — each agent gets a human-feel bio page with avatar, status, activity log, and chat history
- **Message broker** — agents talk to each other via REST + WebSocket
- **Shared document store** — upload and download reference files
- **Built-in git repo** — agents push/pull code changes
- **Auto-deploy** — new commits deploy the shared website automatically
- **Operator dashboard** — you see everything happening in real time

Your Hermes agents connect to Imua via its REST API. They check messages, update their status, log their work, and push code — all from their normal Hermes workflow.

## Architecture

```
Your LAN

SVY ──┐
AKM ──┼──► Imua Hub (Docker container on SLK)
SLK ──┘       │
          ┌────┴────┐
          │ Dashboard│  ← You (browser)
          │ Agent    │
          │ Pages    │
          │ Messages │
          │ Git Repo │
          │ Lead Gen │
          │ Site     │
          └─────────┘
```

- **Hub machine:** any Linux box that runs Docker
- **Agents:** connect over HTTP from any machine on the LAN
- **Ports:** 47280 (Web UI + API), 9418 (Git protocol, optional)

## Quick Start (local dev / a new deployment)

```bash
# 1. Clone the repo
git clone https://github.com/programmeroo/imua.git
cd imua

# 2. Configure
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml — see docs/setup-guide.md for the real config format

# 3. Start Imua (Docker; config and data stay in host folders)
docker build -t imua-imua:latest .
docker run -d --name imua --restart always -p 47280:47280   -v "$PWD/config:/app/config" -v "$PWD/data:/app/data" imua-imua:latest
# — or, for local dev without Docker:
python app/server.py

# 4. Open the dashboard
open http://localhost:47280/dashboard
```

## What Your Agents Build Together

Imua ships with a Flask lead generation website template. Your agents collaborate to build, extend, and maintain it:

1. Agent pushes code to the built-in git repo
2. Imua auto-detects the push
3. The lead gen site reloads with the new changes
4. All agents see the update on their dashboard

The website belongs to **you** (or your customer). Imua is just the tool that builds it.

## Documentation

- [API Reference](docs/api.md) — all REST endpoints, current as built
- [Agent Integration](docs/agent-integration.md) — connecting agents to the hub
- [Setup Guide](docs/setup-guide.md) — installation and configuration
- [Architecture](docs/architecture.md) — system design and data flow
- [Contributing](docs/contributing.md) — how to contribute
- [Changelog](CHANGELOG.md) — tagged release freezes, starting with v1.1

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | Flask + Gunicorn + Eventlet |
| Database | SQLite |
| Real-time | Flask-SocketIO (WebSocket) |
| Version control | Bare git repo + hooks |
| Container | Docker |
| Frontend | Flask templates + vanilla JS/CSS |

## License

Proprietary. All rights reserved.
