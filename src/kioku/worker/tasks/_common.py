"""Shared helpers for every task module: the pause check and run bookkeeping (cost, budget-mode alerts, vault commit)."""
import redis

from ...config import settings
from ...memory import db, budget, switch
from ...frontdoor.notify import notify



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
    # Prefer the SDK's own figure; otherwise price the tokens, cache reads/writes included.
    cost = out.get("cost_usd")
    if cost is None:
        cost = budget.cost_usd(out["model"], out["tokens_in"], out["tokens_out"],
                               out.get("cache_read", 0), out.get("cache_write", 0))
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
    from ...memory import vaultsync
    from .vault_ops import reindex_vault_task       # lazy: vault_ops imports this module
    if out.get("result_path"):
        reindex_vault_task.delay([out["result_path"]])
    vaultsync.commit_push(f"run {str(run_id)[:8]}")
