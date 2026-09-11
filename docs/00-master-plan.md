# Kioku (記憶) — Complete Plan

> A private, self-owned agentic personal assistant. Cloud brain, local hands. The second
> brain is the heart. Runs on your Pro subscription's Agent SDK credit. Cheap by design.

This is the top-level plan. **Full documentation index: `docs/INDEX.md`** (architecture, commands, API, config, data model, capabilities, modules, all phases).

---

## 1. What it is

A single-user assistant that **remembers** (owns a markdown vault + Postgres state), **acts**
(an orchestrator spawns sub-agents for coding, research, planning, automation), is **reachable
everywhere** (Telegram, a web command center, Claude Code/Cowork hand-offs), and **stays cheap**
(tiered models, caching, deterministic-Python, hard caps, a self-budget-guard).

Stance: **adopt before build.** Claude Agent SDK for the loop, Langfuse for observability,
Obsidian for the graph, khoj/claude-obsidian patterns for the vault. You build the glue that's
genuinely yours: orchestration, memory, connectors, and the meta-cognition layer.

## 2. Reality checks that shaped it

- No API reads your claude.ai chats out → Kioku owns its memory; you route work *through* it.
- Multi-agent fan-out is ~15× the tokens of a chat → tiering + caps + the budget guard.
- Real-world booking has no universal API → human-in-the-loop confirm.
- Observability self-hosting is heavy now (ClickHouse) → Langfuse cloud free tier.
- **Billing:** since 2026-06-15 a personal Agent-SDK app can bill your **subscription's
  monthly Agent SDK credit** (~$20 Pro). That $20 is a hard wall → it's a design constraint.

## 3. Architecture

```
   Telegram (async)   Web command center (live runs, approvals, graph)   Claude Code/Cowork
          \                        |                                          (interactive Pro pool)
           \                       | HTTP + SSE
            \             ┌────────▼────────┐
             ───────────► │  FastAPI gateway │  submit · stream · budget · writes · reindex
                          └────────┬─────────┘
                     Redis (broker + pub/sub + cache)
                          ┌────────▼─────────┐
                          │  Celery workers   │  Agent SDK · routing · caps · budget guard
                          │   + Beat (pollers)│  orchestrator → sub-agents (draft→apply)
                          └──┬─────────────┬──┘
              ┌──────────────▼──┐   ┌──────▼───────────┐     ┌──────────────────────────┐
              │ Postgres+pgvector│   │ Markdown vault    │     │ Local runners (Tailscale) │
              │ runs·signals·    │   │ (git) SOURCE OF   │     │ local machine / laptop:        │
              │ claims·people·   │   │ TRUTH · BM25 +    │     │ ollama triage · repo work ·│
              │ chunks           │   │ pgvector (hybrid) │     │ Claude Code hand-off       │
              └──────────────────┘   └───────────────────┘     └──────────────────────────┘
   Observability: Langfuse (cloud free) — trace tree, tokens, latency, cost per step.
```

## 4. Stack (decided)

Python 3.12 · **Claude Agent SDK** (orchestration) · **FastAPI** (gateway) · **Celery+Beat**
on **Redis** · **Postgres 16 + pgvector** · markdown vault on disk (git) · **hybrid BM25 +
pgvector** with **local multilingual embeddings** · **MCP** connectors · **Telegram** (in the API process) + **CLI** + thin **Next.js** dashboard · **Langfuse** cloud · **Railway** (persistent containers, managed pgvector + Redis) — or docker-compose on Hetzner ·
local **Celery runners over Tailscale**.

## 5. Billing & cost model (subscription-locked)

- Bills the **Pro Agent SDK credit (~$20/mo, standard API rates, no rollover)** via subscription
  OAuth (`claude setup-token`); `ANTHROPIC_API_KEY` stays unset (setting it silently overrides
  and bills pay-as-you-go). Interactive Code/Cowork hand-offs use the **separate** Pro pool.
- **Fable is off the table** for routine use ($10/$50); Opus sparingly; Sonnet for work; Haiku
  default. Route by difficulty, never a fixed tier.
