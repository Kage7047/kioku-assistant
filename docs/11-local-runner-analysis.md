# Local runners / Ollama triage tier — do we need it? (decision memo, 2026-08-19)

Phase 2 spec §2.3 proposes routing the "always-on nervous system" (high-volume, low-stakes
LLM calls) to a small **Ollama** model on the local machine — free while the PC is on, sparing the
$20 Agent SDK credit. This memo asks whether that's worth building. **Recommendation: skip the
Ollama triage tier; build the Claude Code hand-off instead.**

## What low-stakes calls does Kioku actually make?

| Call | Frequency | Cost today |
|---|---|---|
| Intent classification (`router._llm_classify`) | only on ambiguous input, a few/day | ~$0.001 each |
| Digest classification (`digest_note`) | ~6/batch, batched across time; one-time over the vault | ~$0.01 for the whole vault |
| **Agent asks** (the real work) | per user request | $0.02–0.15 — but **not low-stakes** |

The genuinely offloadable volume (intent + digest) already costs **pennies/month**, because the
budget guard routes it to Haiku and the pollers are deterministic (fetch→store, no LLM). The
money is spent on the **agent asks**, which need Claude quality + tools + the vault — a small
local model can't do those without visibly worse output. So Ollama would save pennies on the
cheap part and can't touch the expensive part.

## Three reasons it's the wrong optimization

1. **It solves a cost we don't have.** The offloadable calls are already ~free. The expensive
   calls aren't offloadable to a 7B local model without quality loss.
2. **"Always-on" contradicts "free while the PC is on."** The user works 200+ cashier hrs/mo;
   the local machine is off much of the time. An always-on assistant's nervous system can't depend
   on hardware that's usually asleep — so you'd need cloud fallback anyway, i.e. maintain *two*
   code paths for pennies of savings.
3. **Real added complexity:** Tailscale mesh, an outbound local Celery worker on a machine-queue,
   Ollama + a model, routing + offline-fallback logic, and ongoing maintenance — for negligible
   benefit.

## What IS worth building from §2.3: the Claude Code hand-off

The valuable half of "local hands" isn't Ollama — it's **`handoff_to_claude_code(repo, task)`**:
dispatch heavy *interactive coding* to a Claude Code session on the laptop. That draws on the
**separate interactive Pro pool, not the $20 Agent SDK credit**, so real coding work doesn't
touch Kioku's budget — at full Claude quality, and only when the user initiates it (no always-on
requirement). This saves real money on the genuinely expensive part.

## Cheaper levers to reach for first (all already in hand)

Before any hardware: the budget guard + Haiku defaults + **intent-based tool narrowing** (built
2026-08-19) + prompt caching + batching. Exhaust these; they cover the cost concern without a
second platform.

## If local compute is ever wanted

A local runner still makes sense for a *different* need — tasks that require the local filesystem
(e.g. `index_repo` over local code, processing local files) — as an **optional, use-case-gated
capability**, not a standing triage tier. Build it when a concrete need appears, behind the same
allow-list + draft→apply safety the vault already uses.

**Bottom line:** don't build the Ollama tier. Keep the $20 defended by the software levers we
already have, and put "local hands" effort into the Claude Code hand-off when we want it.
