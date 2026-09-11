import json
from datetime import date

import redis

from .celery_app import app
from .._compat import run_sync
from ..config import settings
from ..agent.orchestrator import run_agent
from ..memory import db, vault, budget, switch
from ..observability.langfuse import trace_run
from ..frontdoor.notify import notify, notify_file

_r = redis.Redis.from_url(settings.redis_url)
_MODE_RANK = {"normal": 0, "conserve": 1, "haiku_only": 2, "halt_nonessential": 3, "exhausted": 4}


def _paused_finish(run_id) -> bool:
    """If Kioku is paused, close this run with the paused notice and return True (skip work).
    The SSE stream picks the terminal state up from Postgres, so Telegram/web still get told."""
    if switch.is_paused():
        db.finish_run_sync(run_id, status="done", result_text=switch.PAUSED_MSG)
        return True
    return False


def _record_and_notify(run_id, out):
    """Store cost on the run, then ping Telegram if the budget mode escalated."""
    cost = budget.cost_usd(out["model"], out["tokens_in"], out["tokens_out"])
    db.finish_run_sync(run_id, status="done",
                       result_text=out.get("text"), result_path=out.get("result_path"),
                       tokens_in=out["tokens_in"], tokens_out=out["tokens_out"], cost_usd=cost)
    # Prove prompt caching is working: record read/write cache tokens vs input (self-review shows the ratio).
    cr, cw = out.get("cache_read", 0), out.get("cache_write", 0)
    if cr or cw or out.get("tokens_in"):
        db.record_signal_sync("self", "cache.usage",
                              {"read": cr, "write": cw, "input": out.get("tokens_in", 0)})
    snap = budget.check_sync("triage", essential=True)
    prev = _r.get("budget:notified_mode")
    prev = prev.decode() if prev else "normal"
    if _MODE_RANK.get(snap["mode"], 0) > _MODE_RANK.get(prev, 0):
        notify(f"⚠️ Agent SDK credit {int(snap['fraction']*100)}% used "
               f"(${snap['spend']}/${snap['credit']}). Mode: {snap['mode']}. "
               f"${snap['remaining']} left this cycle.")
        _r.set("budget:notified_mode", snap["mode"])
    elif _MODE_RANK.get(snap["mode"], 0) < _MODE_RANK.get(prev, 0):
        _r.set("budget:notified_mode", snap["mode"])   # recovered (new cycle)
    # The agent can now write/edit/delete/move the vault freely during a run — persist whatever it
    # changed (commit is a no-op if nothing changed) and reindex the named result if there is one.
    from ..memory import vaultsync
    if out.get("result_path"):
        reindex_vault_task.delay([out["result_path"]])
    vaultsync.commit_push(f"run {str(run_id)[:8]}")


@app.task(name="kioku.worker.tasks.run_agent_task")
def run_agent_task(run_id: str, prompt: str, difficulty: str = "triage", essential: bool = True):
    if _paused_finish(run_id):
        return switch.PAUSED_MSG
    with trace_run(run_id, kind="ask", model=difficulty):
        try:
            # conversational=True: carry recent turns so /ask has continuity, not a cold start.
            out = run_sync(run_agent(run_id, prompt, difficulty, essential, conversational=True))
            _record_and_notify(run_id, out)
            return out["text"]
        except Exception as e:  # noqa: BLE001
            db.finish_run_sync(run_id, status="error", error=str(e))
            raise


@app.task(name="kioku.worker.tasks.vault_audit_task")
def vault_audit_task(run_id: str):
    """Kioku's first real job. Deterministic inventory (free) + a light model summary."""
    if _paused_finish(run_id):
        return switch.PAUSED_MSG
    with trace_run(run_id, kind="vault_audit", model="triage"):
        try:
            inv = vault.audit_inventory()
            summary_prompt = (
                "Here is a vault audit inventory as JSON. Write a 6-8 line plain-language "
                "summary: health, biggest issues, and the 3 highest-value cleanup actions.\n\n"
                + json.dumps(inv, ensure_ascii=False)[:6000]
            )
            out = run_sync(run_agent(run_id, summary_prompt, "triage", essential=True))
            report = _render_report(inv, out["text"])
            path = vault.write(f"_reports/audit-{date.today().isoformat()}.md", report)
            out["result_path"] = path
            _record_and_notify(run_id, out)
            return path
        except Exception as e:  # noqa: BLE001
            db.finish_run_sync(run_id, status="error", error=str(e))
            raise


def _inert_links(s: str) -> str:
    """Neutralize [[wikilinks]] so an audit report doesn't self-poison: if the report writes a
    dead-link target as a live [[x]], the NEXT audit scans the report and counts it as a fresh
    dead link (runaway: 30→100→200). Single brackets don't match the WIKILINK regex (\\[\\[)."""
    return s.replace("[[", "[").replace("]]", "]")


def _render_report(inv: dict, narrative: str) -> str:
    dirs = "\n".join(f"- `{d}` — {n}" for d, n in inv["by_dir"].items())
    orphans = "\n".join(f"- {o}" for o in inv["orphans"][:40])
    dead = "\n".join(f"- `{_inert_links(d)}`" for d in inv["dead_links"][:40])
    return f"""# Vault audit — {inv['generated_at']}

{narrative}

## Inventory
- files: **{inv['file_count']}**, size: **{inv['total_kb']} KB**
- orphans: **{inv['orphan_count']}**, dead links: **{inv['dead_link_count']}**

### By directory
{dirs}

### Orphans (first 40)
{orphans or '- none'}

### Dead links (first 40)
{dead or '- none'}
"""