- **Self-budget-guard** (built): pre-flight ceiling estimate → allow / downgrade to Haiku /
  refuse *before* spending; post-run metering; degrade `normal→conserve→haiku_only→halt`; ping
  Telegram on escalation. `/budget` shows spend/remaining/mode.
- Levers by impact: prompt caching → deterministic-Python → routing → hard caps → batch API →
  local embeddings + vault-as-cache → optional local Ollama triage.
- **Hosting: Railway** (you already pay for it; less ops than a VPS) with a **git-backed, worker-owned vault** and the **pgvector template**; embeddings offloaded to a local runner or a hosted API since Railway is CPU-only. Flat-price Hetzner stays the cheap alternative. See `docs/05`.

## 6. Knowledge & retrieval

Files are truth (markdown, git); Postgres is a rebuildable index. Retrieval is **hybrid**:
BM25 for exact terms/identifiers, pgvector for meaning + **cross-lingual** recall (multiple
languages in one semantic space), fused by RRF. Embeddings also unlock near-duplicate detection and
contradiction/staleness sweeps that BM25 can't do. The vault is **agent-maintained** (source +
claim ledgers, Maps of Content, boot memory); rebuild plan in `02-vault-migration.md`.

## 7. Safety non-negotiables

- **Files are truth.** Drop the DB, lose no knowledge.
- **Cap every run.** No uncapped loops. Pre-flight + post-run budget guard.
- **Guard the credit.** Degrade gracefully; never die mid-task.
- **Allow-list capabilities.** No deletes; writes outside `_reports/`/`inbox/` need `/approve`;
  money/messages/bookings hit a gate; local runners run only registered tasks.
- **Draft→apply for fan-out.** Sub-agents never write; the orchestrator commits one recoverable
  transaction.
- **Capabilities are code; specifics are data.** Dead things (retired bots, old workflows) cost *not
  adding a line to `connectors.yaml`* — never a code change.
- **Never simulate a capability.** Detect, degrade, or say so.

## 8. Build status  *(updated 2026-08-20)*

**Phases 0, 1, 1.5, 2 — done and live. Phase 3 (Agency — `docs/13`) — core done and live**
(event-driven alerts, weekly self-education, acting-with-the-gate, meta-cognition, self-scheduling,
system-file enforcement + cache verification). Remaining in 3: **mobile/Telegram UX** (formatting +
send files/links), **Claude Code hand-off** (heavy coding + local-file curation), extra interfaces.
Sub-agent fan-out 🅿️ backlog (raises usage). Phase 4/5 not started (by design).

