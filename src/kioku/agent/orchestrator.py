"""Single-agent runner (Phase 0), now budget-aware. Phase 2 adds sub-agent fan-out
(sub-agents stage drafts via memory.pending; orchestrator calls apply_drafts).

Verify query()/ClaudeAgentOptions against your installed claude-agent-sdk version.
"""
import asyncio
import json
import re

import redis.asyncio as aioredis
from claude_agent_sdk import query, ClaudeAgentOptions

from ..config import settings
from ..memory import budget
from .tools.vault import vault_server
from .tools.calendar import calendar_server
from .tools.scheduler import scheduler_server
from .tools.watch import watch_server
from .tools.handoff import handoff_server

# Stable, cache-friendly prefix — keep constant so prompt-caching hits (~10% of input).
# The live boot/persona/profile is appended AFTER this by _load_boot(); keeping the static
# character here as the prefix means the cache still hits even as the live context changes.
BOOT = """You are Kioku (記憶, "memory"), the private assistant of a single owner.
Speak like JARVIS: unflappable, precise, quietly witty, always a half-step ahead — competent
understatement, never eager, never servile, never chatty. A trusted right hand. Lead with the answer;
no preamble, no flattery, no "happy to help", no restating their question back to them. This voice is
not optional — hold it in every reply, short or long.

You own a markdown vault (your source of truth) via the `vault` tools — read it before answering,
and capture new notes/tasks to inbox/ silently as you go. Do deterministic work yourself; call
tools for I/O.

Autonomy — this matters: when the owner gives you a direct instruction, CARRY IT OUT. Do not ask them to
reconfirm something they already told you to do, and NEVER tell them you "need permission" to touch your
own vault — you never do. The vault is YOURS: read, write, edit, delete, move and reorganise it freely
and immediately (only your system/ config spine and .git are protected). Filing a note or a report to
the vault requires no approval, ever — just do it, then tell them it's done. Stop for approval ONLY on
genuinely OUTBOUND or world-irreversible actions: sending a message/email to a real person, publishing
publicly, spending money, or deleting something OUTSIDE the vault. Those you DRAFT or stage — you do
not execute them. Reading anything is always fine.

Length matches the task: a simple question gets a crisp 1–3 sentence answer; a research or analysis
request earns a fuller, structured one. The cheapest token is the one you don't spend.

You can search and read the web (WebSearch, WebFetch) for current facts — check the vault first,
keep queries tight (they cost), and cite what you use.

HOW YOU REACH THEM — never ask "how can I do that?": you talk to the owner over **Telegram**, and it's
already wired. Anything you write to `_reports/` and any scheduled task's result is delivered to their
Telegram automatically — you don't need an API key or their help to send. To send something later or on
a cadence, use the `schedule_*` tools (a cron task whose output is pushed to Telegram). To act now,
just do it. Work linearly and do the job yourself by default — you have a generous step budget, so
use it to finish rather than stalling. NEVER narrate a plan to "dispatch parallel readers" or paste
sub-agent prompts into your reply. For a genuinely large, parallelizable job (deep research across
many sources, processing many files), you MAY delegate to focused sub-agents via the **Agent tool**
IF it's available to you this run — used sparingly, it multiplies cost. If the Agent tool isn't
offered, simply do the work yourself.

The sections that follow — YOUR CHARACTER, HOW YOU OPERATE, and WHAT YOU KNOW ABOUT THE USER — are
your BINDING configuration, not background reading. They are authoritative: follow them over any
generic assistant default, in every reply. This block is stable so it stays cached; honour it."""