@app.task(name="kioku.worker.tasks.reindex_vault_task")
def reindex_vault_task(paths=None):
    """(Re)embed changed notes into pgvector. Cheap: local embeddings, only changed files."""
    from ..memory import index
    return index.reindex_sync(paths)


@app.task(name="kioku.worker.tasks.reap_stale_runs_task")
def reap_stale_runs_task(minutes: int = 15):
    """Periodic: flip runs stuck in 'running' past the timeout to 'error' (killed mid-flight)."""
    n = db.reap_stale_runs_sync(minutes)
    return {"reaped": n}


@app.task(name="kioku.worker.tasks.poll_self_task")
def poll_self_task():
    """Real, no-external-API poller: record Kioku's own spend/mode over time as signals."""
    snap = budget.check_sync("triage", essential=True)
    db.record_signal_sync("self", "agent.spend_mtd",
                          {"spend": snap["spend"], "remaining": snap["remaining"],
                           "mode": snap["mode"], "fraction": snap["fraction"]})
    return snap


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


@app.task(name="kioku.worker.tasks.apply_write_task")
def apply_write_task(sha: str):
    """Apply an approved write ON THE WORKER (which owns the vault checkout), then index+push."""
    from ..memory import pending, vaultsync
    path = pending.apply_plan(sha)
    reindex_vault_task.delay([path])
    vaultsync.commit_push(f"apply {path}")
    notify(f"✅ applied {path}")
    return path


@app.task(name="kioku.worker.tasks.execute_approved_task")
def execute_approved_task(approval_id: str):
    """Execute an OUTBOUND action the user just approved (from the command center or /approve <id>).
    Runs the exact staged tool call once via a scoped run with a one-time grant (no re-gating)."""
    if switch.is_paused():
        notify("⏸ Paused — approve again after /resume.")
        return {"paused": True}
    from ..memory import approvals
    rec = approvals.pop(approval_id)
    if not rec:
        notify(f"⚠️ Approval {approval_id} not found (expired or already handled).")
        return {"error": "not found"}

    # Phase 4.4 — a self-improvement config edit: apply it deterministically (no model call), then push.
    if rec.get("kind") == "config-edit":
        from ..memory import vaultsync
        path, content, mode = rec["path"], rec.get("content", ""), rec.get("mode", "append")
        try:
            if mode == "append":
                existing = ""
                try:
                    existing = vault.read(path)
                except Exception:  # noqa: BLE001
                    pass
                body = (existing.rstrip() + "\n\n" + content + "\n") if existing.strip() else content + "\n"
                vault.write(path, body)
            else:
                vault.write(path, content if content.endswith("\n") else content + "\n")
            reindex_vault_task.delay([path])
            vaultsync.commit_push(f"self-edit {path}")
            notify(f"🛠 Applied self-improvement to {path} — {rec.get('rationale', '')[:120]} "
                   "(revertible via git).")
        except Exception as e:  # noqa: BLE001
            notify(f"🛠 Could not apply the self-edit to {path}: {e}")
        return {"applied": rec.get("path")}

    run_id = db.create_run_sync("approved_action", f"approved: {rec.get('desc', '')[:60]}", "work")
    prompt = (
        "The user has APPROVED this outbound action. Execute it now — call the tool exactly once "
        "with these arguments, then report the result in one line. Do nothing else.\n"
        f"tool: {rec['tool']}\narguments (JSON): {json.dumps(rec.get('input', {}), default=str)}\n"
        "If the tool errors, say so plainly.")
    # outbound_approved=True → bypassPermissions for THIS run (no gate) so the approved call runs.
    out = run_sync(run_agent(run_id, prompt, "work", essential=True, outbound_approved=True))
    if out.get("text"):
        notify(f"✅ Approved action done:\n{out['text'][:1500]}")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.handoff_result_task")
def handoff_result_task(hid: str):
    """A local Claude Code hand-off finished (Phase 3.5): file its result to the vault + notify."""
    from ..memory import handoff, vaultsync
    rec = handoff.get(hid)
    if not rec:
        return {"error": "not found"}
    status = rec.get("status", "done")
    icon = "🖥️✅" if status == "done" else "🖥️⚠️"
    body = (f"# Hand-off {hid} — {status}\n\n"
            f"**Task:** {rec.get('task','')}\n\n"
            f"**Repo:** {rec.get('repo') or '(none)'}\n\n"
            f"---\n\n{rec.get('result','') or '(no output returned)'}\n")
    path = vault.write(f"_reports/handoff-{hid}.md", body)
    vaultsync.commit_push(f"handoff {hid}")
    notify(f"{icon} Local coding hand-off {hid} {status} — {rec.get('task','')[:80]}\n"
           f"Filed to {path}.")
    notify_file(path, f"🖥️ Hand-off {hid} — result")
    return {"id": hid, "status": status, "path": path}


