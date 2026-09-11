"""Scheduler tools — let Kioku set up recurring tasks for itself ("send me X every Friday").

Schedules persist in the vault (system/schedules.json); a per-minute worker tick runs due ones and
sends the result to Telegram. cron is 5-field local time: minute hour day-of-month month day-of-week.
"""
from claude_agent_sdk import tool, create_sdk_mcp_server

from ...memory import scheduler as S


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


@tool("schedule_add",
      "Schedule a RECURRING task for yourself. cron = 5 fields (minute hour day-of-month month "
      "day-of-week, local time; e.g. '0 9 * * 5' = every Friday 09:00). task = the full instruction "
      "to carry out each time it fires (its result is sent to the user on Telegram). note = a short "
      "label for that alert.",
      {"cron": str, "task": str, "note": str})
async def schedule_add(args):
    try:
        sid = S.add(args["cron"], args["task"], args.get("note", ""))
        return _text(f"scheduled ✓ id={sid} · '{args['cron']}' · {args['task'][:80]}")
    except Exception as e:  # noqa: BLE001
        return _text(f"could not schedule: {e}. cron is 5 fields, e.g. '0 9 * * 5' = Fri 09:00, "
                     "'30 7 * * *' = daily 07:30, '0 18 * * 0' = Sun 18:00.")


@tool("schedule_once",
      "Run a task ONCE after a delay in minutes, then report the result to Telegram. Use for "
      "'report back in 2 hours', 'remind me in 30 min', 'check on X later', or to update the owner on a "
      "long job's progress. Not recurring — for that use schedule_add.",
      {"delay_minutes": int, "task": str, "note": str})
async def schedule_once(args):
    from ...worker.tasks import run_scheduled_task           # lazy: avoid import cycle at load
    mins = max(1, int(args.get("delay_minutes", 60)))
    run_scheduled_task.apply_async(
        args=[{"task": args["task"], "note": args.get("note", ""), "id": "once"}],
        countdown=mins * 60)
    return _text(f"will do that in {mins} min and report back to you ✓")


@tool("schedule_list", "List the recurring tasks you've scheduled.", {})
async def schedule_list(args):
    items = S.load()
    if not items:
        return _text("no scheduled tasks yet")
    return _text("\n".join(f"{i['id']} · {i['cron']} · {i.get('note') or i['task'][:70]}" for i in items))


@tool("schedule_remove", "Remove a scheduled task by its id.", {"id": str})
async def schedule_remove(args):
    n = S.remove(args["id"])
    return _text("removed ✓" if n else "no schedule with that id")


scheduler_server = create_sdk_mcp_server(
    name="scheduler", version="0.2.0",
    tools=[schedule_add, schedule_once, schedule_list, schedule_remove],
)
