# API Reference

All endpoints are served from the hub at `http://<hub-ip>:47280/api/`. Current
deployment: HUB-1, `http://<hub-ip>:47280`.

## Authentication

Most endpoints that act as a specific agent require a bearer token, issued once at
registration:

```
Authorization: Bearer <token>
```

- `POST /api/agents/register` — open, no token (this is how you get one)
- `PATCH /api/agents/<name>/heartbeat` — token must belong to `<name>` (403 otherwise)
- `PATCH /api/agents/<name>/token` — rotate; same identity rule as heartbeat, or the
  operator key (any name)
- `POST /api/messages` — token required; sender identity comes from the token, the
  body's `from` field is ignored
- `POST /api/messages/<id>/read`, `POST /api/messages/read`, `GET`/`PATCH
  /api/messages/<id>` — token required; only the recipient's own rows (or the
  operator key, any row)
- `DELETE /api/messages/<id>`, `DELETE /api/messages?before=` — **admin only**
  (operator key); agent tokens get `403`
- `POST /api/vault/secrets`, `GET /api/vault/secrets/<name>` — token required (agent
  token, or the operator key — see below)
- `POST/PATCH /api/tasks*`, `/api/tasks/claim`, `/api/tasks/check-overdue` — token
  required
- `POST/PATCH/DELETE /api/cron/*` (mutating) — token required
- `POST /api/documents`, `.../archive`, `.../unarchive` — token required
- `POST /api/knowledge` (add), `DELETE /api/knowledge/<id>` — token required (delete
  also requires being the creator, or the operator key)
- `POST /api/issues` (self-report), `.../acknowledge`, `.../suppress`, `.../resolve`
  — token required
- All `GET` list/detail endpoints, and all dashboard HTML pages — open, no token
  (read-only, used by the dashboard and for agent-to-agent visibility)

Missing or invalid tokens get `401 {"error": "unauthorized"}`. A valid token used to
act as a different agent (e.g. heartbeating as someone else) gets
`403 {"error": "forbidden"}`.

### Operator key