@app.task(name="kioku.worker.tasks.project_manager_task")
def project_manager_task(name: str):
    """Phase 4.6 — one project check-in: assess → plan → do the steps its autonomy level allows →
    report. Per-project aggregate budget cap (Redis); outbound/irreversible steps auto-gate."""
    if switch.is_paused():
        return {"paused": True}
    from ..agent import project
    c = project.get_charter(name)
    if not c:
        notify(f"🏗 No charter for project '{name}' — create projects/{name}/charter.md first.")
        return {"error": "no charter"}
    key = f"project:spend:{name}"
    spent = float(_r.get(key) or 0)
    if spent >= c["budget_cap_usd"]:
        notify(f"🏗 Project '{name}' has hit its ${c['budget_cap_usd']} cap (spent ${spent:.2f}) — "
               "its loop is paused until you raise the cap.")
        return {"capped": True, "spent": spent}
    run_id = db.create_run_sync("project_pm", f"project: {name}", "work")
    out = run_sync(run_agent(run_id, project.pm_prompt(c), "work", essential=False,
                             intent="automate", retrieve_query=f"{name} {c['goal']}"))
    cost = budget.cost_usd(out["model"], out.get("tokens_in", 0), out.get("tokens_out", 0))
    try:
        _r.incrbyfloat(key, cost)
        _r.expire(key, 60 * 86400)
    except Exception:  # noqa: BLE001
        pass
    if not out.get("skipped") and out.get("text"):
        notify(f"🏗 {name}:\n{out['text'][:2500]}")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.project_checkins_task")
def project_checkins_task():
    """Daily gate: run each project's PM check-in on its cadence (daily/weekly). No charters → no-op."""
    if switch.is_paused():
        return {"paused": True}
    import time as _t
    from ..agent import project
    ran = []
    for c in project.list_charters():
        name = c["name"]
        if c["checkin"] == "weekly":
            k = f"project:lastcheckin:{name}"
            if _t.time() - float(_r.get(k) or 0) < 6.5 * 86400:
                continue
            _r.set(k, str(_t.time()))
        project_manager_task.delay(name)
        ran.append(name)
    return {"ran": ran}


@app.task(name="kioku.worker.tasks.sync_vault_task")
def sync_vault_task():
    """Pull device edits, reindex what changed, then commit+push Kioku's own changes.
    Note: BM25 recall reads files live, so it's already fresh the moment a pull lands;
    the reindex keeps the pgvector side current too (incremental — no-op if embeddings off)."""
    from ..memory import vaultsync
    vaultsync.ensure_repo()            # pull device edits from git
    reindex_vault_task.delay()         # incremental: only changed files re-embed
    vaultsync.commit_push("periodic sync")


