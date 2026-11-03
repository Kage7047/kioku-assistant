"""Reading cost and limits off the SDK message stream."""


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


class UsageMeter:
    """Token accounting over the SDK's message stream.

    Each AssistantMessage carries the usage of ONE API response, and Claude Code repeats that same
    usage on every content block of the response (same message_id). The terminal ResultMessage then
    reports the whole session's totals, plus the SDK's own cost. Summing everything — the old
    approach — counted each response several times and the session once more on top, so the budget
    guard over-counted spend and degraded early. Here: count each response once, and let the
    ResultMessage's totals and cost win when they arrive."""

    _KEYS = (("tokens_in", "input_tokens"), ("tokens_out", "output_tokens"),
             ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))

    def __init__(self):
        self._per_response: dict[str, dict] = {}
        self._anonymous: list[dict] = []
        self._final: dict | None = None
        self.cost_usd: float | None = None

    @classmethod
    def _read(cls, usage) -> dict:
        g = usage.get if isinstance(usage, dict) else (lambda k, d=0: getattr(usage, k, d))
        return {mine: int(g(theirs, 0) or 0) for mine, theirs in cls._KEYS}

    def observe(self, msg) -> None:
        usage = getattr(msg, "usage", None)
        is_result = hasattr(msg, "result") or hasattr(msg, "total_cost_usd")
        if is_result:
            if usage is not None:
                self._final = self._read(usage)
            cost = getattr(msg, "total_cost_usd", None)
            if isinstance(cost, (int, float)):
                self.cost_usd = float(cost)
            return
        if usage is None:
            return
        mid = getattr(msg, "message_id", None)
        if mid:
            self._per_response[mid] = self._read(usage)     # repeated blocks overwrite, not add
        else:
            self._anonymous.append(self._read(usage))

    def totals(self) -> dict:
        if self._final is not None:
            out = dict(self._final)
        else:
            out = {k: 0 for k, _ in self._KEYS}
            for u in [*self._per_response.values(), *self._anonymous]:
                for k in out:
                    out[k] += u[k]
        out["cost_usd"] = self.cost_usd
        return out