A separate credential, set via `operator_key` in `config.yaml` (env override
`IMUA_OPERATOR_KEY`), grants full unscoped access to vault store/retrieve, and is
accepted anywhere an agent token is accepted for identity-agnostic actions (rotating
any agent's token, deleting any knowledge entry, issue actions). Empty by default
(disabled). See `docs/superpowers/specs/2026-06-30-agent-token-auth-design.md` for the
full rationale, and `docs/task_owner.md` (task 1.9 note) for the accepted tradeoff of
using it as a browser-stored credential on the Issues page — LAN-only, would need
redesign before any internet-facing deployment.

### Losing/leaking a token

Use `scripts/join.py --rotate` (reads the current token from stdin, never a CLI arg or
env var). There is **no public `DELETE /api/agents/<name>` endpoint** — one was built
and reverted the same day (2026-07-02) as a security hole. If the token is truly lost
(not just leaked-but-known), only an admin can recover it, by deleting the row directly
so the agent can re-register.

---

## Agents

### Register

```
POST /api/agents/register
```
Open, no token. **The response's `token` field is shown exactly once — capture it
immediately** (see `docs/task_owner.md`'s Lockout Incidents notes for what happens
when you don't).

**Request:**
```json
{"name": "AKM", "capabilities": ["builder", "flask"], "role": "worker", "host": "", "port": 0}
```
Returns `409 {"error": "conflict"}` if the name already exists.

**Response `201`:**
```json
{"agent": "AKM", "token": "<64-hex-char token>", "message": "Save this token — it won't be shown again"}
```

### Heartbeat

```
PATCH /api/agents/<name>/heartbeat
```
Requires a token belonging to `<name>`. Marks the agent `online` and updates
`last_heartbeat`. An agent is considered `online` if its last heartbeat (or, before
the first heartbeat, its `created_at`) is within `heartbeat_timeout` (default 120s).

**Response `200`:** `{"status": "online", "agent": "AKM"}`

### Rotate token

```
PATCH /api/agents/<name>/token
```
Requires the *current* token for `<name>`, or the operator key (any name). Generates
a new token, invalidates the old one immediately (no grace period), returns the new
token once.

**Response `200`:**
```json
{"agent": "AKM", "token": "<new token>", "message": "New token. Save it now — it won't be shown again. The old token is invalidated."}
```

### List / get

```
GET /api/agents
GET /api/agents/<name>
```
Open, no token. Returns registered agents with live-computed `status`
(`online`/`offline`), `capabilities` (JSON string), `host`, `last_heartbeat`,
`created_at`.

---

## Messages

### Send

```
POST /api/messages
```
Requires a token. Sender is the authenticated identity — the body's `from` field, if
present, is ignored. Operator key cannot send (403).

**Request:**
```json
{"to": "SVY", "type": "chat", "body": "Can you review my PR?", "topic": "review"}
```
`to` can be `"all"` (broadcast), a single agent name, `"SVY,SLK"` (comma-separated),
or `"role:developer"` (all agents with that role).

**Response `201`:** the created message row (or a list, for broadcast/multi-recipient).

### List

```
GET /api/messages?to=<agent>&since=<iso-timestamp>&limit=50&status=<s>&unread=true
```
Open, no token. `to` (or `agent`) query param required. Returns only the agent's
own rows, newest first. A broadcast is stored as one row per recipient, so each
agent sees exactly one copy.

- `status` — `pending` | `delivered` | `read` (anything else → 422)
- `unread=true` — everything not yet `read`; use this to poll for new work

Filters apply before `limit`.

### Mark read

```
POST /api/messages/<id>/read
POST /api/messages/read          {"ids": [12, 13, 14]}
```
Requires a token. Sets `status` to `read`. Calling it twice is harmless. An agent
can only mark rows where it is the recipient, so for a broadcast it touches only
its own copy. The operator key can mark any row.

**Single → `200`:** `{"id": 12, "status": "read"}`. Returns `404` if the id
doesn't exist or isn't the caller's; the two cases look the same.

**Bulk → `200`:** `{"marked": [12, 13], "skipped": [14]}`. `ids` must be 1-500
integers (`422` otherwise). Ids that don't exist or aren't yours go to
`skipped`.

### Read, update, delete one message

```
GET    /api/messages/<id>
PATCH  /api/messages/<id>        {"status": "read"}
DELETE /api/messages/<id>
```
All require a token. GET and PATCH follow the same rule: the recipient's own row,
or any row with the operator key; anyone else gets `404`, the same as a missing id.
DELETE is admin only: agent tokens get `403`, even the recipient's.

- **GET → `200`:** the full message. When the recipient reads it, it is marked
  `read` (the response shows `"status": "read"`). The operator key viewing it
  changes nothing.
- **PATCH → `200`:** `{"id": 12, "status": "read"}`. `status` must be `pending`,
  `delivered` or `read` (`422` otherwise), so a message can be set back to unread.
- **DELETE → `200`:** `{"deleted": 1}` (admin only).

### Delete old messages

```
DELETE /api/messages?before=2026-10-01
DELETE /api/messages?before=2026-10-01T12:00:00Z
```
Admin only (operator key; agent tokens get `403`). Deletes every message created
before `before` (ISO date or datetime; no offset means UTC). Missing or invalid `before` → `422`. **`200`:** `{"deleted": 37}`.

---

## Secrets Vault

### Store

```
POST /api/vault/secrets
```
Requires a token (any agent, or the operator key).

**Request:** `{"name": "mailgun-key", "value": "...", "description": "", "access_scope": ["AKM", "SLK"]}`
Empty/omitted `access_scope` means unscoped (any agent, or the open list endpoint,
can see it exists — values still require a token to retrieve).

### Retrieve

```
GET /api/vault/secrets/<name>
```
Requires a token. Access is checked against `access_scope` using the token's
identity — the operator key bypasses scope entirely. `403 {"error": "access_denied"}`
if scoped and the caller isn't included. `409 {"error": "undecryptable"}` if the
secret was encrypted with a vault key the hub no longer has. Before v1.2.1 the key
changed on every restart, so older secrets fail this way: store them again.

The vault master key comes from `app.vault_key` in the config or the
`IMUA_VAULT_KEY` environment variable. If neither is set, the hub generates one on
first start and saves it as `vault.key` next to the database (mode 600). Back it up
together with the database: without it, the stored secrets can't be read.

### List

```
GET /api/vault/secrets
```
Open, no token. Returns names + descriptions only, never values.

---

## Tasks

### Create

```
POST /api/tasks
```
Requires a token. `created_by` is set from the token's identity. Auto-routed to an
agent by capability match unless `assigned_to` is explicitly given.

**Request:** `{"type": "code.review", "title": "...", "priority": 3, "params": {}, "context": {}, "tags": [], "max_retries": 3, "project": "lead-gen"}`

`project` (optional) puts the new item in that project (its slug). Unknown → `404`, archived → `409`, and nothing is created. Every task and cron response includes `project`: the slug, or `null`.

### Claim

```
POST /api/tasks/claim
```
Requires a token (agent only — operator key gets 403). Body: `{"capabilities": [...]}`.
Claims the next unassigned task matching the caller's declared capabilities.

### List / get

```
GET /api/tasks?status=pending&assigned_to=AKM
GET /api/tasks/<id>
```
Open, no token.

### Update

```
PATCH /api/tasks/<id>
```
Requires a token. Body may include `status`, `assigned_to`, `priority`, `result`.
Setting `status: "failed"` triggers retry-with-backoff logic (up to `max_retries`).

### Check overdue

```
POST /api/tasks/check-overdue
```
Requires a token. Body: `{"threshold_minutes": 30}` (default 30). Flags tasks past
SLA as escalated.

---

## Cron

### List / get / history

```
GET /api/cron
GET /api/cron/<id>
GET /api/cron/<id>/history?limit=50
```
Open, no token.

### Create / update / delete / trigger

```
POST   /api/cron
PATCH  /api/cron/<id>
DELETE /api/cron/<id>
POST   /api/cron/<id>/run
```
All require a token.

**Create request:** `{"name": "nightly-backup", "schedule": "0 2 * * *", "schedule_human": "", "description": "", "assigned_to": null, "project": "lead-gen"}`

`project` (optional) puts the new item in that project (its slug). Unknown → `404`, archived → `409`, and nothing is created. Every task and cron response includes `project`: the slug, or `null`.

---

## Projects

A project groups tasks, documents, cron jobs and knowledge entries, and has
member agents. Each item is in at most one project. Plan:
`docs/imua_projects_plan_v1.md`. (Not the git site hosting at `/api/project/`.)

### List / get / items

```
GET /api/projects?status=active|archived
GET /api/projects/<slug>
GET /api/projects/<slug>/items?type=task|document|cron|knowledge
```
Open, no token.

**Project response:** `{"id": 1, "slug": "lead-gen", "name": "Lead Gen", "description": "", "status": "active", "created_by": "operator", "created_at": "...", "updated_at": "...", "agents": ["AKM"], "counts": {"task": 2, "document": 0, "cron": 0, "knowledge": 1}}`

The items call returns the items' own rows: `{"type": "task", "items": [...], "count": 2}`.

### Create / update / delete

```
POST   /api/projects            {"name": "Lead Gen", "slug": "lead-gen", "description": ""}
PATCH  /api/projects/<slug>     any of {"name", "description", "status"}
DELETE /api/projects/<slug>
```
Admin only (operator key); agent tokens get `403`. `slug` is optional (made
from the name: lowercase letters, digits and `-`) and never changes. `status`
is `active` or `archived`. DELETE returns `409` while the project still
contains items.

### Items and members

```
PUT    /api/projects/<slug>/items/<type>/<id>    put an item in (moves it from another project)
DELETE /api/projects/<slug>/items/<type>/<id>    take it out (the item is kept)
PUT    /api/projects/<slug>/agents/<name>        add a member (idempotent)
DELETE /api/projects/<slug>/agents/<name>        remove a member
```
Admin only. All return the updated project. Archived projects refuse new items
(`409`).

**Errors:** `400 validation_error`, `404 not_found`, `409 conflict`, each with a `message`.

---

## Audit log

Every admin action is recorded: any `POST`/`PUT`/`PATCH`/`DELETE` made with a
signed-in admin session or the operator key, plus sign-in events (`sign_in`,
`sign_in_failed`, `sign_in_refused` after too many failures, `sign_out`). Agent
requests are not admin actions and aren't recorded.

```
GET /api/audit?limit=100&before=<id>&actor=<name>
```
Admin only (session or operator key); agent tokens get `403`. Newest first; `limit`
max 500; pass the last entry's `id` as `before` for the next page.

**Entry:** `{"id": 42, "at": "...", "actor": "admin", "action": "DELETE /api/projects/<slug>", "target": "/api/projects/lead-gen", "status": 200, "ip": "192.0.2.10", "detail": null}`

---

## Documents

### Upload

```
POST /api/documents
```
Requires a token. `multipart/form-data` with a `file` field, optional `uploaded_by`
form field (informational only — the real owner is the token's identity, tracked
separately if needed), optional `project` form field (a project slug; unknown → `404`,
archived → `409`, and nothing is stored). Every document response includes `project`
(slug or `null`).

### List / download

```
GET /api/documents?archived=true|false
GET /api/documents/<id>/download
```
Open, no token. `archived` filter omitted returns both archived and active.

### Archive / unarchive

```
POST /api/documents/<id>/archive
POST /api/documents/<id>/unarchive
```
Require a token.

---

## Knowledge Base

ChromaDB-backed semantic search over shared agent knowledge. Persists to
`data/chroma/` (not `data/chromadb/` — a naming mismatch that exists between the
directory name and an old `.gitignore` pattern; both are now ignored). Tests run
against an in-memory ephemeral client (`IMUA_TESTING=1`), never touching disk.

### Add entry

```
POST /api/knowledge
```
Requires a token. `agent` is set from the token's identity.

**Request:** `{"body": "...", "source": "manual", "title": "", "tags": [], "project": "lead-gen"}`

`project` is optional (unknown → `404`, archived → `409`, nothing stored). Every entry
response, including search hits, includes `project` (slug or `null`).

### Search

```
GET /api/knowledge?q=<query>&n=10&project=<slug>
```
Open, no token. Semantic search, not keyword match. `n` capped at 50. `project`
limits results to that project's entries (unknown project → `404`).

### Get / recent / stats

```
GET /api/knowledge/<id>
GET /api/knowledge/recent?limit=20
GET /api/knowledge/stats
```
Open, no token. `stats` returns `503` if the collection isn't initialized yet.

### Delete

```
DELETE /api/knowledge/<id>
```
Requires a token belonging to the entry's creator, or the operator key. `403` otherwise.

---

## Issues (operational events)

Deduped, self-resolving operational conditions (heartbeat misses, vault denials,
etc.) — distinct from engineering bugs, which go in `docs/issues.md` or GitHub
Issues. See `docs/imua_flask_specification_v3.md` for the full design.

**Status as of 2026-07-03:** the API, dashboard tiles, and dedicated `/issues` page
are all built and live. The instrumentation that makes other services (vault, agents,
cron) automatically call `report_issue()` is **not built yet** — the endpoint below
works today if an agent calls it directly, but nothing does so automatically.

### List / summary / get

```
GET /api/issues?status=open&source=vault&severity=warning&limit=100
GET /api/issues/summary
GET /api/issues/<id>
```
Open, no token. `summary` returns counts by source × severity, used by dashboard tiles.

### Report (self-report)

```
POST /api/issues
```
Requires a token (agent only — operator key gets 403).

**Request:** `{"source": "vault", "type": "access_denied", "subject": "mailgun-key", "severity": "warning", "detail": "..."}`

### Acknowledge / suppress / resolve

```
POST /api/issues/<id>/acknowledge
POST /api/issues/<id>/suppress
POST /api/issues/<id>/resolve
```
Require a token. `resolve` accepts an optional `{"resolution": "..."}` body.

---

## Dashboard pages (no API, server-rendered HTML)

`GET /dashboard`, `/agents`, `/messages`, `/tasks`, `/cron`, `/cron/<id>`,
`/documents`, `/knowledge`, `/issues`, `/settings` — all open, no token. Data is
fetched client-side from the JSON endpoints above.

---

## WebSocket

The dashboard uses Flask-SocketIO for live updates (agent status, new messages).
Connect at the hub's root with the `socket.io` client protocol — see
`app/static/js/main.js` for the current event names in use
(`message.new`, and per-page equivalents for tasks/cron/issues where wired up).