@app.task(name="kioku.worker.tasks.handle_input_task")
def handle_input_task(run_id: str, text: str, source: str = "telegram"):
    """Universal entry: classify intent, then capture / run a command / run the agent.
    This is what makes Kioku feel like one mind — you just talk, it figures out what you want."""
    # Wake-words always get through, even while paused, so you can never lock yourself out.
    if (text or "").strip().lower().lstrip("/") in ("resume", "wake", "wake up", "unpause", "start"):
        switch.set_paused(False)
        db.finish_run_sync(run_id, status="done", result_text="▶️ Awake again.")
        notify("▶️ Awake again. Back on watch.")
        return {"paused": False}
    # Phase 4.3 feedback: "mute <class>" / "unmute <class>" tunes proactive interrupt weights.
    low = (text or "").strip().lower()
    if low.split(None, 1)[0] in ("mute", "unmute") and len(low.split(None, 1)) > 1:
        from .interrupt import mute, unmute
        cmd, cls = low.split(None, 1)
        cls = cls.strip()
        w = unmute(cls) if cmd == "unmute" else mute(cls)
        msg = (f"🔔 Unmuted '{cls}' (weight {w:.2f})." if cmd == "unmute"
               else f"🔕 Muted '{cls}' — you'll hear less of it (weight {w:.2f}). Say 'unmute {cls}' to undo.")
        db.finish_run_sync(run_id, status="done", result_text=msg)
        notify(msg)
        return {"muted": cls, "weight": w}
    if _paused_finish(run_id):
        return switch.PAUSED_MSG
    from ..agent import router, capture, journal, skills
    r = run_sync(router.classify(text))
    intent = r["intent"]
    cmd = r.get("command")             # concrete command keyword, or None (precise — not substring)

    if intent == "capture":
        res = capture.triage_capture(text)
        db.finish_run_sync(run_id, status="done", result_path=res["path"],
                           result_text=f"captured as {res['type']}")
        notify(f"📥 captured → {res['type']} ({res['path']})")
        return res

    # Only run command machinery when we have a REAL command keyword. If the classifier said
    # "command" but nothing concrete matched, fall through and answer it as a normal question —
    # so a message that merely mentions "budget"/"audit" is never hijacked.
    if cmd:
        if cmd == "audit":
            return vault_audit_task(run_id)
        if cmd == "reindex":
            db.finish_run_sync(run_id, status="done", result_text="reindex enqueued")
            return reindex_vault_task.delay()
        if cmd in ("review", "weekly review"):
            db.finish_run_sync(run_id, status="done", result_text="weekly review enqueued")
            return weekly_review_task.delay()          # creates its own run
        if cmd.startswith("propose") or cmd in ("skill", "skills"):
            db.finish_run_sync(run_id, status="done", result_text="skill proposal enqueued")
            return propose_skill_task.delay()          # creates its own run
        if "import" in cmd:
            db.finish_run_sync(run_id, status="done", result_text="bulk import enqueued")
            notify("📚 importing everything under vault/_import/ …")
            return bulk_ingest_task.delay()            # files vault/_import/ → reference/imported/
        if cmd in ("organize", "organise", "digest", "connect"):
            db.finish_run_sync(run_id, status="done", result_text="digest/connect enqueued")
            notify("🧩 organizing the vault: rebuilding the map + digesting notes in batches…")
            return digest_batch_task.delay()           # index rebuild + batched digestion
        if cmd.startswith(("opportun", "job", "radar")):
            db.finish_run_sync(run_id, status="done", result_text="opportunity radar enqueued")
            notify("🎯 scanning the job boards for good-fit roles…")
            return opportunity_radar_task.delay()
        if cmd == "learn":
            db.finish_run_sync(run_id, status="done", result_text="learning pass enqueued")
            notify("🧠 reviewing the week to sharpen what I know about you…")
            return learn_task.delay()
        if cmd == "introspect":
            db.finish_run_sync(run_id, status="done", result_text="self-review enqueued")
            notify("🔍 reviewing my own runs — cost, errors, model mix, skills…")
            return self_review_task.delay()
        if cmd in ("ideas", "brainstorm", "proposals", "suggest"):
            db.finish_run_sync(run_id, status="done", result_text="proposals enqueued")
            notify("💡 thinking about what would move the needle for you…")
            return propose_ideas_task.delay()
        if cmd in ("pause", "resume"):
            switch.set_paused(cmd == "pause")
            msg = switch.PAUSED_MSG if cmd == "pause" else "▶️ Awake again. Back on watch."
            db.finish_run_sync(run_id, status="done", result_text=msg)
            notify(msg)
            return {"paused": cmd == "pause"}
        # budget / status
        snap = budget.check_sync("triage", essential=True)
        db.finish_run_sync(run_id, status="done",
                           result_text=f"💳 {snap['mode']} · ${snap['remaining']} of "
                                       f"${snap['credit']} left ({int(snap['fraction']*100)}% used)")
        notify(f"💳 {snap['mode']} · ${snap['remaining']} left")
        return snap

    # everything else -> a learned skill if one matches, else the agent flavored by intent
    sk = skills.find_matching(text)
    if sk:
        db.record_signal_sync("self", "skill.used", {"name": sk["name"]})   # skill maturation (3.4)
        prompt, difficulty = skills.render(sk, text), sk.get("model", "work")
        intent = sk.get("intent") or intent   # a skill can declare the tools it needs (e.g. draft)
    else:
        prompt, difficulty = f"[intent:{intent}] {text}", r["difficulty"]
    chan = {"web": "the web dashboard", "cli": "the CLI"}.get(source, "Telegram")
    prompt = f"[He is talking to you right now through {chan}.]\n" + prompt
    out = run_sync(run_agent(run_id, prompt, difficulty, r["essential"],
                             conversational=True, intent=intent,
                             verbosity=r.get("verbosity", "normal"),
                             retrieve_query=text))   # pre-inject relevant vault notes → 1-turn answers
    if not out.get("skipped"):
        journal.maybe_journal(intent, text, out.get("text", ""))   # the compounding loop
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.poll_all_task")
def poll_all_task():
    """Proactive loop: poll every enabled connector into the signals store."""
    if switch.is_paused():
        return {"paused": True}
    from ..memory import connectors
    from . import pollers
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
    from . import alerts
    return alerts.run_all()


@app.task(name="kioku.worker.tasks.tick_schedules_task")
def tick_schedules_task():
    """Per-minute deterministic gate: find self-scheduled tasks due now and ENQUEUE each as its own
    run (so one slow task can't block the tick), deduped so a schedule never double-fires in a minute."""
    if switch.is_paused():
        return {"paused": True}
    from ..memory import scheduler
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


@app.task(name="kioku.worker.tasks.watch_signals_task")
def watch_signals_task():
    """Phase 3.1: event-driven alerts — notify on state CHANGES in the signal store (deploy
    down/recovered, error spike, new PRs). Deterministic + deduped → free and quiet by default."""
    if switch.is_paused():
        return {"paused": True}
    from . import alerts
    return alerts.watch_signals()


@app.task(name="kioku.worker.tasks.propose_skill_task")
def propose_skill_task(_label: str = "propose"):
    """Learning loop: draft a reusable skill from recent journal work → inbox/skills/ for approval."""
    if switch.is_paused():
        return {"paused": True}
    import glob
    import os
    from ..config import settings
    run_id = db.create_run_sync("propose_skill", "propose skill", "work")  # own row: valid id + budget accounting
    entries = ""
    for f in sorted(glob.glob(os.path.join(settings.vault_path, "journal", "*.md")))[-7:]:
        try:
            entries += open(f, encoding="utf-8").read()[:1500] + "\n"
        except Exception:  # noqa: BLE001
            pass
    if not entries.strip():
        db.finish_run_sync(run_id, status="done", result_text="no journal yet")
        return "no journal"
    prompt = ("From these recent journal entries, identify ONE workflow worth turning into a "
              "reusable skill. Output a skill card exactly as:\n"
              "---\nname: <kebab-name>\nwhen: <comma-separated trigger phrases>\nmodel: work\n---\n"
              "<clear step-by-step instructions>\n\nJournal:\n" + entries[:6000])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False))
    if not out.get("skipped") and out.get("text"):
        name = "proposed-skill"
        for line in out["text"].splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip() or name
                break
        path = vault.write(f"inbox/skills/{name}.md", out["text"])
        notify(f"🧠 proposed skill '{name}' → approve by moving to system/skills/\n{path}")
        out["result_path"] = path
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


