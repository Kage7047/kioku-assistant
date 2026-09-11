"""Heavy-coding hand-off queue (Phase 3.5).

Kioku runs on Railway against the $20 Agent-SDK credit and can't see your LOCAL files. Heavy
interactive coding (big multi-file builds/refactors, work on a local repo) is the wrong thing to
spend that budget on — and often impossible from the cloud worker. This queue lets Kioku DISPATCH
such a task to a Claude Code session running on your own machine: a SEPARATE interactive Pro pool,
full quality, with local-filesystem access, and only when you're actually at your PC.

Flow: Kioku calls `handoff_code` → a record lands here (Redis) → the local runner
(`runner/kioku_runner.py`, polling your API) claims it, runs `claude` in the target repo, and POSTs
the result back → Kioku files it to `_reports/` and pings you. Nothing runs on your machine unless
the runner is on. Redis-backed so the API, the worker, and the external runner all share it.
"""
import hashlib
import json
import time

import redis

from ..config import settings

_r = redis.Redis.from_url(settings.redis_url)
HANDOFF_TTL = 7 * 86400            # keep a hand-off record for a week
PENDING_KEY = "handoff:pending"    # FIFO list of ids awaiting a runner


def _get(hid: str) -> dict | None:
    raw = _r.get(f"handoff:{hid}")
    return json.loads(raw) if raw else None


def _save(rec: dict) -> None:
    _r.setex(f"handoff:{rec['id']}", HANDOFF_TTL, json.dumps(rec))


def create(task: str, repo: str = "", context: str = "", kind: str = "code") -> dict:
    """Stage a hand-off. `repo` is a name the runner maps to a local path. `kind` selects the runner's
    handler: 'code' (free-form Claude Code) or a registered dev task (run_tests/lint/review_diff/
    scaffold/index_repo — Phase 4.5B). The runner runs ONLY handlers it recognises; anything else it
    refuses, so an unknown/destructive kind never executes."""
    hid = hashlib.sha256(f"{kind}{task}{repo}{time.time()}".encode()).hexdigest()[:12]
    rec = {"id": hid, "kind": kind, "task": task, "repo": repo, "context": context,
           "status": "pending", "result": "", "runner": None,
           "created_at": time.time(), "finished_at": None}
    _save(rec)
    _r.rpush(PENDING_KEY, hid)
    return rec


def claim_next(runner: str = "local") -> dict | None:
    """Runner claims the next pending task (atomic pop) and marks it running. Returns it or None."""
    hid = _r.lpop(PENDING_KEY)
    if not hid:
        return None
    hid = hid.decode() if isinstance(hid, bytes) else hid
    rec = _get(hid)
    if not rec:
        return None
    rec.update(status="running", runner=runner, started_at=time.time())
    _save(rec)
    return rec


def complete(hid: str, status: str, result: str) -> dict | None:
    """Runner reports a finished hand-off (status 'done' or 'error')."""
    rec = _get(hid)
    if not rec:
        return None
    rec.update(status=status if status in ("done", "error") else "done",
               result=result or "", finished_at=time.time())
    _save(rec)
    return rec


def get(hid: str) -> dict | None:
    return _get(hid)


def list_all(limit: int = 50) -> list[dict]:
    out = []
    for key in _r.scan_iter("handoff:*"):
        k = key.decode() if isinstance(key, bytes) else key
        if k == PENDING_KEY:
            continue
        raw = _r.get(k)
        if raw:
            try:
                out.append(json.loads(raw))
            except Exception:  # noqa: BLE001
                pass
    return sorted(out, key=lambda r: r.get("created_at", 0), reverse=True)[:limit]
