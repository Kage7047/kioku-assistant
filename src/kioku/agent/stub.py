"""A deterministic stand-in for the Claude Agent SDK, for demos and local exploration.

With MODEL_BACKEND=stub, `run_agent` streams from this instead of `claude_agent_sdk.query`: no API
key, no subscription, no Claude Code subprocess. Everything around the model stays real — intent
routing, the budget pre-flight, hybrid retrieval over the vault, the outbound gate, the run ledger,
SSE streaming to the command center — so a visitor can see the system work end to end.

The "answer" is honest about what it is: it quotes the vault notes that retrieval found for the
question. It never pretends to reason.
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

_EXCERPT = re.compile(r'<vault_excerpt path="([^"]+)">\n(.*?)\n</vault_excerpt>', re.S)
_TOKENS_PER_CHAR = 0.25


def _answer(prompt: str) -> str:
    hits = _EXCERPT.findall(prompt)
    question = prompt.rsplit("---", 1)[-1].strip()
    if not hits:
        return ("(demo model) I found nothing in the vault for that. With a real model connected I "
                f"would research it; here I only quote notes. You asked: “{question[:200]}”")
    lines = ["(demo model — quoting the notes retrieval found; a real model would answer from them)", ""]
    for path, body in hits[:3]:
        first = " ".join(body.split())[:220]
        lines.append(f"• {path}: {first}")
    return "\n".join(lines)


def stub_query(*, prompt: str, options=None):
    """Same call shape as claude_agent_sdk.query; yields the same message shapes."""

    async def _stream():
        text = _answer(prompt)
        usage = {"input_tokens": int(len(prompt) * _TOKENS_PER_CHAR),
                 "output_tokens": int(len(text) * _TOKENS_PER_CHAR),
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        words = text.split(" ")
        step = max(1, len(words) // 6)
        for i in range(0, len(words), step):                    # stream in a few chunks
            await asyncio.sleep(0.15)
            chunk = " ".join(words[i:i + step]) + (" " if i + step < len(words) else "")
            yield SimpleNamespace(content=[SimpleNamespace(text=chunk)], message_id="stub-1", usage=usage)
        yield SimpleNamespace(content=None, result=text, total_cost_usd=0.0, usage=usage)

    return _stream()
