"""Two vault-safety primitives (borrowed from claude-obsidian / DeepOrbit):

1. PLAN -> APPLY WITH HASH: a sensitive write (outside _reports/ inbox/) does not
   execute. It emits a plan with a sha256; nothing changes until someone approves
   that exact hash (/approve <sha> in Telegram, or POST /writes/{sha}/apply).

2. DRAFT -> APPLY: sub-agents never touch the vault. They stage drafts; the ONE
   orchestrator applies them as a single recoverable transaction. Prevents parallel
   workers racing/corrupting the vault in Phase 2 fan-out.

Plans/drafts live in Redis so API and worker processes share them.
"""
import hashlib
import json
import time

import redis

from . import vault as V
from ..config import settings

_r = redis.Redis.from_url(settings.redis_url)
PLAN_TTL = 3600  # seconds a pending plan stays approvable


def _sha(path: str, content: str) -> str:
    return hashlib.sha256(json.dumps({"path": path, "content": content},
                                     sort_keys=True).encode()).hexdigest()


# ---- preview-then-apply-with-hash ----
def plan_write(path: str, content: str) -> dict:
    sha = _sha(path, content)
    _r.setex(f"plan:{sha}", PLAN_TTL,
             json.dumps({"path": path, "content": content, "ts": time.time()}))
    return {"sha256": sha, "path": path, "bytes": len(content.encode()),
            "preview": content[:280], "expires_in": PLAN_TTL}


def plan_exists(sha: str) -> bool:
    return bool(_r.exists(f"plan:{sha}"))


def apply_plan(sha: str) -> str:
    raw = _r.get(f"plan:{sha}")
    if not raw:
        raise KeyError("no such plan (expired or already applied)")
    plan = json.loads(raw)
    path = V.write(plan["path"], plan["content"], approved=True)  # plan IS the approval
    _r.delete(f"plan:{sha}")
    return path


def list_plans() -> list[dict]:
    out = []
    for key in _r.scan_iter("plan:*"):
        raw = _r.get(key)
        if raw:
            p = json.loads(raw)
            out.append({"sha256": key.decode().split(":", 1)[1], "path": p["path"]})
    return out


# ---- draft -> apply (fan-out safety) ----
def stage_draft(run_id: str, path: str, content: str) -> None:
    _r.rpush(f"drafts:{run_id}", json.dumps({"path": path, "content": content}))


def apply_drafts(run_id: str) -> list[str]:
    raw = _r.lrange(f"drafts:{run_id}", 0, -1)
    items = [json.loads(x) for x in raw]
    applied = V.apply_writes(items)   # backup + write + rollback-on-failure
    _r.delete(f"drafts:{run_id}")
    return applied
