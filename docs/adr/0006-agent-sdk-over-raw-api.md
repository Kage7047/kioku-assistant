# 0006 — The Claude Agent SDK rather than a hand-written tool loop

**Status:** Accepted

## Context
Kioku needs an agent loop with tools, MCP servers, sub-agents, permission callbacks and
web search, and it bills a subscription's agent credit rather than a metered API key.

## Decision
Use the Claude Agent SDK (`query()` + `ClaudeAgentOptions`) for the loop. Kioku owns what is
specific to it: routing and difficulty tiers, the budget guard, the outbound gate, memory and
retrieval, and the tools over its vault.

## Consequences
- No loop, retry or context-management code to maintain; sub-agents and MCP come for free.
- The SDK surface moves, so it is pinned to a tested minor range and its message shapes are
  covered by the scripted model in `tests/fakes.py`.
- Built-in filesystem and shell tools are removed from every run: Kioku's filesystem is the
  vault, reached only through its guarded tools.
