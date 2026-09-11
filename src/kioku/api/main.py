from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..memory import db, budget, pending, connectors, people, switch
from ..frontdoor import telegram_bot as tg
from ..worker.tasks import (run_agent_task, vault_audit_task, reindex_vault_task,
                             apply_write_task, handle_input_task, ingest_task, bulk_ingest_task,
                             digest_batch_task)
from .events import run_event_stream

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the Telegram bot inside the API process — one container, not two.
    NOTE: run the API with a SINGLE uvicorn worker so polling isn't duplicated."""
    application = None
    if settings.telegram_bot_token:
        application = tg.build_application()
        await application.initialize()
        await application.start()
        # drop_pending_updates clears any backlog held by a previous container so a redeploy
        # overlap (two getUpdates pollers → 409 Conflict) resolves to a single clean poller.
        # REQUIRES the api service to run ONE replica and ONE uvicorn worker (see railway.api.toml).
        await application.updater.start_polling(drop_pending_updates=True)
    yield
    if application:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


app = FastAPI(title="Kioku", lifespan=lifespan)

# Paths that never require the token: the healthcheck (Railway) and the dashboard shell +
# its assets (inert without a token — every data call below is still gated).
_OPEN_PATHS = {"/health", "/", "/favicon.ico"}


def _token_ok(request: Request) -> bool:
    tok = settings.dashboard_token
    if not tok:
        return True                                  # auth disabled until a token is set
    ah = request.headers.get("authorization", "")
    given = ah[7:].strip() if ah[:7].lower() == "bearer " else ""
    given = given or request.query_params.get("token", "") or request.cookies.get("kioku_token", "")
    return given == tok