def _load_boot() -> str:
    """Loads Kioku's live context after the static cached persona (BOOT) so caching still hits
    the stable prefix. Four files (all optional, all your data):
      system/boot.md     — live projects, current focus
      system/persona.md  — its character: how it addresses you, humor, when to push back
      system/playbook.md — how it operates: vault map, cheap-path answering, connector usage, autonomy
      system/profile.md  — its model of you: patterns, energy, preferences (grows over time)
    """
    from ..memory import vault as V
    out = ""
    for label, path in (("CURRENT CONTEXT", "system/boot.md"),
                        ("YOUR CHARACTER", "system/persona.md"),
                        ("YOUR INFRASTRUCTURE — WHAT YOU CAN DO", "system/capabilities.md"),
                        ("HOW YOU OPERATE", "system/playbook.md"),
                        ("WHAT YOU KNOW ABOUT THE USER", "system/profile.md")):
        try:
            out += f"\n\n{label} ({path}):\n" + V.read(path)
        except Exception:
            pass
    # Phase 4.2 — model-of-you PATTERNS: a compact, derived rhythm (active hours, avoidances, decision
    # style) so replies/nudges/timing fit how the owner actually operates. Tiny (loaded every session).
    try:
        from ..memory import patterns
        ps = patterns.summary()
        if ps:
            out += ("\n\nYOUR PATTERNS (how the owner tends to operate — fit timing and nudges to this, "
                    f"don't fight it):\n{ps}")
    except Exception:  # noqa: BLE001
        pass
    return out


async def _emit(run_id: str, event: dict):
    r = aioredis.from_url(settings.redis_url)
    await r.publish(f"run:{run_id}", json.dumps(event))
    await r.aclose()


async def _conversation_preamble(run_id: str, turns_n: int = 6) -> str:
    """A compact transcript of the last few exchanges so a chat message has continuity instead
    of cold-starting. Bounded (truncated) so it costs a few hundred tokens at most. Simple asks
    carry fewer turns (this preamble is re-sent every message and isn't cached)."""
    from ..memory import db
    try:
        turns = await db.recent_turns(turns_n, exclude_run_id=run_id)
    except Exception:  # noqa: BLE001  (never let history-loading break a run)
        return ""
    if not turns:
        return ""
    lines = ["RECENT CONVERSATION (most recent last — for continuity; the vault is still truth):"]
    for t in turns:
        lines.append(f"\nYou: {(t['input'] or '').strip()[:300]}")
        lines.append(f"Kioku: {(t['result_text'] or '').strip()[:400]}")
    return "\n".join(lines) + "\n\n---\n\n"


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
_HANDOFF = ["mcp__handoff__handoff_code", "mcp__handoff__handoff_status", "mcp__handoff__dev_task",
            "mcp__handoff__browser_task"]
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

# Signatures that mean "the Claude subscription usage limit was hit" (5-hour or weekly window),
# or a transient capacity error — surfaced from the SDK error OR from text the model returns.
_LIMIT_SIG = ("usage limit", "rate limit", "rate_limit", "ratelimit", "429",
              "too many requests", "quota", "credit balance", "overloaded",
              "weekly limit", "5-hour", "reached your", "resets at", "try again later",
              "insufficient", "capacity")


def _limit_note(s: str) -> str | None:
    """If a string looks like a usage/rate-limit signal, return a clear user-facing line."""
    low = (s or "").lower()
    if not any(k in low for k in _LIMIT_SIG):
        return None
    weekly = "weekly" in low
    which = "weekly" if weekly else "5-hour (session)"
    return (f"⛔ Claude usage limit reached — your {which} window is spent. "
            "I can't run model calls until it resets; I'll be ready the moment it does. "
            "(Vault reads, budget and status still work.)")


# Per-difficulty turn caps — GENEROUS. The 6-turn cap was killing real work mid-run (the #1 failure
# in testing). A simple recall still finishes in a few turns; heavy work now has room to actually
# complete. Background/heavy tasks pass difficulty 'work'+ and get the big budgets.
_TURNS_BY_DIFF = {"triage": 15, "work": 40, "orchestrator": 60, "hard": 80}

# Intents whose answers live in the vault → pre-fetch the relevant notes (deterministic, ~free:
# BM25 + one embedding query) and hand them to the model so it answers in ONE turn instead of
# burning turns on vault_search/vault_read round-trips. THIS is how the long-term memory saves
# tokens. 'code' is excluded (its context is usually the repo, not the vault).
_RETRIEVE_INTENTS = {"recall", "research", "plan", "draft", "automate"}


