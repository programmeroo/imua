"""imua-mcp server entrypoint — stdio transport.

PR1a bootstrap + PR1b read tools + PR2a write tools (send_message, mark_messages_read so far).

Bootstraps the FastMCP server, loads the token file, validates the hub,
and registers tools before entering the stdio loop.

Usage:
    imua-mcp --agent-name <name> --hub-url <url> --token-file ~/.hermes/<name>.token
    imua-mcp --agent-name AKM  # hub from $IMUA_HUB_URL, else http://localhost:47280
"""

from __future__ import annotations

import argparse
import os
import sys
from mcp.server.fastmcp import FastMCP

from imua_mcp.auth import TokenFile, TokenFileError
from imua_mcp.client import ImuaClient, ImuaClientError
from imua_mcp.tools_read import register_read_tools
from imua_mcp.tools_write import register_write_tools


def main() -> int:
    """Parse args, validate, bootstrap server, run."""
    parser = argparse.ArgumentParser(description="MCP server for the Imua hub")
    parser.add_argument("--agent-name", required=True, help="Agent name (for token identity)")
    parser.add_argument(
        "--hub-url",
        default=os.environ.get("IMUA_HUB_URL", "http://localhost:47280"),
        help="Hub base URL (default: $IMUA_HUB_URL, else http://localhost:47280)",
    )
    parser.add_argument(
        "--token-file",
        help="Path to token file (default: ~/.hermes/<agent-name>.token)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Tool call timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    # Token file path: explicit arg or default ~/.hermes/<name>.token
    token_file_path = args.token_file
    if not token_file_path:
        from pathlib import Path
        token_file_path = str(Path.home() / ".hermes" / f"{args.agent_name}.token")

    # Load token (enforces mode 600)
    try:
        token_file = TokenFile(token_file_path)
    except TokenFileError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Validate hub connectivity (health check)
    token_file.read()  # fail early if the file is unreadable
    client = ImuaClient(base_url=args.hub_url, token=token_file.read, timeout=args.timeout)
    try:
        health = client.get("/api/health")
        if not health:
            print(f"ERROR: hub health check failed (empty response)", file=sys.stderr)
            return 1
    except ImuaClientError as e:
        print(f"ERROR: hub unreachable ({e.message})", file=sys.stderr)
        return 1

    # FastMCP instance
    mcp = FastMCP(
        name="imua-mcp",
        instructions=(
            "Imua hub MCP server. Authenticated as the agent named via --agent-name. "
            "Read-only tools: list/get agents, messages, tasks, documents, secrets, knowledge, projects. "
            "Write tools: send_message (send/broadcast a message to other agents), "
            "mark_messages_read (mark your own messages read after handling them; poll with "
            "list_messages(unread=True)), create_task / claim_task / complete_task (task queue; "
            "create_task takes an optional project), add_knowledge and create_cron_job (both take "
            "an optional project), report_issue and update_issue_status (Issues page), "
            "get_secret / put_secret (vault; never repeat a secret value), rotate_token. "
            "Resources: imua://self, imua://agents/<name>, imua://tasks/<id>, etc."
        ),
    )

    # Hold references on the instance so tools can access them
    mcp._imua_token_file = token_file  # type: ignore[attr-defined]
    mcp._imua_client = client  # type: ignore[attr-defined]
    mcp._imua_agent_name = args.agent_name  # type: ignore[attr-defined]

    # Register read-only tools and resources (PR1b)
    register_read_tools(mcp, token_file, client, args.agent_name)
    # Register write tools (PR2a)
    register_write_tools(mcp, token_file, client, args.agent_name)

    # Run the server on stdio
    try:
        mcp.run()
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"ERROR: server crashed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