@app.task(name="kioku.worker.tasks.ingest_task")
def ingest_task(run_id: str, b64: str, filename: str, origin: str = "telegram"):
    """Ingest a file/photo (base64) into the brain: source copy + note + index + push."""
    import base64
    from ..agent import ingest
    data = base64.b64decode(b64)
    res = ingest.ingest_bytes(data, filename, origin)
    reindex_vault_task.delay([res["note"]])
    from ..memory import vaultsync
    vaultsync.commit_push(f"ingest {filename}")
    db.finish_run_sync(run_id, status="done", result_path=res["note"],
                       result_text=f"ingested {filename} ({res['kind']}, {res['chars']} chars)")
    notify(f"📎 learned from {filename} → {res['kind']} · {res['note']}")
    return res


def _flatten_wrapper(rel):
    """Collapse an import's wrapper ancestors to zone/filename so the map groups by real zone.
    `second-brain.md-export/second-brain/conversations/01.md` → `conversations/01.md`. Files at
    the import root or already at zone/file depth are left as-is."""
    from pathlib import Path
    parts = Path(rel).parts
    return Path(rel) if len(parts) <= 2 else Path(parts[-2], parts[-1])


@app.task(name="kioku.worker.tasks.bulk_ingest_task")
def bulk_ingest_task(subdir: str = "_import"):
    """Bulk-ingest a folder of exports dropped into the vault (default _import/). Deterministic and
    cheap: markdown/text is filed as notes as-is (preserving structure); other files (pdf/docx/csv/
    images) are extracted → source copy + note. One reindex + push at the end. NO model calls here —
    for an LLM 'study/organize' pass, ask Kioku afterwards (batched, budget-guarded)."""
    from pathlib import Path
    from ..agent import ingest
    from ..memory import vaultsync
    base = Path(vault.VAULT) / subdir
    if not base.exists():
        return {"error": f"drop your export into vault/{subdir}/ first"}
    dest = Path(vault.VAULT) / "reference" / "imported"
    ing = moved = skipped = 0
    for f in base.rglob("*"):
        if f.is_dir() or f.name == ".gitkeep":
            continue
        ext = f.suffix.lower()
        try:
            if ext in (".md", ".markdown", ".txt"):
                # Keep folder structure, but strip redundant single-child wrapper dirs (e.g. an
                # export nested as second-brain.md-export/second-brain/<zone>/…) so the map/graph
                # groups by real zone (conversations/projects/cvs) instead of one giant blob.
                target = dest / _flatten_wrapper(f.relative_to(base))
                target.parent.mkdir(parents=True, exist_ok=True)
                f.replace(target)
                moved += 1
            elif ext in ingest.IMAGE_EXT or ext in (".pdf", ".docx", ".csv"):
                ingest.ingest_bytes(f.read_bytes(), f.name, origin="import")
                f.unlink()                            # extracted → remove the original from _import
                ing += 1
            else:                                     # unknown type: preserve it, but out of _import
                target = dest / "_unprocessed" / f.name
                target.parent.mkdir(parents=True, exist_ok=True)
                f.replace(target)
                skipped += 1
        except Exception:  # noqa: BLE001
            skipped += 1
    # Leave _import EMPTY (bar .gitkeep) so the next batch starts clean — remove now-empty subdirs.
    for d in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()                                 # only removes if empty
        except OSError:
            pass
    reindex_vault_task.delay()
    vaultsync.commit_push("bulk import")
    # Don't leave the import as an orphaned dump: rebuild the structural map now (free) and
    # start digesting in cheap batches (understand + tag + connect each note over time).
    digest_batch_task.delay()
    notify(f"📚 bulk import: {ing} extracted, {moved} notes filed, {skipped} preserved as-is. "
           f"_import/ is clear for the next batch. Now digesting + connecting…")
    return {"ingested": ing, "moved": moved, "skipped": skipped}


