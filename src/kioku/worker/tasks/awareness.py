"""Awareness: connector pollers, alert rules, signal watches."""
import json


from ..celery_app import app
from ..._compat import run_sync
from ...agent.orchestrator import run_agent
from ...memory import db, switch
from ...frontdoor.notify import notify

from ._common import _record_and_notify


@app.task(name="kioku.worker.tasks.poll_all_task")
def poll_all_task():
    """Proactive loop: poll every enabled connector into the signals store."""
    if switch.is_paused():
        return {"paused": True}
    from ...memory import connectors
    from .. import pollers
    results = {}
    for c in connectors.enabled():
        if c.get("kind") not in ("metrics", "poller"):
            continue                                   # mcp connectors are tools, not polled
        try:
            pollers.poller_for(c["name"])()
            results[c["name"]] = "ok"
        except NotImplementedError as e:
            results[c["name"]] = f"unwired: {e}"
        except Exception as e:  # noqa: BLE001
            results[c["name"]] = f"error: {e}"
    return results


@app.task(name="kioku.worker.tasks.check_alerts_task")
def check_alerts_task():
    """Proactive loop: run alert rules (deadlines now; more as signals flow)."""
    if switch.is_paused():
        return {"paused": True}
    from .. import alerts
    return alerts.run_all()


@app.task(name="kioku.worker.tasks.watch_signals_task")
def watch_signals_task():
    """Phase 3.1: event-driven alerts — notify on state CHANGES in the signal store (deploy
    down/recovered, error spike, new PRs). Deterministic + deduped → free and quiet by default."""
    if switch.is_paused():
        return {"paused": True}
    from .. import alerts
    return alerts.watch_signals()


@app.task(name="kioku.worker.tasks.check_watches_task")
def check_watches_task():
    """Watch mode: re-check each thing Kioku is watching, compare to the last observed state, and
    ping Telegram on a MATERIAL change. Deterministic gate (only runs if there are watches);
    each check is one budget-gated, pausable research turn."""
    if switch.is_paused():
        return {"paused": True}
    from ...memory import watches
    items = watches.load()
    if not items:
        return {"watches": 0}
    fired = 0
    for w in items:
        run_id = db.create_run_sync("watch", f"watch: {w.get('what', '')[:40]}", "work")
        prompt = (
            f"You are monitoring this for the owner: {w.get('what', '')}\n"
            f"What you observed last time:\n{w.get('last_state') or '(nothing yet — first check)'}\n\n"
            "Check the CURRENT state now (use the web and connectors as needed). Reply with ONLY JSON:\n"
            '{"state": "<=60-word snapshot of what you see now", "changed": true or false, '
            '"alert": "<=40 words on what changed (empty if nothing)"}\n'
            "changed=true ONLY for a genuine, material change since last time (ignore noise). On the "
            "first check, changed=false unless something is already clearly noteworthy.")
        out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="research",
                                 retrieve_query=w.get("what", "")))
        _record_and_notify(run_id, out)
        if out.get("skipped"):
            continue
        try:
            txt = out.get("text", "")
            data = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            continue
        if data.get("state"):
            watches.update_state(w["id"], str(data["state"]))
        if data.get("changed") and data.get("alert"):
            notify(f"👁️ Watch — {w.get('note') or w.get('what', '')[:40]}: {data['alert']}")
            fired += 1
    return {"watches": len(items), "alerts": fired}
