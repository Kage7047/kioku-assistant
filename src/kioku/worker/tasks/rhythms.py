"""Scheduled rhythms: morning brief, evening digest, weekly review, and user-defined schedules."""
import json
from datetime import date


from ..celery_app import app
from ..._compat import run_sync
from ...agent.orchestrator import run_agent
from ...memory import db, vault, switch
from ...frontdoor.notify import notify, notify_file

from ._common import _r, _record_and_notify
from .agency import propose_skill_task


@app.task(name="kioku.worker.tasks.morning_brief_task")
def morning_brief_task(_label: str = "brief"):
    """Proactive chief-of-staff brief. Runs as a full agent with connectors mounted, so it can
    scan the calendar + mail live and fold in dev/ops signals. Non-essential → pauses (and says
    so) if the budget is tight."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("morning_brief", "morning brief", "triage")  # own row: valid id + budget accounting
    sig = db.recent_signals_sync(30)
    prompt = (
        "Prepare the owner's morning brief — act as their chief of staff, not a log printer.\n"
        "Scan, then lead with the single most important thing:\n"
        "1. Today's calendar — meetings, deadlines, anything time-sensitive (use the calendar tool).\n"
        "2. Mail that needs a reply or decision — surface it, draft nothing, SEND nothing (gmail; read-only here).\n"
        "3. Dev/ops from the signals below — a down deploy, failing CI, error spike, or budget mode.\n"
        "4. One or two concrete nudges toward their live priorities (their active projects and goals).\n"
        "Treat money/health items as sensitive: mention only if genuinely urgent, briefly.\n"
        "Format: your voice, greet them warmly, one lead line then short scannable sections; skip any\n"
        "empty section; no filler. If a connector isn't reachable, just skip it silently.\n\n"
        "SIGNALS (JSON):\n" + json.dumps(sig, default=str)[:4000])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, verbosity="normal"))
    if not out.get("skipped"):
        path = vault.write(f"_reports/brief-{date.today().isoformat()}.md", out["text"])
        notify("☀️ " + out["text"][:3500])          # full brief (Telegram cap 4096); archived in _reports
        notify_file(path, "☀️ Morning brief")
    else:
        # Never let the brief vanish silently — the top complaint. Say why it didn't run.
        why = (out.get("text") or "").strip() or "budget/usage limit reached"
        notify("☀️ No morning brief today — " + why[:400])
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.evening_digest_task")
def evening_digest_task():
    """Evening wind-down (the other half of the morning/evening rhythm). Short, calm end-of-day:
    what moved today, what's still open, what's on tomorrow. Non-essential + pausable."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("evening_digest", "evening wind-down", "work")
    sig = db.recent_signals_sync(30)
    prompt = (
        "Prepare the owner's evening wind-down — calm, end-of-day tone, not a fresh to-do dump. In a few "
        "short lines:\n"
        "1. What actually moved today (from today's journal/runs, dev-ops signals, and — if relevant "
        "— mail/calendar).\n"
        "2. Anything still open or waiting on the owner.\n"
        "3. What's on their calendar tomorrow (check it).\n"
        "4. The single thing worth doing first tomorrow.\n"
        "Keep it brief and human. If today was quiet, say so.\n\n"
        "SIGNALS (JSON):\n" + json.dumps(sig, default=str)[:3000])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False))
    if not out.get("skipped") and out.get("text"):
        path = vault.write(f"_reports/evening-{date.today().isoformat()}.md", out["text"])
        notify("🌙 " + out["text"][:3500])
        notify_file(path, "🌙 Evening wind-down")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.tick_schedules_task")
def tick_schedules_task():
    """Per-minute deterministic gate: find self-scheduled tasks due now and ENQUEUE each as its own
    run (so one slow task can't block the tick), deduped so a schedule never double-fires in a minute."""
    if switch.is_paused():
        return {"paused": True}
    from ...memory import scheduler
    stamp = scheduler.now_local().strftime("%Y%m%d%H%M")
    queued = []
    for s in scheduler.due()[:10]:                       # cap per tick (defensive)
        key = f"sched:fired:{s['id']}:{stamp}"
        try:
            if _r.get(key):
                continue
            _r.set(key, "1", ex=180)
        except Exception:  # noqa: BLE001
            pass
        run_scheduled_task.delay(s)
        queued.append(s["id"])
    return {"queued": queued}


@app.task(name="kioku.worker.tasks.run_scheduled_task")
def run_scheduled_task(s: dict):
    """Run one self-scheduled task with the FULL toolset (arbitrary automations may need web,
    gmail/drive, calendar, the vault) and Telegram the result."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("scheduled", f"scheduled: {s.get('note') or s.get('task', '')[:50]}", "work")
    out = run_sync(run_agent(run_id, s.get("task", ""), "work", essential=False,
                             retrieve_query=s.get("task", "")))
    if not out.get("skipped") and out.get("text"):
        notify(f"⏰ {s.get('note') or 'Scheduled task'}:\n{out['text'][:3000]}")
    elif out.get("limited"):
        notify(f"⏰ Scheduled '{s.get('note') or s.get('task', '')[:40]}' skipped — usage limit.")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.weekly_review_task")
def weekly_review_task(_label: str = "weekly"):
    """Learning loop: weekly retro from journal + signals, then propose a skill."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("weekly_review", "weekly review", "work")  # own row: valid id + budget accounting
    sig = db.recent_signals_sync(50)
    prompt = ("Write a concise weekly review from these signals + recent work: wins, misses, "
              "what to focus on next week. JSON signals:\n" + json.dumps(sig, default=str)[:5000])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False))
    if not out.get("skipped"):
        wpath = vault.write(f"_reports/weekly-{date.today().isoformat()}.md", out["text"])
        notify("🗓️ Weekly review ready:\n" + (out.get("text") or "")[:1500])
        notify_file(wpath, "🗓️ Weekly review — full report")
    _record_and_notify(run_id, out)
    propose_skill_task.delay()  # chain a skill proposal (creates its own run)
    return out.get("text")
