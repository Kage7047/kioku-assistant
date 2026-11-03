"""Budget guard: cost maths, degradation modes, routing and the pre-flight decision."""
import pytest

from kioku.config import settings
from kioku.memory import budget


def _spend(monkeypatch, usd: float):
    async def fake():
        return usd
    monkeypatch.setattr(budget, "month_to_date_spend", fake)


# ---- cost ----------------------------------------------------------------------------
def test_cost_uses_per_model_rates():
    # 1M in + 1M out on the triage model = its input + output rate
    ri, ro = budget.RATES[settings.model_triage]
    assert budget.cost_usd(settings.model_triage, 1_000_000, 1_000_000) == pytest.approx(ri + ro)


def test_cost_unknown_model_falls_back_to_default_rate():
    ri, ro = budget.DEFAULT_RATE
    assert budget.cost_usd("some-future-model", 1_000_000, 0) == pytest.approx(ri)


def test_cost_zero_tokens_is_free():
    assert budget.cost_usd(settings.model_work, 0, 0) == 0


# ---- modes ---------------------------------------------------------------------------
@pytest.mark.parametrize(("fraction", "mode"), [
    (0.0, "normal"),
    (settings.budget_conserve_at - 0.01, "normal"),
    (settings.budget_conserve_at, "conserve"),
    (settings.budget_haiku_at, "haiku_only"),
    (settings.budget_halt_at, "halt_nonessential"),
    (1.0, "exhausted"),
    (3.5, "exhausted"),
])
def test_mode_thresholds(fraction, mode):
    assert budget.mode_for(fraction) == mode


# ---- routing -------------------------------------------------------------------------
@pytest.mark.parametrize(("difficulty", "model"), [
    ("triage", settings.model_triage),
    ("work", settings.model_work),
    ("orchestrator", settings.model_orchestrator),
    ("hard", settings.model_hard),
    ("nonsense", settings.model_triage),
])
def test_route_normal_mode_follows_difficulty(difficulty, model):
    assert budget.route(difficulty, "normal") == model


@pytest.mark.parametrize("difficulty", ["orchestrator", "hard"])
def test_conserve_never_auto_burns_top_models(difficulty):
    assert budget.route(difficulty, "conserve") == settings.model_work


def test_conserve_keeps_cheap_tiers():
    assert budget.route("triage", "conserve") == settings.model_triage
    assert budget.route("work", "conserve") == settings.model_work


@pytest.mark.parametrize("mode", ["haiku_only", "halt_nonessential", "exhausted"])
def test_late_modes_force_the_cheapest_model(mode):
    assert budget.route("hard", mode) == settings.model_triage


# ---- check ---------------------------------------------------------------------------
async def test_check_reports_remaining_credit(monkeypatch):
    _spend(monkeypatch, 5.0)
    snap = await budget.check("work", essential=False)
    assert snap["allowed"] is True
    assert snap["mode"] == "normal"
    assert snap["remaining"] == pytest.approx(settings.agent_sdk_monthly_credit_usd - 5.0)


async def test_halt_refuses_background_but_not_the_owner(monkeypatch):
    _spend(monkeypatch, settings.agent_sdk_monthly_credit_usd * settings.budget_halt_at)
    assert (await budget.check("work", essential=False))["allowed"] is False
    assert (await budget.check("work", essential=True))["allowed"] is True


# ---- pre-flight ----------------------------------------------------------------------
def test_ceiling_grows_with_turns_and_prompt():
    m = settings.model_work
    short = budget.ceiling_cost(m, "hi", max_turns=5)
    assert budget.ceiling_cost(m, "hi", max_turns=10) == pytest.approx(short * 2, rel=1e-3)
    assert budget.ceiling_cost(m, "x" * 400_000, max_turns=5) > short


async def test_preflight_allows_when_ceiling_fits(monkeypatch):
    _spend(monkeypatch, 0.0)
    d = await budget.preflight("triage", "what's on today?", essential=True, max_turns=5)
    assert d["decision"] == "allow"
    assert d["model"] == settings.model_triage
    assert d["projected_ceiling"] <= d["remaining"]


async def test_preflight_downgrades_to_haiku_before_refusing(monkeypatch):
    credit = settings.agent_sdk_monthly_credit_usd
    work_ceiling = budget.ceiling_cost(settings.model_work, "plan my week", 40)
    haiku_ceiling = budget.ceiling_cost(settings.model_triage, "plan my week", 40)
    assert haiku_ceiling < work_ceiling
    # leave just enough credit for the Haiku ceiling, not the Sonnet one
    _spend(monkeypatch, credit - (haiku_ceiling + work_ceiling) / 2)
    d = await budget.preflight("work", "plan my week", essential=True, max_turns=40)
    assert d["decision"] == "allow"
    assert d["model"] == settings.model_triage
    assert "downgraded" in d["note"]


async def test_preflight_refuses_when_even_haiku_does_not_fit(monkeypatch):
    _spend(monkeypatch, settings.agent_sdk_monthly_credit_usd - 0.0001)
    d = await budget.preflight("triage", "anything", essential=True, max_turns=80)
    assert d["decision"] == "refuse"


async def test_preflight_refuses_background_work_in_halt_mode(monkeypatch):
    _spend(monkeypatch, settings.agent_sdk_monthly_credit_usd * settings.budget_halt_at)
    d = await budget.preflight("triage", "nightly digest", essential=False, max_turns=1)
    assert d["decision"] == "refuse"
    assert "halt_nonessential" in d["note"]
