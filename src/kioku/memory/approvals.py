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

# Kioku's OWN tools — memory, scheduling, watches, the local calendar stubs — plus read-only
# web/search/delegation. Always free.
_NEVER_GATE_PREFIX = ("mcp__vault__", "mcp__scheduler__", "mcp__watch__", "mcp__calendar__")
_NEVER_GATE_EXACT = {"websearch", "webfetch", "agent", "todowrite"}

# Hand-off tools reach the owner's own machine. Anything that starts a Claude Code session there
# (handoff_code, and the scaffold / review_diff dev tasks, which take free-form text and run with
# edit permissions) or drives a real browser is gated. Only the fixed commands — run_tests, lint and
# index_repo (git ls-files) — run without approval, and the runner refuses any other kind.
_HANDOFF_GATED = {"mcp__handoff__handoff_code", "mcp__handoff__browser_task"}
_HANDOFF_FREE_KINDS = {"run_tests", "lint", "index_repo"}

# External connector tools (Composio, remote MCP) are DEFAULT-DENY. A name-based deny-list misses
# whatever it didn't think of — GMAIL_REPLY_TO_THREAD, GMAIL_FORWARD_MESSAGE, SLACK_INVITE_USER and
# GITHUB_CREATE_ISSUE_COMMENT contain no "send"/"post"/"delete" yet all act on the world. So an
# external tool runs freely only if its action is clearly read-only or creates a draft; anything
# unrecognised is staged for approval. Write verbs win over read verbs (SEND_DRAFT is gated).
_WRITE_VERBS = {"send", "reply", "forward", "delete", "trash", "remove", "post", "publish", "share",
                "transfer", "pay", "revoke", "invite", "comment", "tweet", "submit", "merge",
                "archive", "move", "browser", "upload", "push", "approve", "accept", "decline"}
_READ_VERBS = {"get", "list", "search", "fetch", "find", "read", "query", "lookup", "describe",
               "retrieve", "download", "count", "check", "view", "export", "batch_get"}
_SAFE_CREATES = {"draft"}            # drafting is the whole point: the human sends it later
# A calendar event is free to create/update unless it invites someone (that emails real people).
_CALENDAR_EVENT = ("calendar_create_event", "calendar_update_event", "calendar_quick_add")
_INVITEE_KEYS = ("attendees", "guests", "invitees", "attendee_emails", "send_updates", "sendUpdates")


def _verbs(tool: str) -> set[str]:
    action = tool.split("__")[-1].lower()
    return set(action.replace("-", "_").split("_"))


def is_outbound(tool: str, inp: dict | None = None) -> bool:
    """True if this tool call must stop for the owner's approval."""
    low = (tool or "").lower()
    if low in _NEVER_GATE_EXACT or any(low.startswith(p) for p in _NEVER_GATE_PREFIX):
        return False
    if low.startswith("mcp__handoff__"):
        if low in _HANDOFF_GATED:
            return True
        if low == "mcp__handoff__dev_task":
            return (inp or {}).get("kind") not in _HANDOFF_FREE_KINDS      # unknown kinds gate too
        return False
    if not low.startswith("mcp__"):
        return False                 # remaining built-ins are either read-only or disallowed outright
    verbs = _verbs(low)
    if verbs & _WRITE_VERBS:
        return True
    if any(low.endswith(c) for c in _CALENDAR_EVENT):
        return any((inp or {}).get(k) for k in _INVITEE_KEYS)
    # unknown external action → default-deny
    return not verbs & (_READ_VERBS | _SAFE_CREATES)


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
    _r.set(f"approval:{aid}", json.dumps(rec, default=str), ex=APPROVAL_TTL)
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
    _r.set(f"approval:{aid}", json.dumps(rec, default=str), ex=APPROVAL_TTL)
    try:
        from ..frontdoor.notify import notify
        notify(f"🛠 Self-improvement proposed:\n{rec['desc']}\n"
               f"Approve with /approve {aid} (or /reject {aid}); revertible via git.")
    except Exception:  # noqa: BLE001
        pass
    return rec


MIN_PREFIX = 6


def _resolve_key(aid: str) -> str | None:
    """Accept a full 12-char id or a UNIQUE prefix of at least MIN_PREFIX chars (so a Telegram
    '/approve <first 8>' works). Too short or ambiguous → None, never "the first match"."""
    aid = (aid or "").strip()
    if len(aid) < MIN_PREFIX:
        return None
    if _r.exists(f"approval:{aid}"):
        return f"approval:{aid}"
    matches = []
    for key in _r.scan_iter("approval:*"):
        k = key.decode() if isinstance(key, bytes) else key
        if k.split(":", 1)[1].startswith(aid):
            matches.append(k)
    return matches[0] if len(matches) == 1 else None


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
