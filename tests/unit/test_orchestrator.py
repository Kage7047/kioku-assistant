"""run_agent end to end against a scripted model: budget pre-flight, tool narrowing, the outbound
gate wiring, streaming, token accounting, and every failure path a headless agent has to survive."""
import pytest

from kioku.agent import orchestrator as O
from kioku.config import settings
from kioku.memory import budget
from tests import fakes
from tests.conftest import write_note


@pytest.fixture
def harness(monkeypatch, vault, fake_redis, no_notify):
    """Wire run_agent to fakes: no SDK subprocess, no Redis pub/sub, no Postgres, no connectors."""
    events: list[dict] = []

    async def emit(run_id, event):
        events.append(event)

    async def spend():
        return harness.spend

    monkeypatch.setattr(O, "_emit", emit)
    monkeypatch.setattr(O, "ClaudeAgentOptions", fakes.RecordingOptions)
    monkeypatch.setattr(budget, "month_to_date_spend", spend)
    monkeypatch.setattr("kioku.agent.mcp_servers.external_servers", lambda: {"composio": {"type": "http"}})

    class H:
        spend = 0.0

        def model(self, *messages, **kw):
            q = fakes.FakeQuery(*messages, **kw)
            monkeypatch.setattr(O, "query", q)
            return q

    harness = H()
    harness.events = events
    harness.vault = vault
    return harness


async def test_happy_path_streams_text_and_counts_tokens(harness):
    q = harness.model(fakes.text("Your dentist is Thursday ", tokens_in=1200, tokens_out=40),
                      fakes.text("at 9:30.", tokens_in=0, tokens_out=10, cache_read=900),
                      fakes.result("ignored because text was streamed", tokens_in=0, tokens_out=0))
    out = await O.run_agent("r1", "when is the dentist?", difficulty="triage", intent="recall")
    assert out["text"] == "Your dentist is Thursday at 9:30."
    assert (out["tokens_in"], out["tokens_out"], out["cache_read"]) == (1200, 50, 900)
    assert out["skipped"] is False
    assert [e["type"] for e in harness.events] == ["preflight", "start", "text", "text", "done"]
    assert q.last_options.model == settings.model_triage


async def test_result_message_is_used_when_no_text_blocks_arrive(harness):
    harness.model(fakes.result("Filed to inbox/idea.md.", tokens_in=300, tokens_out=12))
    out = await O.run_agent("r1", "remember: try Redis streams", intent="capture")
    assert out["text"] == "Filed to inbox/idea.md."


async def test_budget_refusal_never_calls_the_model(harness):
    harness.spend = settings.agent_sdk_monthly_credit_usd       # wallet empty
    q = harness.model(fakes.text("should never run"))
    out = await O.run_agent("r1", "nightly digest", essential=False)
    assert out["skipped"] is True
    assert out["text"].startswith("Skipped (")
    assert q.calls == []
    assert harness.events[-1] == {"type": "done", "text": out["text"]}


async def test_persona_and_live_config_form_the_system_prompt(harness):
    write_note(harness.vault, "system/persona.md", "Address the owner as 'sir'.")
    write_note(harness.vault, "system/profile.md", "Prefers answers under 3 lines.")
    q = harness.model(fakes.result("ok"))
    await O.run_agent("r1", "hi", intent="recall")
    sp = q.last_options.system_prompt
    assert sp.startswith(O.BOOT)                                   # static prefix stays cacheable
    assert "Address the owner as 'sir'." in sp and "Prefers answers under 3 lines." in sp


async def test_retrieval_context_is_injected_for_vault_intents(harness, monkeypatch):
    async def hits(query, k):
        return [{"path": "people/anna.md", "excerpt": "Anna: dentist, Thursday 9:30"}]

    monkeypatch.setattr("kioku.memory.retrieval.hybrid_search", hits)
    q = harness.model(fakes.result("Thursday."))
    await O.run_agent("r1", "when is Anna's appointment?", intent="recall", retrieve_query="Anna appointment")
    assert '<vault_excerpt path="people/anna.md">' in q.last_prompt
    assert q.last_prompt.rstrip().endswith("when is Anna's appointment?")


async def test_code_intent_skips_retrieval(harness, monkeypatch):
    called = []

    async def hits(query, k):
        called.append(query)
        return []

    monkeypatch.setattr("kioku.memory.retrieval.hybrid_search", hits)
    harness.model(fakes.result("done"))
    await O.run_agent("r1", "refactor the poller", intent="code", retrieve_query="poller")
    assert called == []


