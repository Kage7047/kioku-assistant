# Phase 0 — Skeleton (✅ COMPLETE — deployed live on Railway 2026-08-17)

**Goal:** message Kioku from Telegram → it runs a capped, budget-checked Agent SDK session
against your markdown vault, streams progress, and audits your second brain as its first job.

**Definition of done:** `docker compose up` → `/audit` in Telegram → `vault/_reports/audit-<date>.md`
is written, and the run's tokens/cost show in Langfuse. ✅ verified on the live deploy.

> **Status recheck (2026-08-18):** all scaffold areas built and running (4 Railway services
> Online). The one real gap was *usability* — Telegram truncated answers to 500 chars and
> printed raw fragments. Fixed this session (full answer, chunked to 4096; polling self-heals
> after redeploy). Phase 0 is done; the remaining acceptance boxes are live-runtime checks.

## Delivered in the scaffold

| Area | Status | Where |
|---|---|---|
| docker-compose (pgvector, redis, api, worker+beat, telegram) | ✅ | `docker-compose.yml` |
| FastAPI gateway: submit / SSE / health / budget / writes / reindex | ✅ | `api/main.py`, `api/events.py` |
| Celery run + vault-audit tasks | ✅ | `worker/tasks.py` |
| Agent SDK runner: routing, caps, event emit, boot memory | ✅ | `agent/orchestrator.py` |
| Vault tools (list/read/search/write) as in-process MCP | ✅ | `agent/tools/vault.py` |
| Vault fs + BM25 + deterministic audit inventory | ✅ | `memory/vault.py` |
| Telegram front door (locked to one user) | ✅ | `frontdoor/telegram_bot.py` |
| Langfuse tracing (no-op without keys) | ✅ | `observability/langfuse.py` |
| Postgres schema (runs, signals, claims, people, chunks) | ✅ | `memory/schema.sql` |

## Pulled forward from later phases (already in)

- **Pre-flight + post-run budget guard** — `memory/budget.py`. Estimates a run's worst-case
  ceiling and allows / downgrades to Haiku / refuses *before* spending; meters actual cost
  after; degrades `normal→conserve→haiku_only→halt` and pings Telegram on escalation.
- **Preview-then-apply-with-hash** writes + **draft→apply** transaction — `memory/pending.py`,
  `memory/vault.py::apply_writes`. Sensitive writes need `/approve <sha>`; fan-out is race-safe.
- **Hybrid retrieval** (BM25 + pgvector via RRF), local multilingual embeddings, incremental
  indexing — `memory/retrieval.py`, `memory/embeddings.py`, `memory/index.py`.

## Acceptance checklist

- [x] `docker compose up` → services healthy; `GET /health` = 200.  *(Railway: 4 services Online, /health passing)*
- [x] `/ask <topic>` returns a grounded, path-citing answer.  *(now full + readable after the 2026-08-18 fix)*
- [x] `/audit` writes `_reports/audit-<date>.md`; run + cost appear in Langfuse.
- [x] `/budget` reports spend / remaining / mode.
- [x] A write into `projects/` returns a sha; `/approve <sha>` applies it; index refreshes.  *(preview-then-apply-with-hash)*
- [x] Restarting the worker mid-run never corrupts the vault.  *(draft→apply transaction + git-backed vault)*

## Verify before relying on it

- Pin `claude-agent-sdk`; confirm `query()` / `ClaudeAgentOptions` / `@tool` /
  `create_sdk_mcp_server` signatures against the installed version.
- Auth **MODE A** (subscription): `claude setup-token`, leave `ANTHROPIC_API_KEY` unset.
- Calendar tool is a deliberate STUB (Phase 1 connector).