@app.middleware("http")
async def _auth(request: Request, call_next):
    path = request.url.path
    if path in _OPEN_PATHS or path.startswith("/static"):
        return await call_next(request)
    if not _token_ok(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


class TaskIn(BaseModel):
    kind: str = "ask"          # ask | vault_audit
    input: str = ""
    difficulty: str = "triage"  # triage | work | orchestrator | hard
    essential: bool = True      # user-initiated = essential; pollers pass False
    source: str = "telegram"    # which channel they're talking through: telegram | web | cli


@app.get("/health")
async def health():
    return {"ok": True}


_DASHBOARD = Path(__file__).parent / "static" / "index.html"


@app.get("/")
async def dashboard():
    """The command center (single-page). Data calls it makes are token-gated by the middleware."""
    if _DASHBOARD.exists():
        return FileResponse(_DASHBOARD)
    return JSONResponse({"ok": True, "note": "dashboard not bundled"}, status_code=200)


@app.get("/budget")
async def get_budget():
    return await budget.check("triage", essential=True)


@app.get("/runs")
async def runs(limit: int = 20):
    return await db.recent_runs(min(limit, 100))


@app.get("/people")
async def list_people(limit: int = 100):
    """Personal CRM — everyone Kioku has learned about, most-recent first."""
    return await people.list_people(min(limit, 500))


def _safe_approvals() -> list:
    """Pending outbound approvals for the dashboard — never let a Redis hiccup break /status."""
    try:
        from ..memory import approvals
        return approvals.list_pending()
    except Exception:  # noqa: BLE001
        return []


@app.get("/status")
async def status():
    """Everything the dashboard shows at a glance — assembled from Postgres, no vault needed."""
    b = await budget.check("triage", essential=True)
    health_sig = await db.latest_signal("vault.health")
    claims_sig = await db.latest_signal("vault.claims")
    sched_sig = await db.latest_signal("system.schedules")
    tg_sig = await db.latest_signal("telegram.deliverable")
    last_seen = await db.source_last_seen()
    raw = connectors.load()
    composio_on = any(c.get("name") == "composio" and c.get("enabled") for c in raw)
    conns = []
    for c in raw:
        enabled = bool(c.get("enabled"))
        if c.get("via") == "composio" and composio_on:
            state = "composio"            # served by the Composio router → available
        elif enabled:
            state = "connected"
        else:
            state = "off"
        conns.append({"name": c["name"], "kind": c.get("kind"), "enabled": enabled,
                      "state": state, "last_seen": last_seen.get(c["name"])})
    return {
        "budget": b,
        "vault": (health_sig or {}).get("value"),
        "vault_observed_at": (health_sig or {}).get("observed_at"),
        "claims": (claims_sig or {}).get("value"),
        "connectors": conns,
        "spend_series": await db.spend_series(48),
        "spend_by_model": await db.spend_by_model(),
        "pending_writes": len(pending.list_plans()),
        "approvals": _safe_approvals(),
        "people": len(await people.list_people(500)),
        "paused": switch.is_paused(),
        "schedules": ((sched_sig or {}).get("value") or {}).get("items", []),
        "telegram_deliverable": ((tg_sig or {}).get("value") or {}).get("ok"),
    }


@app.post("/pause")
async def pause():
    """Soft off-switch: Kioku stays up but stops running/spending until /resume."""
    switch.set_paused(True)
    return {"paused": True}


@app.post("/resume")
async def resume():
    switch.set_paused(False)
    return {"paused": False}


@app.post("/tasks")
async def submit_task(t: TaskIn):
    model = t.difficulty if t.kind == "ask" else "triage"
    run_id = await db.create_run(t.kind, t.input, model)
    if t.kind == "vault_audit":
        vault_audit_task.delay(run_id)
    elif t.kind == "input":                    # natural language -> intent router
        handle_input_task.delay(run_id, t.input, t.source)
    else:
        run_agent_task.delay(run_id, t.input, t.difficulty, t.essential)
    return {"run_id": run_id, "stream": f"/tasks/{run_id}/stream"}


@app.post("/inbox")
async def inbox(t: TaskIn):
    """Universal capture/ask: routes by intent. Any interface can POST here."""
    run_id = await db.create_run("input", t.input, "triage")
    handle_input_task.delay(run_id, t.input)
    return {"run_id": run_id, "stream": f"/tasks/{run_id}/stream"}


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    """Upload a file/photo to learn from it. Any interface can POST multipart here."""
    import base64
    data = await file.read()
    if len(data) > 12_000_000:
        raise HTTPException(413, "file too large for inline ingest (>12MB) — use object storage")
    run_id = await db.create_run("ingest", file.filename, "triage")
    ingest_task.delay(run_id, base64.b64encode(data).decode(), file.filename, "upload")
    return {"run_id": run_id, "file": file.filename}


@app.get("/tasks/{run_id}/stream")
async def stream(run_id: str):
    return EventSourceResponse(run_event_stream(run_id))


@app.post("/bulk-ingest")
async def bulk_ingest(subdir: str = "_import"):
    """Ingest a folder you dropped into the vault (vault/_import/ by default)."""
    bulk_ingest_task.delay(subdir)
    return {"status": "bulk ingest enqueued", "subdir": subdir}


@app.post("/reindex")
async def reindex():
    reindex_vault_task.delay()
    return {"status": "reindex enqueued"}


@app.post("/organize")
async def organize():
    """Rebuild the vault map (free) + digest/connect notes in cheap batches."""
    digest_batch_task.delay()
    return {"status": "organize enqueued"}


@app.get("/skills")
async def list_skills():
    from ..agent import skills
    return [{"name": s["name"], "when": s["when"]} for s in skills.load()]


@app.get("/approvals")
async def list_approvals():
    """Outbound actions Kioku has staged and is waiting on you to approve (send mail, external
    delete, post, transfer). The vault is free and never appears here."""
    from ..memory import approvals
    return approvals.list_pending()


@app.post("/approvals/{aid}/approve")
async def approve_action(aid: str):
    from ..memory import approvals
    from ..worker.tasks import execute_approved_task
    rec = approvals.get(aid)
    if not rec:
        raise HTTPException(404, "no such approval (expired or already handled)")
    execute_approved_task.delay(rec["id"])
    return {"status": "approving", "id": rec["id"], "desc": rec.get("desc")}


@app.post("/approvals/{aid}/reject")
async def reject_action(aid: str):
    from ..memory import approvals
    if not approvals.reject(aid):
        raise HTTPException(404, "no such approval")
    return {"status": "rejected", "id": aid}


@app.get("/handoffs")
async def list_handoffs():
    """Heavy-coding hand-offs Kioku dispatched to your local Claude Code runner (Phase 3.5)."""
    from ..memory import handoff
    return handoff.list_all()


@app.post("/handoffs/claim")
async def claim_handoff(runner: str = "local"):
    """The LOCAL runner calls this (with the dashboard token) to claim the next pending hand-off."""
    from ..memory import handoff
    return handoff.claim_next(runner) or {}


@app.post("/handoffs/{hid}/result")
async def handoff_result(hid: str, body: dict):
    """The LOCAL runner posts a finished hand-off here: {status: done|error, result: <text>}."""
    from ..memory import handoff
    from ..worker.tasks import handoff_result_task
    rec = handoff.complete(hid, body.get("status", "done"), body.get("result", ""))
    if not rec:
        raise HTTPException(404, "no such hand-off")
    handoff_result_task.delay(hid)     # file to the vault + notify on the worker
    return {"ok": True, "id": hid, "status": rec["status"]}


@app.get("/writes")
async def pending_writes():
    return pending.list_plans()


@app.post("/writes/{sha}/apply")
async def apply_write(sha: str):
    if not pending.plan_exists(sha):
        raise HTTPException(404, "no such plan (expired or already applied)")
    apply_write_task.delay(sha)               # worker owns the vault; apply there
    return {"status": "apply enqueued", "sha": sha}
