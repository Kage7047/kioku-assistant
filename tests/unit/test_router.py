"""Intent router: command detection, heuristics, difficulty and verbosity."""
import pytest

from kioku.agent import router


# ---- commands --------------------------------------------------------------------------
@pytest.mark.parametrize(("text", "cmd"), [
    ("/budget", "budget"),
    ("/learn python", "learn"),               # slash always wins, even with an object
    ("audit the vault", "audit"),
    ("organise my notes", "organize"),        # British spelling is normalised
    ("bulk import", "import"),
    ("learn", "learn"),                       # bare weak verb is a command
    ("review the week", "review"),            # weak verb + filler only
])
def test_real_commands_are_detected(text, cmd):
    assert router.command_name(text) == cmd


@pytest.mark.parametrize("text", [
    "what's my grocery budget?",              # a question that mentions a command word
    "learn python this month",                # weak verb with a real object
    "review the contract Anna sent and flag risks",
    "budget for the trip to Lisbon next week including flights hotel and food",  # too long
    "how do I audit a Postgres role?",
    "",
    "   ",
    "hello there",
])
def test_ordinary_messages_are_not_commands(text):
    assert router.command_name(text) is None


# ---- heuristics ------------------------------------------------------------------------
@pytest.mark.parametrize(("text", "intent"), [
    ("remember that Anna's birthday is 3 May", "capture"),
    ("research the best Postgres queue libraries", "research"),
    ("refactor the poller module", "code"),
    ("plan my week", "plan"),
    ("draft a reply to the landlord", "draft"),
    ("every morning send me the weather", "automate"),
    ("alert me when the deploy fails", "automate"),
    ("/status", "command"),
    ("where did I put the passport scan", "recall"),
])
def test_heuristic_intents(text, intent):
    assert router.heuristic(text) == intent


@pytest.mark.parametrize(("text", "deep"), [
    ("analyze the trade-offs of moving to Redis streams", True),
    ("why does the worker restart at night", True),
    ("word " * 40, True),                     # long messages count as deep
    ("what's on today", False),
])
def test_depth_detection(text, deep):
    assert router._is_deep(text) is deep


# ---- classify ----------------------------------------------------------------------------
async def test_classify_skips_the_model_when_heuristics_are_confident(monkeypatch):
    calls = []

    async def spy(text):
        calls.append(text)
        return "research"

    monkeypatch.setattr(router, "_llm_classify", spy)
    out = await router.classify("draft a reply to the landlord")
    assert out["intent"] == "draft"
    assert out["difficulty"] == "work"
    assert calls == []


async def test_classify_asks_the_model_only_for_ambiguous_messages(monkeypatch):
    async def model_says(text):
        return "research"

    monkeypatch.setattr(router, "_llm_classify", model_says)
    out = await router.classify("the Kalshi thing from last week")
    assert out["intent"] == "research"
    assert out["verbosity"] == "deep"


async def test_classify_falls_back_to_recall_when_model_is_unavailable(monkeypatch):
    async def down(text):
        return None

    monkeypatch.setattr(router, "_llm_classify", down)
    out = await router.classify("the Kalshi thing from last week")
    assert out == {"intent": "recall", "difficulty": "triage", "essential": True,
                   "verbosity": "brief", "command": None}


async def test_deep_recall_gets_a_smarter_model(monkeypatch):
    async def down(text):
        return None

    monkeypatch.setattr(router, "_llm_classify", down)
    out = await router.classify("walk me through how the budget guard decides")
    assert out["intent"] == "recall"
    assert out["difficulty"] == "work"
    assert out["verbosity"] == "deep"


# ---- the Haiku classifier itself ----------------------------------------------------------
def _sdk(monkeypatch, *messages):
    import claude_agent_sdk

    from tests import fakes
    q = fakes.FakeQuery(*messages)
    monkeypatch.setattr(claude_agent_sdk, "query", q)
    monkeypatch.setattr(claude_agent_sdk, "ClaudeAgentOptions", fakes.RecordingOptions)
    return q


async def test_llm_classify_reads_the_sdk_message_stream(monkeypatch):
    from tests import fakes
    q = _sdk(monkeypatch, fakes.text('{"intent": "research"}'), fakes.result('{"intent": "research"}'))
    assert await router._llm_classify("the Kalshi thing") == "research"
    assert q.last_options.max_turns == 1


async def test_llm_classify_reads_a_result_only_stream(monkeypatch):
    from tests import fakes
    _sdk(monkeypatch, fakes.result('Sure: {"intent": "plan"}'))
    assert await router._llm_classify("next week") == "plan"


@pytest.mark.parametrize("reply", ['{"intent": "hack the planet"}', "no json here", ""])
async def test_llm_classify_rejects_unknown_or_garbled_replies(monkeypatch, reply):
    from tests import fakes
    _sdk(monkeypatch, fakes.result(reply))
    assert await router._llm_classify("x") is None
