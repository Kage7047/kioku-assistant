"""Intent router — the front of the brain. Any input (Telegram, CLI, Obsidian, email,
webhook) comes here first; it decides WHAT you want so you never pick a 'mode'.

Two stages: a deterministic fast-path for obvious cases, then a cheap Haiku classify for
the rest, with a heuristic fallback so it never blocks or costs much. It also decides how
HARD the answer needs to be (model tier) and how LONG it should be (verbosity).
"""
import json
import re

INTENTS = {"recall", "research", "code", "plan", "draft", "automate", "capture", "command"}

# intent -> difficulty tier for budget routing
DIFFICULTY = {
    "recall": "triage", "capture": "triage", "command": "triage",
    "draft": "work", "plan": "work", "research": "work", "automate": "work",
    "code": "orchestrator",
}

# --- COMMAND detection ------------------------------------------------------------------
# A command is an operational instruction to Kioku's machinery (audit, budget, reindex…),
# NOT any message that happens to contain one of those words. The old regex matched the word
# anywhere, so "what's my grocery budget?" ran the budget command and dropped the question.
# Now a command must be a slash-command (/budget) OR a short message that LEADS with the
# command word — a genuine imperative, not a question that mentions it.
# Command words split into two tiers by how ambiguous they are in normal chat:
#  STRONG — rarely a verb-with-object, so a short leading imperative is enough ("audit the vault").
#  WEAK   — common verbs ("learn python", "review the plan", "connect to X") that must NOT hijack a
#           real request; they only count as a command when slash-prefixed or bare (verb + filler only).
_STRONG = {"audit", "reindex", "budget", "status", "digest", "organize", "organise",
           "radar", "opportunity", "opportunities", "job", "jobs", "skill", "skills",
           "pause", "resume", "import", "introspect"}
_WEAK = {"learn", "review", "connect", "propose", "ideas", "brainstorm", "proposals", "suggest"}
_FILLER = {"the", "a", "an", "my", "vault", "notes", "note", "brain", "map", "week",
           "about", "me", "everything", "now", "please", "up", "skill", "skills", "of", "for"}
_QUESTIONY = re.compile(r"[?？]|^\s*(what|what's|whats|how|why|when|who|where|which|do|does|"
                        r"is|are|can|could|should|would|tell me|show me|explain)\b", re.I)


def command_name(text: str) -> str | None:
    """Return the command keyword iff this message really is a command, else None.
    Slash always wins; bare strong words allow a short imperative; bare weak verbs must be
    followed only by filler (so 'learn python' stays a request, 'learn' is the command)."""
    t = (text or "").strip()
    if not t:
        return None
    slash = t.startswith("/")
    body = t[1:].strip() if slash else t
    words = [w for w in re.split(r"\s+", body.lower()) if w]
    if not words:
        return None
    kw = words[0]
    if kw == "bulk" and len(words) > 1 and words[1] in ("import", "ingest"):
        kw = "import"
    if kw == "organise":
        kw = "organize"
    if kw not in _STRONG and kw not in _WEAK:
        return None
    if slash:
        return kw                                       # explicit slash command always wins
    if _QUESTIONY.search(t):
        return None
    if kw in _WEAK:                                     # bare verb only — no real object after it
        return kw if all(w in _FILLER for w in words[1:]) else None
    return kw if len(words) <= 6 else None              # strong: short leading imperative


_HEUR = [
    (re.compile(r"^\s*(remember|note|save|todo|idea:|fyi|log)\b", re.I), "capture"),
    (re.compile(r"\b(research|investigate|look up|find out|compare|deep[-\s]?dive|analy[sz]e)\b", re.I), "research"),
    (re.compile(r"\b(code|implement|refactor|debug|script|build a|fix the)\b", re.I), "code"),
    (re.compile(r"\b(plan|schedule|book|arrange|itinerary)\b", re.I), "plan"),
    (re.compile(r"\b(draft|reply|compose|write a (message|post|email)|email)\b", re.I), "draft"),
    (re.compile(r"\b(every\s+(day|morning|evening|night|week|hour|month|mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
                r"each\s+(day|morning|week)|daily|weekly|monthly|automate|automation|recurring|schedules?|scheduled|"
                r"watch\s|monitor|keep an eye|keep track|alert me|notify me|let me know when|whenever)\b", re.I), "automate"),
]

# "deep" markers → escalate model + widen the answer even for a plain recall question.
_DEEP = re.compile(r"\b(analy[sz]e|analysis|research|investigate|compare|trade[-\s]?offs?|"
                   r"deep[-\s]?dive|thorough|in[-\s]depth|pros and cons|strategy|design|"
                   r"why (do|does|is|are|would)|walk me through|step[-\s]by[-\s]step|"
                   r"reason(ing)? through|evaluate|assess)\b", re.I)


def _is_deep(text: str) -> bool:
    return bool(_DEEP.search(text)) or len(text.split()) >= 40


def heuristic(text: str) -> str:
    if command_name(text):
        return "command"
    for rx, intent in _HEUR:
        if rx.search(text):
            return intent
    return "recall"  # default: it's probably a question about their world


_CLASSIFY_SYS = (
    "Classify the user's message into exactly one intent from: "
    "recall, research, code, plan, draft, automate, capture, command. "
    "'capture' = information to store (a note/task/person/idea), not a question. "
    "'command' = an explicit operational instruction to the assistant (audit, budget, reindex) "
    "— NOT a question that merely mentions those words. "
    "Reply with ONLY JSON: {\"intent\": \"...\"}."
)


async def _llm_classify(text: str) -> str | None:
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
        from ..config import settings
        opts = ClaudeAgentOptions(model=settings.model_triage, system_prompt=_CLASSIFY_SYS, max_turns=1)
        buf = ""
        async for m in query(prompt=text[:2000], options=opts):
            t = getattr(m, "text", None) or getattr(m, "content", None)
            if isinstance(t, str):
                buf += t
        intent = json.loads(buf[buf.find("{"): buf.rfind("}") + 1]).get("intent")
        return intent if intent in INTENTS else None
    except Exception:  # noqa: BLE001
        return None


def _verbosity_for(intent: str, deep: bool) -> str:
    if intent in ("research", "plan", "code"):
        return "deep"
    if deep:
        return "deep"
    if intent in ("recall", "capture", "command"):
        return "brief"
    return "normal"


async def classify(text: str) -> dict:
    intent = heuristic(text)
    # only spend a Haiku call when the fast-path defaulted (ambiguous)
    if intent == "recall":
        llm = await _llm_classify(text)
        if llm:
            intent = llm
    deep = _is_deep(text)
    difficulty = DIFFICULTY.get(intent, "triage")
    # A "recall" question with real depth deserves a smarter model than Haiku — this is what
    # makes it stop feeling like "it only ever uses Haiku" while keeping simple asks cheap.
    if intent == "recall" and deep:
        difficulty = "work"
    return {"intent": intent, "difficulty": difficulty, "essential": True,
            "verbosity": _verbosity_for(intent, deep), "command": command_name(text)}