@app.task(name="kioku.worker.tasks.digest_batch_task")
def digest_batch_task(limit: int = 12, chain: bool = True):
    """Make imports understandable + connected, WITHOUT bursting a subscription window.

    Free structural pass every time (rebuild zone indexes + root MAP → kills orphans), then a
    small model-driven batch (summary/type/tags/[[links]] per note). Budget-gated: if the guard
    has paused non-essential work, we still do the free indexing and defer the model batch.
    Re-enqueues itself (spread over time) until every note is digested."""
    if switch.is_paused():
        return {"paused": True}
    from ..agent import digest
    idx = digest.rebuild_indexes()                       # deterministic, free — always safe

    snap = budget.check_sync("triage", essential=False)
    if not snap["allowed"]:
        notify(f"🧩 indexed {idx['notes']} notes (orphans linked). Digestion paused — "
               f"budget mode {snap['mode']}; will resume next cycle.")
        return {"indexed": idx, "digested": 0, "deferred": True}

    pending = digest.find_undigested(limit)
    if not pending:                                      # nothing to digest → free index only, no run row
        return {"indexed": idx, "digested": 0, "remaining": 0}
    total_left = len(digest.find_undigested(9999))
    done, links, claims_n, people_n = 0, 0, 0, 0
    run_id = db.create_run_sync("digest", f"digest {len(pending)} of {total_left} notes", "triage")
    chars_in = 0
    for rel in pending:
        try:
            res = run_sync(digest.digest_note(rel))
            if res.get("type"):
                done += 1
                links += res.get("links", 0)
                claims_n += res.get("claims", 0)
                people_n += res.get("people", 0)
                chars_in += 3000                          # prompt bound per note (see digest.py)
        except Exception:  # noqa: BLE001  (one bad note never stops the batch)
            continue
    # approximate accounting so month-to-date spend stays honest (Haiku, tiny)
    t_in, t_out = chars_in // 4, done * 150
    db.finish_run_sync(run_id, status="done", tokens_in=t_in, tokens_out=t_out,
                       cost_usd=budget.cost_usd(settings.model_triage, t_in, t_out),
                       result_text=f"digested {done} notes, added {links} links")

    from ..memory import vaultsync
    reindex_vault_task.delay()
    vaultsync.commit_push("digest batch")

    # Record fresh vault health so the dashboard reflects the drop in orphans right after
    # organize (rebuild_indexes just linked them), not only on the nightly self-heal.
    inv = vault.audit_inventory()
    db.record_signal_sync("self", "vault.health",
                          {"files": inv["file_count"], "orphans": inv["orphan_count"],
                           "dead_links": inv["dead_link_count"]})

    remaining = len(digest.find_undigested(9999))
    # If a whole batch digested NOTHING (classify failing, model erroring) the notes never get
    # marked, so the old code re-queued the SAME notes every 90s forever — burning tokens and
    # spamming identical "digest" rows. Only continue while we're actually making progress.
    if done == 0:
        notify(f"🧩 indexed the vault, but couldn't digest this batch ({len(pending)} notes) — "
               f"stopping the loop. {remaining} still undigested; I'll retry on the nightly pass.")
        return {"indexed": idx, "digested": 0, "remaining": remaining, "stalled": True}
    notify(f"🧩 digested {done} notes (+{links} links, +{claims_n} claims, +{people_n} people). "
           f"{remaining} left to digest.")
    if chain and remaining:                               # keep going — churn through the backlog
        digest_batch_task.apply_async(kwargs={"limit": limit}, countdown=45)
    return {"indexed": idx, "digested": done, "remaining": remaining}


@app.task(name="kioku.worker.tasks.check_watches_task")
def check_watches_task():
    """Watch mode: re-check each thing Kioku is watching, compare to the last observed state, and
    ping Telegram on a MATERIAL change. Deterministic gate (only runs if there are watches);
    each check is one budget-gated, pausable research turn."""
    if switch.is_paused():
        return {"paused": True}
    from ..memory import watches
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


@app.task(name="kioku.worker.tasks.propose_ideas_task")
def propose_ideas_task():
    """Proactive 'Kioku proposes things': mid-week, review the owner's world and surface 1-3 concrete,
    high-leverage ideas / fixes / risks / opportunities — specific to THEM, not generic advice.
    Non-essential + pausable. This is the 'works while you sleep, and comes back with something'."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("propose_ideas", "proactive proposals", "work")
    sig = db.recent_signals_sync(30)
    prompt = (
        "Act as the owner's proactive chief of staff / technical co-founder. Review what you know about "
        "them — their active projects (e.g. Acme's push to first paying users, Kioku "
        "itself), their goals, constraints, and the recent signals below; read the vault as needed.\n"
        "Surface 1-3 CONCRETE, high-leverage proposals — an idea worth pursuing, a fix or "
        "improvement, a risk to get ahead of, or an opportunity. For each: a one-line WHY it matters "
        "to them now, and a specific suggested NEXT STEP. Be specific to their situation, not generic. "
        "Prefer things you could help execute (draft, research, schedule). Rank by leverage. If you "
        "have only one genuinely good idea, give one — no padding.\n\n"
        "RECENT SIGNALS (JSON):\n" + json.dumps(sig, default=str)[:3500])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="research",
                             retrieve_query="active projects goals priorities acme ideas risks"))
    if not out.get("skipped") and out.get("text"):
        path = vault.write(f"_reports/proposals-{date.today().isoformat()}.md", out["text"])
        out["result_path"] = path
        notify("💡 A few thoughts:\n" + out["text"][:2500])
        notify_file(path, "💡 Proposals — full note")
    elif out.get("limited"):
        notify("💡 Proposals skipped — usage limit.")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.opportunity_radar_task")
def opportunity_radar_task():
    """Proactive job scout: search the boards, score FIT against the owner's profile + CVs, and
    surface only genuine matches. Non-essential (budget-gated, pausable). Uses vault_read + web
    only (no connectors) and Sonnet for the scoring quality."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("opportunity_radar", "opportunity radar", "work")
    boards = settings.job_boards
    floor = settings.job_fit_floor
    prompt = (
        "Scout fresh job opportunities that genuinely fit the owner. You already know them (target roles, "
        "stack, location, salary floor, and their CVs are in the vault — read them if useful).\n"
        f"1. Search these boards with WebSearch, preferring postings from the last ~10 days: {boards}.\n"
        "2. Take the 3-4 most promising, fetch each posting, and score FIT 0-100 against their profile, "
        "stack, location (their city or remote) and salary floor.\n"
        f"3. Keep ONLY roles scoring >= {floor}. Skip anything already in the latest opportunities report.\n"
        "For each kept role: **Role @ Company** · location/remote · comp if listed · FIT NN · one line "
        "on why it fits + any red flag · the link. Lead with the single best. If nothing clears the bar, "
        "say so plainly — do not pad."
    )
    # intent='recall' → vault_read + web tools only (no Composio); difficulty 'work' → Sonnet.
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="recall",
                             retrieve_query="job search target roles salary preferences CV"))
    if not out.get("skipped") and out.get("text"):
        path = vault.write(f"_reports/opportunities-{date.today().isoformat()}.md", out["text"])
        out["result_path"] = path
        notify("🎯 Opportunity radar:\n" + out["text"][:2500])
        notify_file(path, "🎯 Opportunities — full report")
    elif out.get("limited"):
        notify("🎯 Opportunity radar skipped — " + (out.get("text") or "usage limit")[:300])
    _record_and_notify(run_id, out)
    return out.get("text")


