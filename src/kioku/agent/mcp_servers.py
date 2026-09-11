"""Mount external MCP servers as tools in a run — two shapes:

1. **Static remote MCP** — a `kind: mcp` connector with a `url` + a bearer token named in
   `auth_env`. Mounted with an `Authorization: Bearer <token>` header.

2. **Composio hosted MCP URL** — ONE endpoint exposes *all* your connected Composio apps
   (Gmail, Calendar, Drive, Sheets, LinkedIn, …). This is the "MCP URL for any MCP client"
   from the Composio dashboard: a fixed URL (`https://connect.composio.dev/mcp`) authenticated
   with an **`x-consumer-api-key`** header whose value is `COMPOSIO_API_KEY` (the `ck_…` key).
   Enabled by the `composio` connector (provider: tool_router) + `COMPOSIO_API_KEY`. No
   session-minting call and no `COMPOSIO_USER_ID` — the consumer key IS the identity.

Anything unconfigured (missing url/token/key) is skipped cleanly — never mounted half-set. If the
key is wrong or Composio is down, the Agent SDK just reports the server unavailable, not a crash.

Verify the external-server config shape and how allowed_tools names external tools against your
pinned `claude-agent-sdk`; the `{type: http, url, headers}` shape below follows the docs.
"""
import logging
import os

from ..memory import connectors

log = logging.getLogger("kioku.mcp")

# Composio's hosted MCP endpoint (the "MCP URL for any MCP client" on the dashboard). Overridable
# via COMPOSIO_MCP_URL if Composio changes it. Auth header is x-consumer-api-key = COMPOSIO_API_KEY.
COMPOSIO_MCP_URL = os.getenv("COMPOSIO_MCP_URL", "https://connect.composio.dev/mcp")


def _record_composio_status(ok: bool, reason: str) -> None:
    """Persist the last Composio mount outcome as a signal so /status + Kioku itself can see WHY
    connectors are (un)available, instead of tools silently vanishing. Never fatal."""
    try:
        from ..memory import db
        db.record_signal_sync("composio", "connectors.composio", {"ok": ok, "reason": reason})
    except Exception:  # noqa: BLE001
        pass


def _composio_config() -> tuple[dict | None, str]:
    """Build the Composio MCP mount config (or None + a human reason). No network call — the hosted
    URL is fixed; the SDK connects to it at run time. Reason is logged/recorded so nothing is silent."""
    if not any(c.get("name") == "composio" and c.get("kind") == "mcp"
               for c in connectors.enabled()):
        return None, "composio connector disabled in connectors.yaml"
    api_key = os.getenv("COMPOSIO_API_KEY", "")
    if not api_key:
        return None, "COMPOSIO_API_KEY not set on this service (the WORKER runs live agent turns)"
    return ({"type": "http", "url": COMPOSIO_MCP_URL,
             "headers": {"x-consumer-api-key": api_key}},
            f"mounted {COMPOSIO_MCP_URL} (x-consumer-api-key)")


def _composio_server() -> dict | None:
    """Return the Composio MCP mount config, else None. Outcome is logged + recorded (the
    connectors.composio signal) rather than swallowed silently."""
    server, reason = _composio_config()
    (log.info if server else log.warning)("composio %s — %s",
                                          "mounted" if server else "not mounted", reason)
    _record_composio_status(server is not None, reason)
    return server


def composio_selftest() -> dict:
    """On-demand diagnostic (dashboard / Kioku 'why can't you use composio?'): reports whether the
    mount config is complete without making a network call."""
    server, reason = _composio_config()
    return {"ok": server is not None, "reason": reason, "url": COMPOSIO_MCP_URL,
            "api_key_set": bool(os.getenv("COMPOSIO_API_KEY"))}


def external_servers() -> dict:
    servers = {}
    for c in connectors.enabled():
        if c.get("kind") != "mcp" or c.get("provider") == "tool_router":
            continue  # composio (tool_router) is handled separately, below
        url = c.get("url", "")
        token = os.getenv(c.get("auth_env", ""), "") if c.get("auth_env") else ""
        if not url or "<your-" in url or (c.get("auth_env") and not token):
            continue  # not configured yet — skip cleanly
        servers[c["name"]] = {
            "type": "http",
            "url": url,
            "headers": {"Authorization": f"Bearer {token}"} if token else {},
        }
    comp = _composio_server()
    if comp:
        servers["composio"] = comp
    return servers


def external_allowed(server_names: list[str]) -> list[str]:
    """Auto-approve every tool from each mounted external server. The SDK expects a wildcard
    (`mcp__<server>__*`) or explicit tool names — a bare `mcp__<server>` matches nothing."""
    return [f"mcp__{name}__*" for name in server_names]
