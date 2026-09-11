"""Self-budget-guard for the subscription Agent SDK credit.

The Pro credit (~$20/mo, standard API rates, no rollover) is a wall: when it's gone,
Agent SDK requests stop. So we track month-to-date spend and DEGRADE gracefully:
conserve -> haiku-only -> halt non-essential, and ping you before the wall.

Rates are conservative (ignore prompt-cache discounts), so real spend is <= our estimate.
UPDATE RATES when Anthropic changes prices.
"""
from .db import pool
from .._compat import run_sync
from ..config import settings

# per-MTok (input, output) USD
RATES = {
    settings.model_triage:       (1.0, 5.0),    # Haiku 4.5
    settings.model_work:         (2.0, 10.0),   # Sonnet 5 (intro; may rise to 3/15)
    settings.model_orchestrator: (5.0, 25.0),   # Opus
    settings.model_hard:         (10.0, 50.0),  # Fable 5
}
DEFAULT_RATE = (3.0, 15.0)

_TIER = {
    "triage": settings.model_triage,
    "work": settings.model_work,
    "orchestrator": settings.model_orchestrator,
    "hard": settings.model_hard,
}


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    ri, ro = RATES.get(model, DEFAULT_RATE)
    return round(tokens_in / 1e6 * ri + tokens_out / 1e6 * ro, 4)


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
    ri, ro = RATES.get(model, DEFAULT_RATE)
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