async def _vault_context(query: str) -> str:
    """Top-k relevant vault excerpts as a compact, bounded prompt block. Never fatal."""
    try:
        from ..memory import retrieval
        hits = await retrieval.hybrid_search(query, k=settings.retrieval_k)
    except Exception:  # noqa: BLE001
        return ""
    if not hits:
        return ""
    lines = ["RELEVANT VAULT CONTEXT (retrieved for you — read these before reaching for tools; "
             "use vault_read only if you need more than the excerpt):"]
    for h in hits:
        lines.append(f"\n[{h['path']}]\n{(h.get('excerpt') or '').strip()[:350]}")
    return "\n".join(lines) + "\n\n---\n\n"


def _outbound_gate(run_id: str):
    """A can_use_tool callback: auto-allow everything EXCEPT genuinely outbound / world-irreversible
    tool calls (send mail, external delete, post, transfer), which it STAGES for the user's approval
    (memory.approvals → Telegram + command center) instead of executing. The vault, scheduler, web,
    calendar and read-only connector tools all pass straight through.

    Returns None if the installed claude-agent-sdk lacks the permission-callback API — the caller then
    falls back to permission_mode='bypassPermissions' (so a missing API degrades to 'everything runs',
    never to the headless permission WALL this whole change exists to remove)."""
    try:
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
    except Exception:  # noqa: BLE001
        return None
    from ..memory import approvals

    async def _gate(tool_name, input_data, context):  # signature per SDK CanUseTool
        try:
            if approvals.is_outbound(tool_name, input_data):
                rec = approvals.stage(tool_name, input_data, run_id=run_id)
                return PermissionResultDeny(
                    message=(f"OUTBOUND action staged for the user's approval (id {rec['id']}); it did "
                             "NOT run and you must not retry it. Tell them plainly what you queued. If "
                             "it's an email/message, ALSO prepare it as a DRAFT now so it's ready the "
                             "moment they approve."))
        except Exception:  # noqa: BLE001 — a gate failure must never block a run
            return PermissionResultAllow()
        return PermissionResultAllow()

    return _gate


def _verbosity_directive(verbosity: str) -> str:
    if verbosity == "brief":
        return ("Answer directly in 1–3 sentences. No headings, no preamble, no bullet lists "
                "unless the answer is genuinely a list. Only expand if he asks.\n\n")
    if verbosity == "deep":
        return ("This warrants a thorough, well-structured answer: reason it through, use the "
                "vault and web as needed, and lay it out clearly.\n\n")
    return ""


