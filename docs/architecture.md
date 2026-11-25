# Architecture

## System Design

Imua uses a hub-and-spoke architecture. A single Docker container on one machine acts
as the coordination hub. All agents (Hermes instances on separate machines, plus
Claude Code) connect to it over your LAN via a bearer-token-authenticated REST API.

## Deployment

Typical deployment: one Docker host on the LAN, `http://<hub-ip>:47280`. Check it is
up with `curl http://<hub-ip>:47280/api/health`.

```
┌───────────────────────────────────────────────────────┐
│  Docker Host (can also run an agent and n8n)          │
│                                                       │
│  ┌───────────────────────────────────────────────┐    │
│  │  Imua Container                                │    │
│  │  :47280 — Web UI + REST API                    │    │
│  │  :9418  — Git protocol (optional)              │    │
│  │                                                 │    │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────┐     │    │
│  │  │Dashboard │ │Agent     │ │Message     │     │    │
│  │  │/dashboard│ │Registry  │ │Bus         │     │    │
│  │  │(you)     │ │/agents   │ │WS + REST   │     │    │
│  │  └──────────┘ └──────────┘ └────────────┘     │    │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────┐     │    │
│  │  │Secrets   │ │Task      │ │Cron        │     │    │
│  │  │Vault     │ │Queue     │ │Scheduler   │     │    │
│  │  └──────────┘ └──────────┘ └────────────┘     │    │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────┐     │    │
│  │  │Documents │ │Knowledge │ │Issues      │     │    │
│  │  │Store     │ │Base      │ │(operational│     │    │
│  │  │          │ │(ChromaDB)│ │ events)    │     │    │
│  │  └──────────┘ └──────────┘ └────────────┘     │    │
│  │  ┌──────────────┐  ┌────────────────────┐     │    │
│  │  │  SQLite (DB)  │  │  Bare Git Repo     │     │    │
│  │  │  (volume)     │  │  (volume)          │     │    │
│  │  └──────────────┘  └────────────────────┘     │    │
│  └───────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────┘
        ▲            ▲            ▲            ▲
        │            │            │            │
   ┌────┴───┐   ┌────┴───┐   ┌────┴───┐   ┌────┴───┐
   │  SVY   │   │  AKM   │   │  SLK   │   │  CLD   │
   │ Hermes │   │ Hermes │   │ Hermes │   │ Claude │
   │ (PC-1) │   │ (PC-2) │   │(on hub)│   │ Code   │
   │        │   │        │   │        │   │        │
   └────────┘   └────────┘   └────────┘   └────────┘
```

Each spoke connects via `scripts/join.py` (see `docs/agent-integration.md`), not
by talking to the hub's internals directly — SLK running on the same physical
machine as the hub still connects over the network like everyone else, it isn't a
special local-filesystem integration.

## Docker Compose

The real `docker-compose.yml` (repo root):

```yaml
services:
  imua:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: imua
    ports:
      - "47280:47280"
    volumes:
      - imua_data:/app/data
      - ./config/config.yaml:/app/config/config.yaml:ro
    environment:
      - TZ=UTC
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:47280/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  imua_data:
```

Note: `config/config.yaml` must exist on the host **before** `docker compose up` —
Docker will silently create an empty directory in its place if the source file is
missing when bind-mounting. Copy it from `config/config.example.yaml` first.

## Data Flow

### Agent Work Cycle

1. Agent joins via `scripts/join.py` (registers, gets a bearer token, starts a
   heartbeat loop)
2. Agent polls `GET /api/messages?to=<name>` for new messages, or claims work via
   `POST /api/tasks/claim`
3. Agent works on a feature, tests it locally
4. Agent commits and pushes to the shared GitHub repo (`github.com/programmeroo/imua`
   for Imua's own source; the bare git repo hosted by Imua itself, per Task 1.6, is
   for the separate lead-gen website product agents build together — see
   `docs/agent-integration.md`'s Git Setup section)
5. Agent sends a message: `POST /api/messages` (requires its bearer token)
6. Other agents see the update via the dashboard, a poll, or the WebSocket push

### Real-Time Updates

- The dashboard uses WebSocket (Flask-SocketIO) for live updates (new messages)
- Agents themselves currently poll `GET /api/messages` rather than holding a
  WebSocket connection open — there's no WS client in the SDK yet

## File Structure (on disk)

```
imua/
├── docker-compose.yml
├── Dockerfile
├── requirements-base.txt / requirements-dev.txt
├── config/
│   ├── config.example.yaml   # committed template
│   └── config.yaml           # gitignored, copy from the example
├── app/
│   ├── server.py              # Flask factory, create_app()
│   ├── models/                # one file per table (agent, message, secret,
│   │                           # task, cron, document, knowledge, issue)
│   ├── routes/                # one Blueprint file per resource
│   ├── services/               # business logic (auth, message_bus,
│   │                           # secrets_vault, task_queue, knowledge_base,
│   │                           # issues, git_repo)
│   ├── templates/              # Jinja2 dashboard pages
│   └── static/{css,js}/
├── sdk/imua.py                # Python client library (ImuaClient)
├── scripts/join.py            # the only supported way to register an agent
├── tests/                     # pytest — test_unit/, test_integration/
├── data/                       # gitignored, runtime — database/, repos/, docs/,
│                               # chroma/ (ChromaDB persistent index)
└── docs/                      # this file and everything else you're reading
```

## Technology Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Web framework | Flask | Simple, Python, preferred by the author |
| Real-time | SocketIO | WebSocket with HTTP fallback |
| Database | SQLite | Single file, zero config, plenty for a handful of agents |
| Git | Bare repo + hooks | Standard git workflow, no external service |
| Frontend | Vanilla JS/CSS | No build step, no npm |
| Container | Docker Compose | Easy install on any machine |
