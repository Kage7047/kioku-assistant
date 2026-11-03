"""The front door: a raw agent run, and natural-language input routed by intent."""
from ..celery_app import app
from ..._compat import run_sync
from ...agent.orchestrator import run_agent
from ...memory import db, budget, switch
from ...observability.langfuse import trace_run
from ...frontdoor.notify import notify

from ._common import _paused_finish, _record_and_notify
from .agency import learn_task, opportunity_radar_task, propose_ideas_task, propose_skill_task, self_review_task
from .rhythms import weekly_review_task
from .vault_ops import bulk_ingest_task, digest_batch_task, reindex_vault_task, vault_audit_task


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
        from ..interrupt import mute, unmute
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
    from ...agent import router, capture, journal, skills
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
