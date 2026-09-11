"""Outbound approval queue.

The vault is Kioku's own memory and is FREE — it never needs approval. But genuinely OUTBOUND or
world-irreversible actions (sending an email/message to a real person, deleting something OUTSIDE
the vault, posting publicly, spending) are GATED: the orchestrator's permission callback stages
them here instead of executing, notifies the user, and shows them in the command center. On approval
the exact tool call is executed via a scoped, one-time-granted run (see worker.tasks.execute_approved_task).

This replaces the old `pending.py` plan/hash queue, which gated VAULT writes — those are free now, so
that queue sat permanently empty ("nothing to approve, no sha"). This one holds the things that
actually should stop for a human: outbound side effects.

Lives in Redis so the API and worker processes share it.
"""
import hashlib
import json
import time

import redis

from ..config import settings

_r = redis.Redis.from_url(settings.redis_url)
APPROVAL_TTL = 86400  # a staged action stays approvable for 24h

# Tools that are ALWAYS free — Kioku's own memory, scheduling, watches, the local calendar stubs,
# and read-only web/search/delegation. These live in allowed_tools and normally never even reach
# the gate, but we hard-exclude them here too so a loose outbound pattern can never gate them.
_NEVER_GATE_PREFIX = ("mcp__vault__", "mcp__scheduler__", "mcp__watch__", "mcp__calendar__")
_NEVER_GATE_EXACT = {"websearch", "webfetch", "agent", "todowrite"}

# Name fragments that mean an OUTBOUND / irreversible-in-the-world action. Matched case-insensitively
# against the tool name. Deliberately tight: creating a DRAFT (GMAIL_CREATE_EMAIL_DRAFT) or a calendar
# event (GOOGLECALENDAR_CREATE_EVENT) contains none of these → stays free (calendar create/update is
# auto per the playbook); SEND / DELETE / TRASH do → they gate.
_OUTBOUND_FRAGMENTS = ("send", "delete", "trash", "remove", "post", "publish", "transfer", "revoke",
                       "browser")   # browser_task (Phase 4.7 computer-use) is gated hardest


def is_outbound(tool: str, _input: dict | None = None) -> bool:
    low = (tool or "").lower()
    if low in _NEVER_GATE_EXACT:
        return False
    if any(low.startswith(p) for p in _NEVER_GATE_PREFIX):
        return False
    return any(frag in low for frag in _OUTBOUND_FRAGMENTS)


def _describe(tool: str, inp: dict | None) -> str:
    inp = inp or {}
    short = tool.split("__")[-1] if tool else tool
    hints = []
    for k in ("to", "recipient", "recipient_email", "email", "subject", "title", "summary",
              "message", "body", "text", "query", "file_id", "event_id", "name"):
        v = inp.get(k)
        if v:
            hints.append(f"{k}={str(v)[:90]}")
        if len(hints) >= 3:
            break
    return short + (": " + "; ".join(hints) if hints else "")


def stage(tool: str, inp: dict | None, run_id: str | None = None) -> dict:
    """Stage an outbound tool call for approval, notify the user, and return the record."""
    ts = time.time()
    blob = json.dumps({"tool": tool, "input": inp or {}}, sort_keys=True, default=str)
    aid = hashlib.sha256((blob + str(ts)).encode()).hexdigest()[:12]
    rec = {"id": aid, "tool": tool, "input": inp or {}, "run_id": run_id, "ts": ts,
           "desc": _describe(tool, inp)}
    _r.setex(f"approval:{aid}", APPROVAL_TTL, json.dumps(rec, default=str))
    try:
        from ..frontdoor.notify import notify
        notify("🔐 Approval needed — I want to run an OUTBOUND action:\n"
               f"“{rec['desc']}”\n"
               f"It has NOT run. Approve it in the command center, or reply /approve {aid}.")
    except Exception:  # noqa: BLE001
        pass
    return rec


def stage_config_edit(path: str, content: str, rationale: str, mode: str = "append",
                      run_id: str | None = None) -> dict:
    """Stage a proposed edit to Kioku's OWN config for approval (Phase 4.4 self-improvement) — a
    playbook lesson, a new skill, a tightened profile. mode: 'append' (add to an existing file) or
    'create' (a new file). Applied on approval via execute_approved_task; git-versioned → revertible.
    Only vault config is reachable this way; code-level safety limits live in the code repo, which
    Kioku cannot write — so it can propose capabilities, never its own safety limits."""
    ts = time.time()
    aid = hashlib.sha256((path + content + str(ts)).encode()).hexdigest()[:12]
    rec = {"id": aid, "kind": "config-edit", "path": path, "content": content, "mode": mode,
           "rationale": rationale, "run_id": run_id, "ts": ts,
           "desc": f"self-edit ({mode}) → {path}: {rationale[:100]}"}
    _r.setex(f"approval:{aid}", APPROVAL_TTL, json.dumps(rec, default=str))
    try:
        from ..frontdoor.notify import notify
        notify(f"🛠 Self-improvement proposed:\n{rec['desc']}\n"
               f"Approve with /approve {aid} (or /reject {aid}); revertible via git.")
    except Exception:  # noqa: BLE001
        pass
    return rec


def _resolve_key(aid: str) -> str | None:
    """Accept a full 12-char id or a prefix (so a Telegram '/approve <first 8>' works)."""
    if _r.exists(f"approval:{aid}"):
        return f"approval:{aid}"
    for key in _r.scan_iter("approval:*"):
        k = key.decode() if isinstance(key, bytes) else key
        if k.split(":", 1)[1].startswith(aid):
            return k
    return None


def get(aid: str) -> dict | None:
    key = _resolve_key(aid)
    if not key:
        return None
    raw = _r.get(key)
    return json.loads(raw) if raw else None


def pop(aid: str) -> dict | None:
    """Fetch and remove (used when actually executing an approved action)."""
    key = _resolve_key(aid)
    if not key:
        return None
    raw = _r.get(key)
    _r.delete(key)
    return json.loads(raw) if raw else None


def reject(aid: str) -> bool:
    key = _resolve_key(aid)
    if not key:
        return False
    _r.delete(key)
    return True


def list_pending() -> list[dict]:
    out = []
    for key in _r.scan_iter("approval:*"):
        raw = _r.get(key)
        if raw:
            try:
                out.append(json.loads(raw))
            except Exception:  # noqa: BLE001
                pass
    return sorted(out, key=lambda r: r.get("ts", 0), reverse=True)
