"""Vault tools exposed to the agent as an in-process MCP server.

The vault is Kioku's OWN memory — it has full control: read, search, write, edit, delete, move.
No approval gate on the vault (this is its brain; it must curate it freely). The only thing it
cannot touch is its config spine (system/) and git internals, guarded in memory/vault.py.

Verify @tool / create_sdk_mcp_server signatures against your installed claude-agent-sdk.
"""
from claude_agent_sdk import tool, create_sdk_mcp_server

from ...memory import vault as V


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


@tool("vault_list", "List entries under a vault-relative directory.", {"path": str})
async def vault_list(args):
    return _text("\n".join(V.list_dir(args.get("path", ""))))


@tool("vault_read", "Read a markdown note by vault-relative path.", {"path": str})
async def vault_read(args):
    return _text(V.read(args["path"]))


@tool("vault_search", "Hybrid (BM25 + semantic) search; returns top-k paths + excerpts.",
      {"query": str, "k": int})
async def vault_search(args):
    from ...memory import retrieval
    hits = await retrieval.hybrid_search(args["query"], int(args.get("k", 6)))
    return _text("\n\n".join(f"{h['path']}\n{h['excerpt']}" for h in hits) or "no matches")


@tool("vault_write",
      "Create or overwrite a note (applies immediately — the vault is yours, no approval needed). "
      "Use for capturing, curating, and updating your memory.",
      {"path": str, "content": str})
async def vault_write(args):
    return _text(f"wrote {V.write(args['path'], args['content'])}")


@tool("vault_delete",
      "Delete a vault file or directory (applies immediately). Use to clear stale notes / clean up. "
      "Your config spine (system/) is protected and cannot be deleted.",
      {"path": str})
async def vault_delete(args):
    try:
        return _text(f"deleted {V.delete(args['path'])}")
    except Exception as e:  # noqa: BLE001
        return _text(f"could not delete: {e}")


@tool("vault_move",
      "Move or rename a vault path (applies immediately). Use to reorganise the vault "
      "(e.g. flatten an import into proper zones). system/ is protected as a source.",
      {"src": str, "dst": str})
async def vault_move(args):
    try:
        return _text(f"moved {args['src']} -> {V.move(args['src'], args['dst'])}")
    except Exception as e:  # noqa: BLE001
        return _text(f"could not move: {e}")


vault_server = create_sdk_mcp_server(
    name="vault", version="0.3.0",
    tools=[vault_list, vault_read, vault_search, vault_write, vault_delete, vault_move],
)