def _render_self_review(summ: dict, usage: dict, unused: list, cache: dict | None = None) -> str:
    """Deterministic (free) markdown for the weekly self-review — the numbers speak first."""
    cache = cache or {}
    bm = "\n".join(f"- {m['model']}: {m['runs']} runs · ${m['cost']}" for m in summ["by_model"]) or "- none"
    bk = "\n".join(f"- {k['kind']}: {k['runs']} runs · ${k['cost']}"
                   + (f" · ⚠️ {k['errors']} err" if k["errors"] else "") for k in summ["by_kind"]) or "- none"
    top = "\n".join(f"- ${t['cost']} · {t['kind']} ({t['model']}) · {t['tokens_in']}→{t['tokens_out']} tok · {t['input']}"
                    for t in summ["top_cost"]) or "- none"
    use = "\n".join(f"- {n}: {c}×" for n, c in usage.items()) or "- (no skills used)"
    un = ", ".join(unused) or "none"
    return f"""# Self-review — last {summ['days']} days

**{summ['total_runs']} runs · ${summ['total_cost']} · {summ['errors']} errors** · avg {summ['avg_tokens_in']}→{summ['avg_tokens_out']} tok/run

## Cost by model
{bm}

## By kind
{bk}

## Most expensive runs
{top}

## Skill usage (30d)
{use}

**Unused skills (prune candidates):** {un}

## Prompt cache (7d)
- cache reads: **{cache.get('cache_read', 0)}** tok · writes: {cache.get('cache_write', 0)} · fresh input: {cache.get('fresh_input', 0)}
- **hit ratio: {int(cache.get('hit_ratio', 0) * 100)}%** over {cache.get('samples', 0)} runs {'✅' if cache.get('hit_ratio', 0) >= 0.3 else '— low; check for a cache invalidator' if cache.get('samples', 0) else '(no data yet)'}
"""


@app.task(name="kioku.worker.tasks.self_review_task")
def self_review_task():
    """Phase 3.4 — meta-cognition. Deterministic analysis of Kioku's own runs (cost, errors, model
    mix, skill usage) + a cheap Haiku read for concrete tuning suggestions. Non-essential + pausable."""
    if switch.is_paused():
        return {"paused": True}
    from ..agent import skills as SK
    summ = db.runs_summary_sync(7)
    usage = db.skill_usage_sync(30)
    cache = db.cache_stats_sync(7)
    unused = [s["name"] for s in SK.load() if s["name"] not in usage]
    report = _render_self_review(summ, usage, unused, cache)

    run_id = db.create_run_sync("self_review", "self review", "triage")
    prompt = ("These are Kioku's own operating stats for the last 7 days (JSON). In 4-6 lines give the owner "
              "concrete tuning suggestions ONLY where the data warrants it — model routing, turn caps, "
              "error hotspots, or skills to prune/trust. No filler; if it's healthy, say so plainly.\n\n"
              + json.dumps({"runs": summ, "skill_usage": usage, "unused_skills": unused}, default=str)[:3500])
    out = run_sync(run_agent(run_id, prompt, "triage", essential=False, intent="recall"))
    insights = out.get("text", "") if not out.get("skipped") else ""
    if insights:
        report += "\n## Kioku's read\n" + insights + "\n"
    rpath = vault.write(f"_reports/self-review-{date.today().isoformat()}.md", report)
    notify(f"🔍 Self-review (7d): {summ['total_runs']} runs · ${summ['total_cost']} · "
           f"{summ['errors']} error(s)." + (f"\n{insights[:1400]}" if insights else ""))
    notify_file(rpath, "🔍 Self-review — full report")
    _record_and_notify(run_id, out)

    # Phase 4.4 — close the loop: propose AT MOST ONE concrete, appendable playbook lesson from the
    # week's failures/cost, STAGED for approval (never applied silently). Only when the data warrants
    # it (errors present or enough runs to learn from). Vault-config only → can't touch safety limits.
    try:
        from ..memory import approvals
        if not out.get("skipped") and (summ.get("errors") or summ.get("total_runs", 0) >= 20):
            pr_id = db.create_run_sync("self_review_propose", "propose playbook lesson", "triage")
            pr = run_sync(run_agent(pr_id,
                ("From your own 7-day operating stats below, propose AT MOST ONE concrete operating "
                 "lesson to APPEND to your playbook that would prevent a repeat failure or cut cost — "
                 "one '- ' bullet, specific and actionable. If nothing is clearly worth it, reply with "
                 "exactly NONE. Output ONLY the bullet (starting '- ') or NONE.\n\n"
                 + json.dumps(summ, default=str)[:2500]),
                "triage", essential=False, intent="recall"))
            line = (pr.get("text") or "").strip()
            _record_and_notify(pr_id, pr)
            if line.startswith("- ") and line[:10].lower().find("none") == -1:
                approvals.stage_config_edit(
                    "system/playbook.md",
                    f"## Learned (self-review {date.today().isoformat()})\n{line}",
                    "operating lesson from this week's self-review", mode="append")
    except Exception:  # noqa: BLE001
        pass
    return {"summary": summ, "unused_skills": unused}


