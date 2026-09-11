"""Watch tools — let Kioku keep an eye on things and alert the owner when they change.

A watch is re-checked on a schedule; when it materially changes vs the last observation, the change
is pushed to Telegram. Use for "watch this job posting", "keep an eye on competitor X's reviews",
"tell me if this metric moves", "watch for a reply on that thread".
"""
from claude_agent_sdk import tool, create_sdk_mcp_server

from ...memory import watches as W


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


@tool("watch_add",
      "Start watching something and alert him when it materially changes. what = a clear, "
      "self-contained description of what to monitor and where to look (a URL, a person/thread, a "
      "metric). note = a short label for the alert.",
      {"what": str, "note": str})
async def watch_add(args):
    wid = W.add(args["what"], args.get("note", ""))
    return _text(f"watching ✓ id={wid} — I'll ping you when it changes: {args['what'][:80]}")


@tool("watch_list", "List what you're currently watching.", {})
async def watch_list(args):
    items = W.load()
    if not items:
        return _text("not watching anything yet")
    return _text("\n".join(f"{i['id']} · {i.get('note') or i['what'][:70]}" for i in items))


@tool("watch_remove", "Stop watching something by its id.", {"id": str})
async def watch_remove(args):
    n = W.remove(args["id"])
    return _text("stopped watching ✓" if n else "no watch with that id")


watch_server = create_sdk_mcp_server(
    name="watch", version="0.1.0",
    tools=[watch_add, watch_list, watch_remove],
)