async def run_agent(run_id: str, prompt: str, difficulty: str = "triage",
                    essential: bool = True, conversational: bool = False,
                    intent: str | None = None, verbosity: str = "normal",
                    retrieve_query: str | None = None,
                    timeout_seconds: int | None = None,
                    outbound_approved: bool = False) -> dict:
    """Run one capped, budget-checked agent session, streaming events to Redis.

    conversational=True prepends a short transcript of recent turns to the prompt so chat
    messages carry context. intent (when known) narrows the tool set to what that intent
    needs — cheaper. verbosity ('brief'|'normal'|'deep') tunes answer length. retrieve_query
    (when the intent's answer lives in the vault) pre-injects the top-k relevant notes so the
    model answers in one turn instead of paying for tool round-trips. Leave defaults for
    background jobs / generic /ask."""
    if verbosity and verbosity != "normal":
        prompt = _verbosity_directive(verbosity) + prompt
    # Retrieval-augment: fetch relevant vault context ONCE (cheap) and hand it over up front.
    if retrieve_query and (intent is None or intent in _RETRIEVE_INTENTS):
        prompt = await _vault_context(retrieve_query) + prompt
    if conversational:
        prompt = await _conversation_preamble(run_id, 3 if verbosity == "brief" else 6) + prompt
    eff_turns = min(settings.max_turns, _TURNS_BY_DIFF.get(difficulty, settings.max_turns))
    b = await budget.preflight(difficulty, prompt, essential, max_turns=eff_turns)
    await _emit(run_id, {"type": "preflight", **b})

    if b["decision"] == "refuse":
        msg = (f"Skipped ({b['note']}). Credit ${b['spend']}/${b['credit']} used, "
               f"~${b['projected_ceiling']} projected for this run, ${b['remaining']} left.")
        await _emit(run_id, {"type": "done", "text": msg})
        return {"text": msg, "tokens_in": 0, "tokens_out": 0,
                "model": b["model"], "skipped": True}

    model = b["model"]                      # preflight already picked/downgraded the model
    from .mcp_servers import external_servers, external_allowed
    # Unknown/None intent → full toolset (backward compatible, e.g. generic /ask).
    if intent is None or intent not in _INTENT_TOOLS:
        builtin, want_external = _ALL_BUILTIN, True
    else:
        builtin = _INTENT_TOOLS[intent]
        # Mount Composio for the actionable intents, OR whenever the request clearly touches a
        # connector (so a plain "what's on my calendar?" isn't answered with "I can't access it").
        want_external = intent in _INTENT_NEEDS_EXTERNAL or bool(_EXTERNAL_HINTS.search(prompt))
    servers = {"vault": vault_server, "calendar": calendar_server,
               "scheduler": scheduler_server, "watch": watch_server,
               "handoff": handoff_server}
    allowed = list(builtin)
    # Outbound gate: intercepts send/delete/post-type calls for approval. When it's active the
    # external (Composio) tools must NOT be auto-approved via the mcp__composio__* wildcard — they
    # have to fall THROUGH to the callback so it can allow reads and stage outbound calls. When the
    # gate is absent (SDK too old, or an approved-action run), we auto-approve them via wildcard.
    gate = None if outbound_approved else _outbound_gate(run_id)
    if want_external:
        servers.update(external_servers())  # Gmail/Calendar/Drive/Notion if enabled + configured
        _local = ("vault", "calendar", "scheduler", "watch", "handoff")
        if gate is None:
            allowed += external_allowed([n for n in servers if n not in _local])

    # Sub-agent fan-out: only for genuinely heavy jobs (deep research / code / generic full-tool runs),
    # where isolating context across parallel sub-agents pays off. Enabling the built-in `Agent` tool
    # lets the model spawn focused sub-agents; the per-run dollar cap (max_budget_usd) + env depth/
    # concurrency caps keep the token multiplier bounded. Never on cheap intents.
    use_subagents = settings.subagents_enabled and (
        intent is None or intent in ("research", "code") or difficulty in ("orchestrator", "hard"))
    if use_subagents:
        allowed = allowed + ["Agent"]

    opt_kwargs = dict(
        model=model,
        system_prompt=BOOT + _load_boot(),  # static persona (cached) + live boot/persona/profile
        mcp_servers=servers,
        allowed_tools=allowed,
        # Kioku runs HEADLESS (no human at a terminal to answer the SDK's permission prompt). In the
        # default mode any tool not in allowed_tools falls through to that prompt and — with no
        # can_use_tool handler — resolves to a silent BLOCK. That is what killed vault writes and
        # connector calls. Two safe modes now:
        #   • gate present  → permission_mode="default" + can_use_tool: the safe surface (vault/web/
        #     scheduler/calendar, in allowed_tools) auto-approves; Composio & co. fall through to the
        #     gate, which allows reads and STAGES outbound actions for approval.
        #   • gate absent   → permission_mode="bypassPermissions": everything mounted runs without a
        #     prompt (used on old SDKs lacking the callback API, and on approved-action re-runs).
        # Either way, dangerous built-in FS/shell tools are stripped from context (Kioku's filesystem
        # IS the vault, via the guarded mcp__vault__* tools).
        disallowed_tools=_DISALLOWED_BUILTINS,
        max_turns=eff_turns,                # HARD CAP (per-difficulty; ≤ settings.max_turns)
    )
    if gate is not None:
        opt_kwargs["permission_mode"] = "default"
        opt_kwargs["can_use_tool"] = gate
    else:
        opt_kwargs["permission_mode"] = "bypassPermissions"
    if use_subagents:
        opt_kwargs["max_budget_usd"] = settings.subagent_budget_usd
    try:
        options = ClaudeAgentOptions(**opt_kwargs)
    except TypeError:                        # older SDK missing one of the newer kwargs — degrade
        for k in ("max_budget_usd", "can_use_tool"):
            opt_kwargs.pop(k, None)
        opt_kwargs["permission_mode"] = "bypassPermissions"  # no callback → don't fall to a wall
        try:
            options = ClaudeAgentOptions(**opt_kwargs)
        except TypeError:                    # even permission_mode/disallowed_tools unsupported
            opt_kwargs.pop("permission_mode", None)
            opt_kwargs.pop("disallowed_tools", None)
            options = ClaudeAgentOptions(**opt_kwargs)

    await _emit(run_id, {"type": "start", "model": model, "mode": b["mode"]})
    state = {"text": "", "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0}

    async def _consume():
        async for msg in query(prompt=prompt, options=options):
            # AssistantMessage carries a list of content blocks; TextBlock has `.text`.
            content = getattr(msg, "content", None)
            if isinstance(content, list):
                for block in content:
                    btext = getattr(block, "text", None)
                    if isinstance(btext, str) and btext.strip():
                        state["text"] += btext
                        # progress preview for a live web view; Telegram renders the full
                        # answer once, from the terminal `done` event below.
                        await _emit(run_id, {"type": "text", "text": btext[:1500]})
            # The terminal ResultMessage carries the assembled answer in `.result`.
            result = getattr(msg, "result", None)
            if isinstance(result, str) and result.strip() and not state["text"].strip():
                state["text"] = result
                await _emit(run_id, {"type": "text", "text": result[:1500]})
            # usage may be a dict or an object depending on SDK version.
            usage = getattr(msg, "usage", None)
            if usage is not None:
                g = usage.get if isinstance(usage, dict) else (lambda k, d=0: getattr(usage, k, d))
                state["tokens_in"] += (g("input_tokens", 0) or 0)
                state["tokens_out"] += (g("output_tokens", 0) or 0)
                # cache verification (prompt caching is prefix-based + automatic in the SDK; this
                # proves it's hitting — cache_read should dominate on repeat runs).
                state["cache_read"] += (g("cache_read_input_tokens", 0) or 0)
                state["cache_write"] += (g("cache_creation_input_tokens", 0) or 0)

    # A run should never hang until the 15-min stale-reaper: a spent usage limit or a stalled
    # subprocess is caught here and turned into a clear reply. Background jobs get a long budget.
    # Interactive chat (conversational) stays snappy; background jobs get the long budget to finish.
    wall = timeout_seconds or (settings.interactive_timeout_seconds if conversational
                               else settings.background_timeout_seconds)
    try:
        await asyncio.wait_for(_consume(), timeout=wall)
    except asyncio.TimeoutError:
        note = (state["text"].strip() or
                "⏳ No reply in time — usually the Claude usage limit (5-hour or weekly) "
                "was hit, or the run stalled. I'll be ready when it resets.")
        await _emit(run_id, {"type": "done", "text": note})
        return {"text": note, "tokens_in": state["tokens_in"], "tokens_out": state["tokens_out"],
                "model": model, "skipped": True, "limited": True}
    except Exception as e:  # noqa: BLE001 — surface limits/failures instead of dying to a stale row
        es = str(e)
        # Hit the turn budget → NOT a failure: keep the partial work + invite a resume.
        if "maximum number of turns" in es.lower() and state["text"].strip():
            note = (state["text"].rstrip() +
                    "\n\n— (I reached my step budget for this run; say “continue” to pick up "
                    "where I left off.)")
            await _emit(run_id, {"type": "done", "text": note})
            return {"text": note, "tokens_in": state["tokens_in"], "tokens_out": state["tokens_out"],
                    "model": model, "skipped": False, "turn_capped": True,
                    "cache_read": state["cache_read"], "cache_write": state["cache_write"]}
        note = _limit_note(es) or f"Run failed: {es[:400]}"
        await _emit(run_id, {"type": "done", "text": note})
        return {"text": note, "tokens_in": state["tokens_in"], "tokens_out": state["tokens_out"],
                "model": model, "skipped": True, "limited": _limit_note(es) is not None}

    final_text = state["text"]
    # Some limit conditions come back as normal text (no exception) — catch those too.
    if not final_text.strip() or (state["tokens_out"] == 0 and _limit_note(final_text)):
        final_text = _limit_note(final_text) or final_text or "(no output)"
    await _emit(run_id, {"type": "done", "text": final_text})
    return {"text": final_text, "tokens_in": state["tokens_in"],
            "tokens_out": state["tokens_out"], "model": model, "skipped": False,
            "cache_read": state["cache_read"], "cache_write": state["cache_write"]}
