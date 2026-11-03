# 0004 — A pre-flight budget guard with graceful degradation

**Status:** Accepted

## Context
Kioku runs on a fixed monthly agent credit. When it is gone, requests stop, so running out is an
outage, not a bill. Agentic runs vary in cost by orders of magnitude.

## Decision
Before every run, estimate a worst-case ceiling (turns × bounded context × max output, at the
model's list price) and decide: allow, downgrade to the cheapest model, or refuse. Month-to-date
spend moves the whole system through modes — normal → conserve (no top-tier models) → Haiku-only
→ halt non-essential — and the owner is notified on each step. Owner-initiated requests keep
working in the last mode; background jobs do not.

## Consequences
- The guard deliberately over-estimates the ceiling (it ignores cache discounts), so it may refuse
  a run that would have fit. Recorded spend, by contrast, must be exact: it uses the SDK's own
  per-run cost, else a price table that includes cache reads and writes, counting each API
  response once.
- Prices live in one table that must be updated when list prices change; unknown models are
  priced as the most expensive known one.
