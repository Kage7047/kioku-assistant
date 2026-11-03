"""Self-budget-guard for the subscription Agent SDK credit.

The Pro credit (~$20/mo, standard API rates, no rollover) is a wall: when it's gone,
Agent SDK requests stop. So we track month-to-date spend and DEGRADE gracefully:
conserve -> haiku-only -> halt non-essential, and ping you before the wall.

Recorded spend uses the SDK's own per-run cost when it reports one, else the PRICES table below
(cache reads and writes included). The pre-flight ceiling ignores cache discounts on purpose, so
it over-estimates: a safe wall to check against.
"""
from .db import pool
from .._compat import run_sync
from ..config import settings

# USD per million tokens: (input, output, cache write [5-minute TTL], cache read).
# Anthropic first-party list prices, checked 2026-11. Cache writes cost 1.25x input; cache reads
# are ~0.1x input except where noted. UPDATE when prices change — a wrong table silently breaks
# the guard in one direction or the other.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5":  (0.10, 0.50, 0.125, 0.01),   # prompts <= 100K tokens
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5":   (4.00, 20.00, 5.00, 0.20),
    "claude-fable-5-1":  (10.00, 50.00, 12.50, 0.25),
    # previous generation, still served
    "claude-haiku-4-5":  (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-5":   (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5":     (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8":   (5.00, 25.00, 6.25, 0.50),
    "claude-fable-5":    (10.00, 50.00, 12.50, 1.00),
}
# An unknown model is priced as the most expensive known one: the guard must over-, never under-estimate.
DEFAULT_PRICE = max(PRICES.values())

_TIER = {
    "triage": settings.model_triage,
    "work": settings.model_work,
    "orchestrator": settings.model_orchestrator,
    "hard": settings.model_hard,
}


def price(model: str) -> tuple[float, float, float, float]:
    return PRICES.get(model, DEFAULT_PRICE)


def cost_usd(model: str, tokens_in: int, tokens_out: int,
             cache_read: int = 0, cache_write: int = 0) -> float:
    """Cost of a run from its token counts. `tokens_in` is the UNCACHED input only — the API reports
    cache reads and writes separately, and ignoring them under-counts long cached sessions."""
    pi, po, pw, pr = price(model)
    return round((tokens_in * pi + tokens_out * po + cache_write * pw + cache_read * pr) / 1e6, 6)


async def month_to_date_spend() -> float:
    p = await pool()
    val = await p.fetchval(
        "SELECT COALESCE(SUM(cost_usd),0) FROM runs "
        "WHERE created_at >= date_trunc('month', now())"
    )
    return float(val or 0.0)


def mode_for(fraction: float) -> str:
    if fraction >= 1.0:                       return "exhausted"
    if fraction >= settings.budget_halt_at:   return "halt_nonessential"
    if fraction >= settings.budget_haiku_at:  return "haiku_only"
    if fraction >= settings.budget_conserve_at: return "conserve"
    return "normal"


def route(difficulty: str, mode: str) -> str:
    """Difficulty tier -> concrete model, tightened by budget mode."""
    if mode in ("haiku_only", "halt_nonessential", "exhausted"):
        return settings.model_triage
    if mode == "conserve" and difficulty in ("hard", "orchestrator"):
        return settings.model_work            # never auto-burn Opus/Fable while conserving
    return _TIER.get(difficulty, settings.model_triage)


async def check(difficulty: str, essential: bool) -> dict:
    spend = await month_to_date_spend()
    credit = settings.agent_sdk_monthly_credit_usd or 1.0
    frac = spend / credit
    mode = mode_for(frac)
    allowed = True
    if mode in ("halt_nonessential", "exhausted"):
        allowed = essential                   # background/pollers refused; you can still ask
    return {
        "allowed": allowed,
        "mode": mode,
        "model": route(difficulty, mode),
        "spend": round(spend, 2),
        "credit": credit,
        "remaining": round(max(credit - spend, 0), 2),
        "fraction": round(frac, 3),
    }


def check_sync(difficulty: str, essential: bool) -> dict:
    return run_sync(check(difficulty, essential))


# ---- pre-flight: estimate a run's worst-case cost BEFORE it starts ----
CHARS_PER_TOKEN = 4  # rough; multilingual content runs ~3.5–4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def ceiling_cost(model: str, prompt: str, max_turns: int | None = None) -> float:
    """Worst-case bound for one capped agentic run: up to max_turns turns, each
    re-sending a bounded context and emitting up to max_output_tokens. Prompt caching
    makes this an over-estimate in practice, so it's a safe wall to check against.
    A lower per-run turn cap (cheap intents) tightens the ceiling → fewer needless refusals."""
    ri, ro, _, _ = price(model)
    ctx_in = settings.preflight_context_tokens + estimate_tokens(prompt)
    per_turn = ctx_in / 1e6 * ri + settings.max_output_tokens / 1e6 * ro
    return round((max_turns or settings.max_turns) * per_turn, 4)


async def preflight(difficulty: str, prompt: str, essential: bool, max_turns: int | None = None) -> dict:
    """Decide BEFORE spending: allow / downgrade / refuse, based on projected ceiling."""
    snap = await check(difficulty, essential)
    model, ceil, decision, note = snap["model"], None, "allow", ""
    ceil = ceiling_cost(model, prompt, max_turns)

    if not snap["allowed"]:
        decision, note = "refuse", f"budget mode '{snap['mode']}' pauses non-essential work"
    elif ceil > snap["remaining"]:
        cheap = settings.model_triage                      # try the floor before refusing
        cheap_ceil = ceiling_cost(cheap, prompt, max_turns)
        if cheap_ceil <= snap["remaining"]:
            model, ceil, note = cheap, cheap_ceil, "downgraded to Haiku to fit remaining credit"
        else:
            decision, note = "refuse", "projected worst-case exceeds remaining credit even on Haiku"

    return {**snap, "model": model, "projected_ceiling": ceil,
            "decision": decision, "note": note}


def preflight_sync(difficulty: str, prompt: str, essential: bool) -> dict:
    return run_sync(preflight(difficulty, prompt, essential))
