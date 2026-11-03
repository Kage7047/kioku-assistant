"""Executing what the owner approved: staged outbound actions and config edits, and filing hand-off results."""
import json


from ..celery_app import app
from ..._compat import run_sync
from ...agent.orchestrator import run_agent
from ...memory import db, vault, switch
from ...frontdoor.notify import notify, notify_file

from ._common import _record_and_notify
from .vault_ops import reindex_vault_task


@app.task(name="kioku.worker.tasks.execute_approved_task")
def execute_approved_task(approval_id: str):
    """Execute an OUTBOUND action the user just approved (from the command center or /approve <id>).
    Runs the exact staged tool call once via a scoped run with a one-time grant (no re-gating)."""
    if switch.is_paused():
        notify("⏸ Paused — approve again after /resume.")
        return {"paused": True}
    from ...memory import approvals
    rec = approvals.pop(approval_id)
    if not rec:
        notify(f"⚠️ Approval {approval_id} not found (expired or already handled).")
        return {"error": "not found"}

    # Phase 4.4 — a self-improvement config edit: apply it deterministically (no model call), then push.
    if rec.get("kind") == "config-edit":
        from ...memory import vaultsync
        path, content, mode = rec["path"], rec.get("content", ""), rec.get("mode", "append")
        try:
            if mode == "append":
                existing = ""
                try:
                    existing = vault.read(path)
                except Exception:  # noqa: BLE001
                    pass
                body = (existing.rstrip() + "\n\n" + content + "\n") if existing.strip() else content + "\n"
                vault.write(path, body, approved=True)        # the owner just approved it
            else:
                vault.write(path, content if content.endswith("\n") else content + "\n", approved=True)
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
    # approved_call scopes THIS run to exactly the approved tool + arguments, once; nothing else runs.
    out = run_sync(run_agent(run_id, prompt, "work", essential=True,
                             approved_call={"tool": rec["tool"], "input": rec.get("input") or {}}))
    if out.get("text"):
        notify(f"✅ Approved action done:\n{out['text'][:1500]}")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.handoff_result_task")
def handoff_result_task(hid: str):
    """A local Claude Code hand-off finished (Phase 3.5): file its result to the vault + notify."""
    from ...memory import handoff, vaultsync
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
