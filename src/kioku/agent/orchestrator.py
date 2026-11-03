"""run_agent: one capped, budget-checked, gated agent session, streamed to Redis.

The pieces live next door: prompts.py (what a run is told), toolsets.py (what it may use),
gate.py (what needs the owner's approval) and usage.py (what it cost).
"""
import asyncio
import json

import redis.asyncio as aioredis
from claude_agent_sdk import query, ClaudeAgentOptions

from ..config import settings
from ..memory import budget
from .tools.vault import vault_server
from .tools.calendar import calendar_server
from .tools.scheduler import scheduler_server
from .tools.watch import watch_server
from .tools.handoff import handoff_server

# run_agent's building blocks; re-exported so `orchestrator.<name>` keeps working.
from .gate import _approved_call_gate, _outbound_gate, _sdk_permission_types  # noqa: F401
from .prompts import BOOT, _conversation_preamble, _load_boot, _vault_context, _verbosity_directive  # noqa: F401
from .toolsets import (  # noqa: F401
    _ALL_BUILTIN, _CAL, _DISALLOWED_BUILTINS, _EXTERNAL_HINTS, _GATED_SERVERS, _HANDOFF,
    _INTENT_NEEDS_EXTERNAL, _INTENT_TOOLS, _RETRIEVE_INTENTS, _SCHED, _TURNS_BY_DIFF, _VAULT_READ,
    _VAULT_WRITE, _WEB,
)
from .usage import UsageMeter, _limit_note  # noqa: F401



async def _emit(run_id: str, event: dict):
    r = aioredis.from_url(settings.redis_url)
    await r.publish(f"run:{run_id}", json.dumps(event))
    await r.aclose()


async def run_agent(run_id: str, prompt: str, difficulty: str = "triage",
                    essential: bool = True, conversational: bool = False,
                    intent: str | None = None, verbosity: str = "normal",
                    retrieve_query: str | None = None,
                    timeout_seconds: int | None = None,
                    approved_call: dict | None = None) -> dict:
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
    from .mcp_servers import external_servers
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
    _local = ("vault", "calendar", "scheduler", "watch", "handoff")
    allowed = list(builtin)
    # Every run has a gate. A normal run stages outbound calls for approval; an approved-action run
    # may make exactly the one approved call. External (Composio / remote MCP) tools are never put in
    # allowed_tools, so each of their calls falls through to the gate.
    gate = _approved_call_gate(approved_call) if approved_call else _outbound_gate(run_id)
    if approved_call:
        want_external = True
        allowed = []                       # nothing auto-approved; the gate allows the one call
    if want_external:
        servers.update(external_servers())  # Gmail/Calendar/Drive/Notion if enabled + configured

    use_subagents = settings.subagents_enabled and not approved_call and (
        intent is None or intent in ("research", "code") or difficulty in ("orchestrator", "hard"))
    if use_subagents:
        allowed = allowed + ["Agent"]

    opt_kwargs = dict(
        model=model,
        system_prompt=BOOT + _load_boot(),  # static persona (cached) + live boot/persona/profile
        mcp_servers=servers,
        allowed_tools=allowed,
        # Dangerous built-in FS/shell tools are stripped from context: Kioku's filesystem IS the
        # vault, reached only through the guarded mcp__vault__* tools.
        disallowed_tools=_DISALLOWED_BUILTINS,
        max_turns=eff_turns,                # HARD CAP (per-difficulty; ≤ settings.max_turns)
        permission_mode="default",
    )
    if gate is not None:
        opt_kwargs["can_use_tool"] = gate
    if use_subagents:
        opt_kwargs["max_budget_usd"] = settings.subagent_budget_usd
    try:
        options = ClaudeAgentOptions(**opt_kwargs)
    except TypeError:                        # older SDK missing a newer kwarg — degrade SAFELY
        opt_kwargs.pop("max_budget_usd", None)
        opt_kwargs.pop("can_use_tool", None)
        gate = None
        options = None
    if gate is None:
        # No permission callback means no way to stop an outbound call. Run with Kioku's own tools
        # only (bypass is then safe: nothing mounted can leave the vault) — or not at all if the
        # point of the run was an approved outbound action.
        if approved_call:
            msg = ("Cannot execute the approved action: this claude-agent-sdk has no permission "
                   "callback, so the call could not be scoped to what you approved. Nothing ran.")
            await _emit(run_id, {"type": "done", "text": msg})
            return {"text": msg, "tokens_in": 0, "tokens_out": 0, "model": model, "skipped": True}
        opt_kwargs["mcp_servers"] = {n: v for n, v in servers.items()
                                     if n in _local and n not in _GATED_SERVERS}
        opt_kwargs["allowed_tools"] = [t for t in allowed if not t.startswith("mcp__handoff__")]
        opt_kwargs["permission_mode"] = "bypassPermissions"
        options = ClaudeAgentOptions(**opt_kwargs)

    await _emit(run_id, {"type": "start", "model": model, "mode": b["mode"]})
    state = {"text": "", "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cache_write": 0,
             "cost_usd": None}
    usage_meter = UsageMeter()

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
            usage_meter.observe(msg)
            state.update(usage_meter.totals())

    # A run should never hang until the 15-min stale-reaper: a spent usage limit or a stalled
    # subprocess is caught here and turned into a clear reply. Background jobs get a long budget.
    # Interactive chat (conversational) stays snappy; background jobs get the long budget to finish.
    wall = timeout_seconds or (settings.interactive_timeout_seconds if conversational
                               else settings.background_timeout_seconds)
    try:
        await asyncio.wait_for(_consume(), timeout=wall)
    except TimeoutError:
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
                    "cache_read": state["cache_read"], "cache_write": state["cache_write"],
                    "cost_usd": state["cost_usd"]}
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
            "cache_read": state["cache_read"], "cache_write": state["cache_write"],
            "cost_usd": state["cost_usd"]}
