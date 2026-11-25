# imua-mcp

MCP server for the [Imua](https://github.com/programmeroo/imua) hub — exposes
the Imua REST API as MCP tools and resources over stdio. Designed for any
MCP-aware client (Hermes, Claude Code, future agents).

## Status

**PR1a — scaffold.** Auth, client, and server bootstrap. No tools registered
yet (those come in PR1b).

## Install

```bash
# Editable install for development
pip install -e mcp/

# Or, when a tagged release exists
pip install imua-mcp
```

Requires `mcp` 1.x (`>= 1.2, < 2.0`). mcp 2.0 removed `mcp.server.fastmcp`;
this server has not been migrated to 2.x's `MCPServer` yet.

Install into a dedicated venv and point your MCP client at that venv's
interpreter. If the client's own runtime exports `PYTHONPATH` (Hermes does),
clear it for the subprocess — otherwise the venv can pick up packages built
for a different Python version (seen as `No module named
'pydantic_core._pydantic_core'`):

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  imua:
    command: /path/to/venv/bin/python
    args: ["-m", "imua_mcp.server", "--hub-url", "http://<hub-ip>:47280",
           "--agent-name", "SLK", "--token-file", "~/.hermes/SLK.token"]
    env:
      PYTHONPATH: ""
```

## Configuration

The server takes three required arguments and one optional flag:

| Flag | Required | Example | Purpose |
|---|---|---|---|
| `--hub-url` | no | `http://<hub-ip>:47280` | Imua hub base URL (default: `$IMUA_HUB_URL`, else `http://localhost:47280`) |
| `--agent-name` | yes | `SLK` | Canonical agent name (token identity) |
| `--token-file` | yes | `~/.hermes/SLK.token` | Mode-600 file containing the bearer token |
| `--timeout` | no | `30` | Per-tool-call timeout in seconds (default: 30) |

The token file **must** be mode 600 (or 400). The server refuses to start
otherwise. The installer script (PR1c) handles file creation from
`~/.hermes/.env`; for manual setup:

```bash
# From ~/.hermes/.env (mode 600) — extract token to a separate file
TOKEN=$(grep -oP 'IMUA_SLK_TOKEN=\K[a-f0-9]+' ~/.hermes/.env)
echo "$TOKEN" > ~/.hermes/SLK.token
chmod 600 ~/.hermes/SLK.token
rm -f /tmp/SLK.token  # don't leave it in /tmp
```

## Token discipline

This server follows `~/.hermes/skills/devops/imua-token-handling` Rule 8:

- Token is read from the mode-600 file at startup AND on each request
  (mtime-checked, supports rotation via `PATCH /api/agents/<name>/token`)
- Token value never appears in:
  - command-line arguments
  - environment variables
  - log lines (stdout is JSON-RPC only; stderr is one-line operator diagnostics)
  - error messages
  - response bodies

## Architecture

| File | Lines | Purpose |
|---|---|---|
| `imua_mcp/server.py` | ~80 | FastMCP bootstrap, stdio transport, argparse CLI |
| `imua_mcp/auth.py` | ~120 | Token file loader with mode-600 enforcement and rotation support |
| `imua_mcp/client.py` | ~140 | httpx wrapper with stable error envelope (per spec §3.3) |
| `imua_mcp/tools_read.py` | (PR1b, 6.9) | 16 read tools (incl. `list_projects`, `get_project`, `list_project_items`; `search_knowledge` takes `project`) + 5 read-only resources |
| `imua_mcp/tools_write.py` | (PR2a, 6.11) | 13 write tools: `send_message`, `mark_messages_read`, `create_task`, `claim_task`, `complete_task`, `add_knowledge`, `create_cron_job` (creates take an optional `project`), `report_issue`, `update_issue_status`, `get_secret`, `put_secret`, `rotate_token` (rewrites the token file atomically; restart other processes using the old token) |
| `tests/test_auth.py` | ~120 | Mode enforcement, file-missing clean error, no token in errors |
| `tests/test_client.py` | ~120 | Error envelope mapping (401/403/404/409/422/5xx/hub_unreachable/hub_timeout) |

## License

Proprietary. All rights reserved.
