"""Housekeeping: reap stale runs, self metrics, nightly self-heal."""
from ..celery_app import app
from ...memory import db, vault, budget, switch

from .vault_ops import digest_batch_task


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
                           "dead_links": inv["dead_link_count"], "by_dir": inv["by_dir"]})
    # Phase 4.2 — refresh the model-of-you rhythm from the runs table (deterministic, free).
    try:
        from ...memory import patterns
        patterns.refresh_sync()
    except Exception:  # noqa: BLE001
        pass
    return {"orphans": inv["orphan_count"], "dead_links": inv["dead_link_count"]}
