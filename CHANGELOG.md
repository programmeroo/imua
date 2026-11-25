# Changelog

All notable versions of Imua. This file tracks release-level freezes only.

## v2.0 — 2026-11-17

Hub `2.0.0`, MCP server `0.5.0`. Builds on v1.3 (admin sign-in, Projects): adds the
audit log, and MCP tools so agents can do their whole job, projects included,
through MCP.

**Upgrading (read first)**
- Hub: same steps as any upgrade (back up `data/`, pull, rebuild, replace the
  container). The new `audit_log` table is created on start.
- Agents using the MCP server: pull and reinstall it (`pip install -e mcp`) to get
  the new tools. Nothing else changes for agents.

**Audit log** (PRs #57, #58)
- New: every admin action is recorded: any write made with a signed-in admin
  session or the operator key, plus `sign_in`, `sign_in_failed`, `sign_in_refused`
  (after too many failures) and `sign_out`. Each entry has when, who, action, the
  item, the result and the IP. Routes added later are covered automatically.
  Agent requests aren't admin actions and aren't recorded.
- New: `GET /api/audit` (admin only), and an **Audit Log** panel in Settings with a
  filter by who and paging.

**MCP server** (PRs #59–#62) — 13 write tools, up from 2
- New: `create_task`, `claim_task`, `complete_task`; `add_knowledge`,
  `create_cron_job` (creates take an optional `project`); `report_issue`,
  `update_issue_status`; `get_secret`, `put_secret`; `rotate_token`.
- `rotate_token` rewrites the token file atomically, keeps the session working on
  the new token, and never returns the token. If the file can't be written, the
  new token is kept in memory and backed up to the vault under a fresh name.
  Other processes using the old token (e.g. `join.py`'s heartbeat) must be
  restarted.
- Fixed: the server used a copy of the token taken at startup, so a token file
  rotated elsewhere wasn't picked up until a restart. It now re-reads the file.

**Fixes**
- Hidden buttons stayed visible, e.g. the Agents page's Copy button before a join
  command was generated. (#58)

**Known gaps**
- The vault can't replace a secret, so after a rotation the vault copy
  `<agent>_token` still holds the old token. `join.py --rotate`'s vault save fails
  (409) for the same reason. Fix planned in task 5.20.
- The audit log grows without limit; pruning is planned with the other prunes
  (5.14–5.20).

## v1.3 — 2026-11-17

Hub `1.3.0`, MCP server `0.4.0`. Admin sign-in for the dashboard, and Projects.
Plans: `docs/imua_admin_security_plan_v1.md` (tasks 5.2–5.9) and
`docs/imua_projects_plan_v1.md` (tasks 6.1–6.9).

**Upgrading (read first)**
- Every dashboard page now needs a signed-in admin. There is no default account:
  after upgrading, create one on the hub's machine with
  `python scripts/create_admin.py --username <you>`
  (Docker: `docker exec -it imua python scripts/create_admin.py --username <you>`).
  Passwords need 12+ characters. `--reset` sets a new password.
- Agents are unaffected: same tokens, same address, same API.
- The Issues page no longer asks for the operator key, and any key a browser
  saved earlier is deleted.
- New files next to the database: `session.key` (signs sign-in cookies). Back it
  up with `vault.key` and `imua.db`.

**Admin sign-in** (PRs #32–#38, #45–#48)
- New: admin accounts (`admin_users` table) and `scripts/create_admin.py`.
  Passwords are scrypt hashes; no default account. (#33)
- New: `/login` and sign-out. Signed out after 8 h idle or 24 h total. After 5
  failed sign-ins for the same IP and username in 15 minutes, further attempts
  are refused. One generic error for every failure. (#34–#36, #38)
- New: the session signing key is saved once as `session.key`, so restarts don't
  sign anyone out. (#32)
- New: every dashboard page redirects to sign-in unless an admin is signed in.
  Pages added later are covered automatically. (#46)
- New: CSRF protection on every write from a signed-in browser. Requests with a
  bearer token (agents, scripts, the operator key) are unaffected. (#45)
- New: admin-only API actions accept the signed-in session as well as the
  operator key. `auth.operator_key_enabled: false` turns the operator key off.
  Reading a vault secret's value still needs a token, never a browser. (#45, #47)
- Changed: the dashboard's own actions (cron, documents, knowledge, tasks, issue
  acknowledge/suppress/resolve) work through the session. (#47, #48)

**Projects** (PRs #37, #40–#44, #49–#55)
- New: projects group tasks, documents, knowledge entries and cron jobs, and have
  member agents. An item is in at most one project. Stored in three new tables,
  created automatically on start; existing tables are unchanged. (#40, #42)
- New: `/api/projects` to create, edit, archive and delete projects (delete is
  refused while a project still has items) and to add, move and remove items and
  members. Changes are admin-only. (#43)
- New: agents can pass `project` when creating a task, cron job, document or
  knowledge entry. Every such response includes `project`. Knowledge search takes
  `?project=`. (#49, #50)
- New: **Projects** in the dashboard menu: project cards, a page per project with
  tabs (Overview, Tasks, Documents, Knowledge, Cron, Agents), and controls to
  create, edit, archive, delete and to add or remove items and agents. (#51–#54)
- New: SDK `list_projects()`, `get_project()`, `list_project_items()`. MCP tools
  `list_projects`, `get_project`, `list_project_items`; `search_knowledge` takes
  `project`. (#55)

**Fixes**
- The Docker image now includes `scripts/`. Before, `create_admin.py` and the git
  `post-receive` hook were missing inside the container. (#44)
- Primary buttons turned white-on-white on hover, and Delete buttons looked like
  ordinary buttons. (#53)
- The sidebar's Sign out button was cut off. (#47)

## v1.2.1 — 2026-11-08

Hub `1.2.1`, MCP server `0.3.0`.

**SDK and MCP server** (PR #29)
- SDK: `check_messages(unread=True)` and `mark_read(ids)`.
- MCP: new `mark_messages_read` write tool. `list_messages` gains optional `unread`
  and `status` filters.

**Hub** (PR #28)
- Fixed: the vault master key was a new random key on every hub start, unless one
  was configured. So every restart or rebuild made all stored secrets unreadable. A
  generated key is now saved once as `vault.key` next to the database (mode 600) and
  reused, so it survives rebuilds on HUB-1. A key set in the config or in
  `IMUA_VAULT_KEY` still takes priority. An empty `vault.key` stops the hub from
  starting, instead of silently creating a new key that would make every stored
  secret unreadable.
- Secrets encrypted under an old key now return `409 undecryptable` with a
  "store it again" message, instead of a 500 error.
- The vault no longer invents a random key when none is supplied; it raises an
  error instead.
- Tests: the test run no longer writes a `vault.key` into the local `data/` folder.
- Fixed: the dashboard activity feed showed a hardcoded `v0.1.0`.

## v1.2 — 2026-11-08

Hub `1.2.0`, MCP server `0.2.0`. Fixes Imua hub issues #1 (AKM) and #2 (SLK); see
`docs/issues 11-8-26.md`.

**Hub (Flask, `app/`)**
- New: `POST /api/messages/<id>/read` and bulk `POST /api/messages/read`
  (`{"ids": [...]}`, up to 500). Token required. Agents can mark only their own
  messages (for a broadcast, only their own copy). The operator key can mark any.
  Marking twice is harmless. (PR #27)
- New: `GET /api/messages` takes `?status=pending|delivered|read` and
  `?unread=true`. Filtering happens before `limit`. (PR #27)
- Fixed: every agent's inbox included every other agent's copy of each
  broadcast (N copies per broadcast). Each agent now sees only its own. (PR #27)

**MCP server (`mcp/`)**
- New: `send_message` write tool (first write tool, PR2a).
- Fixed: the server and `join.py` could never connect to the hub. There were
  seven stacked bugs, including missing `/api/` prefixes on every call, the
  wrong health path, `token_file.token` instead of `read()`, a mode-600 check
  that can never pass on Windows, and a Windows console emoji crash in
  `join.py`.
- Fixed: the server crashed at import with mcp 2.x, because 2.0 removed
  `mcp.server.fastmcp`. The `mcp` package is now limited to
  `>= 1.2, < 2.0`, and the README documents clearing `PYTHONPATH` for the MCP
  subprocess. (PR #26)

## v1.1 — 2026-07-18

First tagged freeze of Imua. Baseline for the HUB-1 Docker deployment.

**Hub (Flask, `app/`)** — unchanged since the 2026-07-03 token-rotation release:
agent registry, message bus, secrets vault, dashboard, bare-git integration,
task queue, knowledge base (ChromaDB), operational issues, bearer-token auth,
self-service token rotation.

**New: Imua MCP server (`mcp/`)** — wraps the hub's REST API as MCP tools/resources
so any MCP client (Claude Code, the Hermes session-start hook, customer
deployments) can talk to the hub via the standard MCP protocol instead of raw
`curl` or the hand-rolled SDK. Per `docs/imua_mcp_server_specification_v1.md`:
- Bootstrap + auth (`--token-file`, mode 600 enforced), stdio transport
- 13 read-only tools (agents, messages, tasks, documents, secrets, knowledge)
  and 5 resources (`imua://self`, `agents/<name>`, `tasks/<id>`,
  `documents/<id>`, `knowledge/<query>`)
- No write tools yet (write mutations are a future PR2a)

**Fixed post-merge (2026-07-18, CLD):** the commit that landed the MCP server
bypassed its own PR review and reintroduced two bugs that PR had already fixed:
- Resource URIs used regex named-group syntax instead of FastMCP's `{param}`
  template syntax, which crashed `register_read_tools()` — and therefore the
  whole server — on every startup.
- Several tools built query strings via raw f-string concatenation, letting
  values containing `&`/`#`/`%` corrupt requests or inject extra query params.
  Now built with `urlencode()`.

Both are covered by regression tests in `mcp/tests/test_tools_read.py`.
