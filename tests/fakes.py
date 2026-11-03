"""A scripted stand-in for `claude_agent_sdk.query`.

The orchestrator only reads messages through getattr (`.content` blocks with `.text`, `.result`,
`.usage`), so plain namespaces reproduce the SDK's stream shape without a network call, an API key
or a Claude Code subprocess. Each test scripts exactly what "the model" says and how many tokens
it reports, which makes runs deterministic and free.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace


_ids = iter(range(1, 1_000_000))


def text(t: str, *, tokens_in: int = 0, tokens_out: int = 0, message_id: str | None = None,
         **cache) -> SimpleNamespace:
    """An AssistantMessage carrying one TextBlock. Each call is its own API response unless a
    message_id is shared (Claude Code repeats a response's usage on each of its blocks)."""
    return SimpleNamespace(content=[SimpleNamespace(text=t)], message_id=message_id or f"msg_{next(_ids)}",
                           usage=_usage(tokens_in, tokens_out, **cache) if tokens_in or tokens_out else None)


def result(r: str = "", *, tokens_in: int = 0, tokens_out: int = 0, cost: float | None = None,
           **cache) -> SimpleNamespace:
    """The terminal ResultMessage: session totals and the SDK's own cost."""
    return SimpleNamespace(content=None, result=r, total_cost_usd=cost,
                           usage=_usage(tokens_in, tokens_out, **cache))


def _usage(tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0) -> dict:
    return {"input_tokens": tokens_in, "output_tokens": tokens_out,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}


class FakeQuery:
    """Callable replacing `query(prompt=..., options=...)`. Records every call it receives."""

    def __init__(self, *messages, raise_after: BaseException | None = None, hang: bool = False):
        self.messages = list(messages)
        self.raise_after = raise_after
        self.hang = hang
        self.calls: list[dict] = []

    def __call__(self, *, prompt, options):
        self.calls.append({"prompt": prompt, "options": options})
        return self._stream()

    async def _stream(self):
        for m in self.messages:
            yield m
        if self.hang:
            await asyncio.sleep(3600)
        if self.raise_after is not None:
            raise self.raise_after

    @property
    def last_options(self):
        return self.calls[-1]["options"]

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]["prompt"]


class RecordingOptions:
    """Replaces ClaudeAgentOptions so tests can assert on exactly what a run was configured with."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __getattr__(self, name):
        try:
            return self.kwargs[name]
        except KeyError as e:
            raise AttributeError(name) from e
