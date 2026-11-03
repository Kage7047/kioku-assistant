"""What a run may use: the tool surface per intent, banned built-ins, when external
connectors are mounted, per-difficulty turn caps."""
import re


# --- intent-based tool narrowing: fewer tool defs = fewer input tokens = cheaper runs.
# The big win is NOT mounting the external connector MCPs (Gmail/Drive/Notion — many tool
# defs + a Composio session) unless the intent actually needs them.
_VAULT_READ = ["mcp__vault__vault_list", "mcp__vault__vault_read", "mcp__vault__vault_search"]
_VAULT_WRITE = ["mcp__vault__vault_write", "mcp__vault__vault_delete", "mcp__vault__vault_move"]
_CAL = ["mcp__calendar__calendar_find_slots", "mcp__calendar__calendar_book"]
_SCHED = ["mcp__scheduler__schedule_add", "mcp__scheduler__schedule_once",
          "mcp__scheduler__schedule_list", "mcp__scheduler__schedule_remove",
          "mcp__watch__watch_add", "mcp__watch__watch_list", "mcp__watch__watch_remove"]
_WEB = ["WebSearch", "WebFetch"]
# Phase 3.5 hand-off: dispatch heavy/local coding to Claude Code on the user's PC (off-budget).
# Only the read-only status tool is pre-approved. handoff_code / dev_task / browser_task act on the
# owner's machine, and anything listed in allowed_tools is auto-approved by the SDK WITHOUT calling
# can_use_tool — so they must stay out of this list and reach the outbound gate on every call.
_HANDOFF = ["mcp__handoff__handoff_status"]
_ALL_BUILTIN = _VAULT_READ + _VAULT_WRITE + _CAL + _SCHED + _WEB + _HANDOFF
# The vault is Kioku's OWN memory — full read+write+delete+move on EVERY intent (the user's standing
# rule: "don't ask permission to write to your own vault"). Research/recall used to omit vault_write,
# which is exactly why filing a research report kept hitting a permission wall — the write tool wasn't
# in the auto-approve list, so the SDK fell through to a prompt that (running headless) resolved to a
# block. Web is on every intent (cheap + often needed); calendar/scheduler go to actionable intents.
# Composio (external) mounts for the intents in _INTENT_NEEDS_EXTERNAL OR when the request clearly
# touches a connector (keyword hint) — so "what's on my calendar?" always works.
# NOTE: with permission_mode="bypassPermissions" (below) allowed_tools no longer gates anything at
# runtime; this map is kept coherent for readability + as defence-in-depth if the mode ever changes.
_INTENT_TOOLS = {
    "recall":   _VAULT_READ + _VAULT_WRITE + _WEB,
    "research": _VAULT_READ + _VAULT_WRITE + _WEB,
    "capture":  _VAULT_READ + _VAULT_WRITE + _WEB,
    "draft":    _VAULT_READ + _VAULT_WRITE + _CAL + _SCHED + _WEB,
    "plan":     _VAULT_READ + _VAULT_WRITE + _CAL + _SCHED + _WEB + _HANDOFF,
    "automate": _VAULT_READ + _VAULT_WRITE + _CAL + _SCHED + _WEB + _HANDOFF,
    "code":     _VAULT_READ + _VAULT_WRITE + _SCHED + _WEB + _HANDOFF,
    "command":  _VAULT_READ + _VAULT_WRITE + _WEB,
}

# Built-in Claude Code tools Kioku must NEVER use directly. Its filesystem IS the vault, reached only
# through the guarded `mcp__vault__*` tools (which protect system/ + .git); direct Bash/Read/Write to
# the worker container would sidestep those guards and could read secrets/env. Bare names remove the
# tool from the model's context entirely (also trims tool-def tokens). WebSearch/WebFetch/Agent stay.
_DISALLOWED_BUILTINS = ["Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit",
                        "NotebookEdit", "Glob", "Grep"]
_INTENT_NEEDS_EXTERNAL = {"draft", "plan", "automate", "research"}
# Any request touching these routes Composio (Gmail/Calendar/Drive/…) even for a plain question.
_EXTERNAL_HINTS = re.compile(
    r"\b(calendar|schedule|meeting|event|agenda|appointment|email|e-?mail|mail|gmail|inbox|reply|"
    r"drive|google\s+doc|docs?|sheet|spreadsheet|linkedin|recruiter|message\s+(from|to))\b", re.I)


# Per-difficulty turn caps — GENEROUS. The 6-turn cap was killing real work mid-run (the #1 failure
# in testing). A simple recall still finishes in a few turns; heavy work now has room to actually
# complete. Background/heavy tasks pass difficulty 'work'+ and get the big budgets.
_TURNS_BY_DIFF = {"triage": 15, "work": 40, "orchestrator": 60, "hard": 80}

# Intents whose answers live in the vault → pre-fetch the relevant notes (deterministic, ~free:
# BM25 + one embedding query) and hand them to the model so it answers in ONE turn instead of
# burning turns on vault_search/vault_read round-trips. THIS is how the long-term memory saves
# tokens. 'code' is excluded (its context is usually the repo, not the vault).
_RETRIEVE_INTENTS = {"recall", "research", "plan", "draft", "automate"}


# Servers whose tools can act outside the vault. Without a working gate they are never mounted.
_GATED_SERVERS = ("handoff",)
