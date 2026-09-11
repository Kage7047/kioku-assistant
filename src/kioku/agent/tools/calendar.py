"""Calendar tool stub. The REAL calendar is Google Calendar via Composio (connectors) — these
built-in tools are non-functional placeholders and tell the agent to use the connector instead,
so it never thinks it booked something when it didn't."""
from claude_agent_sdk import tool, create_sdk_mcp_server

_USE_COMPOSIO = ("These built-in calendar tools are NOT connected. Use the Google Calendar "
                 "(Composio) tools to actually read or change the calendar — creating/updating/"
                 "RSVPing events is pre-approved, so just do it.")


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


@tool("calendar_find_slots", "STUB — not connected. Use the Google Calendar (Composio) tools instead.",
      {"date": str, "duration_min": int})
async def calendar_find_slots(args):
    return _text(_USE_COMPOSIO)


@tool("calendar_book", "STUB — not connected. Use the Google Calendar (Composio) tools instead.",
      {"title": str, "start": str, "end": str})
async def calendar_book(args):
    return _text(_USE_COMPOSIO)


calendar_server = create_sdk_mcp_server(
    name="calendar", version="0.1.0",
    tools=[calendar_find_slots, calendar_book],
)