# ---- tool surface ------------------------------------------------------------------------
async def test_recall_gets_vault_and_web_only(harness):
    q = harness.model(fakes.result("ok"))
    await O.run_agent("r1", "where is my passport scan?", intent="recall")
    opts = q.last_options
    assert set(opts.allowed_tools) == set(O._VAULT_READ + O._VAULT_WRITE + O._WEB)
    assert "composio" not in opts.mcp_servers                     # no connector, no hint → not mounted
    for banned in ("Bash", "Read", "Write", "Edit"):
        assert banned in opts.disallowed_tools


async def test_connector_hint_mounts_external_tools_behind_the_gate(harness):
    q = harness.model(fakes.result("ok"))
    await O.run_agent("r1", "what's on my calendar tomorrow?", intent="recall")
    opts = q.last_options
    assert "composio" in opts.mcp_servers
    assert opts.permission_mode == "default"
    assert callable(opts.can_use_tool)
    assert not any(t.startswith("mcp__composio__") for t in opts.allowed_tools)   # must hit the gate


async def test_subagents_only_for_heavy_work(harness):
    q = harness.model(fakes.result("ok"))
    await O.run_agent("r1", "deep research on queues", intent="research", difficulty="work")
    assert "Agent" in q.last_options.allowed_tools
    assert q.last_options.max_budget_usd == settings.subagent_budget_usd
    await O.run_agent("r2", "what's for dinner", intent="recall")
    assert "Agent" not in q.last_options.allowed_tools


@pytest.mark.parametrize(("difficulty", "turns"), [("triage", 15), ("work", 40), ("hard", 80)])
async def test_turn_caps_follow_difficulty(harness, difficulty, turns):
    q = harness.model(fakes.result("ok"))
    await O.run_agent("r1", "x", difficulty=difficulty, intent="recall")
    assert q.last_options.max_turns == min(turns, settings.max_turns)


# ---- outbound gate callback --------------------------------------------------------------
async def test_gate_stages_outbound_calls_and_allows_reads(harness, fake_redis, no_notify):
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    gate = O._outbound_gate("run-9")
    denied = await gate("mcp__composio__GMAIL_SEND_EMAIL", {"to": "anna@example.com"}, None)
    assert isinstance(denied, PermissionResultDeny)
    assert "staged" in denied.message
    assert len(fake_redis.keys("approval:*")) == 1
    allowed = await gate("mcp__composio__GMAIL_FETCH_EMAILS", {"query": "is:unread"}, None)
    assert isinstance(allowed, PermissionResultAllow)


# ---- failure paths -----------------------------------------------------------------------
async def test_timeout_returns_partial_text_instead_of_hanging(harness, monkeypatch):
    harness.model(fakes.text("Partial answer"), hang=True)
    out = await O.run_agent("r1", "x", intent="recall", timeout_seconds=0.05)
    assert out["skipped"] is True and out["limited"] is True
    assert out["text"] == "Partial answer"


async def test_turn_cap_keeps_partial_work_and_offers_to_continue(harness):
    harness.model(fakes.text("Step 1 done. "),
                  raise_after=RuntimeError("Reached maximum number of turns (15)"))
    out = await O.run_agent("r1", "x", intent="recall")
    assert out["turn_capped"] is True and out["skipped"] is False
    assert out["text"].startswith("Step 1 done.") and "continue" in out["text"]


async def test_usage_limit_errors_become_a_clear_message(harness):
    harness.model(raise_after=RuntimeError("You've hit your weekly limit · resets Mon 9:00"))
    out = await O.run_agent("r1", "x", intent="recall")
    assert out["limited"] is True
    assert "weekly" in out["text"] and "usage limit" in out["text"]


async def test_unexpected_errors_are_reported_not_raised(harness):
    harness.model(raise_after=ValueError("subprocess exited 1"))
    out = await O.run_agent("r1", "x", intent="recall")
    assert out["text"].startswith("Run failed: subprocess exited 1")
    assert out["limited"] is False


async def test_empty_output_is_never_returned_as_blank(harness):
    harness.model(fakes.result(""))
    out = await O.run_agent("r1", "x", intent="recall")
    assert out["text"] == "(no output)"


@pytest.mark.parametrize(("text", "expected"), [
    ("Error 429 Too Many Requests", "5-hour"),
    ("weekly limit reached", "weekly"),
    ("all good, here is your answer", None),
])
def test_limit_note(text, expected):
    note = O._limit_note(text)
    assert (note is None) if expected is None else (expected in note)