| Component | Phase | Status |
|---|---|---|
| Skeleton (compose, API+Telegram, worker, vault tools, audit) | 0 | ✅ live |
| Budget guard: pre-flight + degrade + notify + per-difficulty turn caps | 0/1 | ✅ live |
| Vault write safety: hash-gate + draft→apply | 0/2 | ✅ live |
| Hybrid retrieval (BM25+pgvector RRF) + embeddings + incremental index | 1 | ✅ live (embeddings ON) |
| Retrieval-augmented prompting (pre-inject context → 1-turn answers) | 1 | ✅ live |
| Boot memory + operating playbook, connectors, self-poller, morning brief, CLI | 1 | ✅ live |
| Intent router (precise commands + complexity routing) + capture + journal | 1.5 | ✅ live |
| Proactive loop: poller registry + alert engine (deadline scanner) | 1.5 | ✅ live |
| Real pollers (vercel/github/db) + web research (WebSearch/WebFetch) | 1 | ✅ live |
| Gmail/Calendar/Drive via Composio MCP; proactive brief scans them | 1 | ✅ live |
| Learning loop: skill library + propose-skill + weekly review | 1.5 | ✅ live |
| On-the-fly ingestion (files/photos → brain) Telegram + web upload + /ingest | 1.5 | ✅ live |
| Claim ledger: extraction + nightly contradiction/staleness sweep | 1 | ✅ live |
| Command center (same-origin SPA: runs, approvals, graph, budget, upload) | 2 | ✅ live |
| People-CRM (upsert/dedup, folded into digest) | 2 | ✅ live |
| Digest/connect engine (map + summaries + [[links]], loop-safe) | 1.5 | ✅ live |
| Soft on/off switch (pause/resume: Telegram + dashboard + API) | 2 | ✅ live |
| Usage-limit surfacing + never-silent skips | 1 | ✅ live |
| Persona seed + operating playbook (loaded first) | 3 | ✅ live |
| Opportunity radar (job scout: boards → fit-score vs CVs) | 2 | ✅ live |
| Event-driven alerts (deploy down/recovered, spikes, new PRs) | 3 | ✅ live |
| Self-education: weekly model-of-you pass (draft-gated profile) | 3 | ✅ live |
| Acting-with-the-gate: apply-to-role + contact-prep skills | 3 | ✅ live |
| Meta-cognition: weekly self-review of own runs + skill maturation | 3 | ✅ live |
| Self-scheduling: Kioku sets its own cron tasks (vault-backed) | 3 | ✅ live |
| System-file enforcement (binding) + prompt-cache verification | 3 | ✅ live |
| Mobile/Telegram UX: rich formatting, send links + files | 3 | ⬜ next |
| Sub-agent fan-out + aggregate budget cap | 2 | 🅿️ backlog (raises usage — user parked 2026-08-20) |
| Local runners (Tailscale) + Ollama triage | 2 | ⏭️ skipped (docs/11 — optimizes pennies) |
| Claude Code hand-off (heavy coding + LOCAL file curation) | 3 | ⬜ next (user parked to "later") |
| Drive file curation (read/create/edit/organise via Composio) | 3 | ✅ live |
| Autonomous project ownership; computer-use hands | 4 | ⬜ later |
| Voice + ambient | 5 | ⬜ later |

## 9. Roadmap

- **Phase 0 — Skeleton (done).** `docs/01`. First job: the vault audit.
- **Phase 1 — Daily-useful + subscription-safe.** `docs/03`. Hybrid live, awareness layer,
  episodic memory, real connectors, cache hardening.
- **Phase 2 — The multiplier.** `docs/04`. Command center, intent narrowing, CRM, radar, on/off switch. (Sub-agent fan-out parked — raises usage.)
- **Phase 3 — Agency (core done).** `docs/13`. Event-driven alerts · weekly self-education (model-of-you, draft-gated) · acting-with-the-gate (draft applications/replies, auto calendar) · meta-cognition (self-review) · **self-scheduling** (its own cron tasks) · system-file enforcement + cache verification. **Remaining:** mobile/Telegram UX (rich formatting + send files/links), Claude Code hand-off (heavy coding + local-file curation), extra interfaces.
- **The three loops (reactive/proactive/learning):** `docs/07`.
- **Interfaces & universality plan:** `docs/06` (CLI ✅, Obsidian-inbox, iOS Shortcut, webhooks; and the capture→route→state→skills backbone that makes it universal).
- **Phase 4 — Agency & Character (next version).** `docs/09`: persona (seeded), model-of-you,
  intelligent proactivity, self-improvement, **local coding agent** (Claude Code hand-off + runner
  dev tasks), autonomous project ownership, computer-use hands. All behind the same governor.
- **Phase 5 — Presence (later).** `docs/10`: voice (wake word, STT/TTS) + ambient (Home Assistant).

## 10. Immediate next actions

1. Railway project: pgvector template + Redis + api/worker/telegram services; or Hetzner + `docker compose up`. `claude setup-token` (MODE A auth). See `docs/05`.
2. Point `VAULT_PATH` at a **copy** of your vault; run `/audit`; read the report.
3. Install `sentence-transformers`, `/reindex`, confirm hybrid beats BM25 on a paraphrased query.
4. Author `system/boot.md` (live projects, current focus).
5. Do the vault migration (`docs/02`) as Kioku's first real job.
6. Full step-by-step in **`docs/08-runbook.md`** (empty Railway project → first `/audit` → photo → proposed skill).
7. Then Phase 1 TODOs → Phase 2.