@app.task(name="kioku.worker.tasks.learn_task")
def learn_task():
    """Phase 3.2 — weekly self-education. Review the past week (calendar, notable mail, dev/ops
    signals) against what Kioku already knows, and PROPOSE a tightened system/profile.md — staged
    for approval, never a silent rewrite of the owner's curated profile. Non-essential + pausable."""
    if switch.is_paused():
        return {"paused": True}
    from ..memory import pending
    run_id = db.create_run_sync("learn", "weekly learning pass", "work")
    sig = db.recent_signals_sync(40)
    prompt = (
        "Weekly learning pass — sharpen your model of the owner, don't just recap.\n"
        "Read system/profile.md and reference/profile/ for what you already know. Then review the "
        "PAST WEEK: check their calendar (this week + next) and scan recent mail for anything that "
        "changes their world — read only, do NOT draft or send. Fold in the dev/ops signals below.\n"
        "Find GENUINELY NEW or CHANGED durable facts: project status, work moves, people, "
        "commitments, deadlines, preferences. Ignore ephemeral chatter and anything already known.\n"
        "Then:\n"
        "1. If their core profile is materially out of date, use vault_write to save an UPDATED "
        "system/profile.md — keep it TIGHT (it loads every session); it will stage for their approval.\n"
        "2. MODEL-OF-THE-OWNER PATTERNS: `system/patterns.json` holds how they OPERATE. Its `active_hours`/"
        "`best_nudge_hours`/`hour_histogram` are auto-derived — do NOT touch them. But if you've learned "
        "a durable PATTERN (energy rhythm, what they AVOID, decision style, over-commitment tendency), "
        "add/update the narrative fields `energy`/`avoids`(list)/`decision_style` by vault_write-ing the "
        "JSON back — PRESERVE every existing key. Only when you genuinely see it; don't invent.\n"
        "3. Summarise in 6-10 lines: what changed this week and what you've proposed. If the week "
        "was quiet, say so and propose nothing — don't manufacture updates.\n\n"
        "DEV/OPS SIGNALS (JSON):\n" + json.dumps(sig, default=str)[:3500])
    before = len(pending.list_plans())
    # intent='draft' → vault read/write + calendar + web + Composio (mail); 'work' → Sonnet.
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="draft"))
    if not out.get("skipped") and out.get("text"):
        new_plans = max(0, len(pending.list_plans()) - before)
        path = vault.write(f"_reports/learn-{date.today().isoformat()}.md", out["text"])
        out["result_path"] = path
        notify_file(path, "🧠 Weekly learning — full note")
        msg = "🧠 Weekly learning:\n" + out["text"][:1900]
        if new_plans:
            msg += f"\n\n📝 {new_plans} profile update(s) proposed — review in the dashboard or /approve."
        notify(msg)
    elif out.get("limited"):
        notify("🧠 Weekly learning skipped — " + (out.get("text") or "usage limit")[:300])
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.claim_sweep_task")
def claim_sweep_task(stale_days: int = 120):
    """Nightly: flag stale claims + (with embeddings on) find contradictions/near-duplicates.
    Writes a human-readable review report and pings you only if something needs resolving.
    Deterministic + free without embeddings; smarter once they're on."""
    if switch.is_paused():
        return {"paused": True}
    from ..memory import claims, vaultsync
    res = claims.sweep_sync(stale_days)
    path = vault.write(f"_reports/claim-review-{date.today().isoformat()}.md", res["report"])
    reindex_vault_task.delay([path])
    vaultsync.commit_push("claim sweep")
    db.record_signal_sync("self", "vault.claims",
                          {"total": res["total"], "stale_new": res["stale_new"],
                           "contradictions": res["contradictions"]})
    if res["contradictions"] or res["stale_new"]:
        notify(f"🧾 claim sweep: {res['total']} claims · {res['stale_new']} newly stale · "
               f"{res['contradictions']} contradiction(s) → {path}")
    return res


@app.task(name="kioku.worker.tasks.self_heal_task")
def self_heal_task():
    """Scheduled 'Kioku fixes its own brain': re-audit, then rebuild indexes + digest a batch.
    This is the connect/repair loop — orphans get linked, new notes get understood, over time."""
    if switch.is_paused():
        return {"paused": True}
    inv = vault.audit_inventory()
    digest_batch_task.delay(limit=12, chain=True)         # churn through the whole backlog nightly
    db.record_signal_sync("self", "vault.health",
                          {"files": inv["file_count"], "orphans": inv["orphan_count"],
                           "dead_links": inv["dead_link_count"]})
    # Phase 4.2 — refresh the model-of-you rhythm from the runs table (deterministic, free).
    try:
        from ..memory import patterns
        patterns.refresh_sync()
    except Exception:  # noqa: BLE001
        pass
    return {"orphans": inv["orphan_count"], "dead_links": inv["dead_link_count"]}
