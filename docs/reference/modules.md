# Reference · Modules (file by file)

`src/kioku/`

## Entry / config
- `config.py` — all settings (`pydantic-settings`). Single source of config.
- `_compat.py` — `run_sync()` so sync Celery code can call async helpers.
- `cli.py` — terminal client (`kioku ask|audit|budget|…`) over the API.

## api/ — HTTP gateway
- `main.py` — FastAPI app; endpoints (`/health /budget /tasks /inbox /ingest /reindex /skills
  /writes /writes/{sha}/apply /tasks/{id}/stream`); embeds the Telegram bot via lifespan.
- `events.py` — Redis pub/sub → SSE relay for live run events.

## worker/ — background work
- `celery_app.py` — Celery + Beat config and the schedule (poll-all, alerts, weekly review, nightly
  reindex, 10-min vault sync).
- `tasks.py` — every task: `handle_input_task` (router entry), `run_agent_task`, `vault_audit_task`,
  `ingest_task`, `apply_write_task`, `reindex_vault_task`, `sync_vault_task`, `poll_all_task`,
  `poll_self_task`, `check_alerts_task`, `propose_skill_task`, `weekly_review_task`,
  `morning_brief_task`.
- `pollers.py` — connector→poll-function registry (`self` real; others raise until wired).
- `alerts.py` — alert rules; real deadline scanner over vault `due:` dates.

## agent/ — the brain
- `orchestrator.py` — the capped, budget-routed Agent SDK run; loads boot/persona/profile; streams events.
- `router.py` — intent classification (heuristic + Haiku fallback) → intent + difficulty.
- `capture.py` — universal capture → typed card in `inbox/`.
- `skills.py` — self-authored skill library: load/match/render skills from `system/skills/`.
- `journal.py` — decision journal after substantial runs (compounding memory).
- `ingest.py` — files/photos → immutable source copy + note + extraction (text/pdf/docx; image vision TODO).
- `tools/vault.py` — vault tools as an in-process MCP (list/read/search/write; sensitive writes → plan).
- `tools/calendar.py` — calendar stub (→ real Google Calendar MCP).

## memory/ — knowledge & state
- `vault.py` — filesystem access, BM25, deterministic audit inventory, recoverable multi-file apply.
- `retrieval.py` — hybrid BM25 + pgvector fused by RRF (graceful BM25 fallback).
- `index.py` — chunk + incrementally embed the vault into pgvector.
- `embeddings.py` — pluggable backends (none/local/openai/voyage), graceful.
- `budget.py` — rates, month-to-date spend, mode routing, **pre-flight ceiling**.
- `pending.py` — preview-then-apply-with-hash plans + draft→apply transaction (Redis-backed).
- `connectors.py` — declarative connector registry from `connectors.yaml`.
- `vaultsync.py` — git-backed vault (clone/pull/commit/push); worker-owned.
- `db.py` — async Postgres helpers (runs, signals) + sync wrappers.
- `schema.sql` — tables (runs, signals, claims, people, chunks).

## frontdoor/ — surfaces
- `telegram_bot.py` — bot handlers (commands, text→router, document/photo→ingest); `build_application()`.
- `notify.py` — fire-and-forget Telegram push (budget/deadline alerts, approvals).

## observability/
- `langfuse.py` — trace wrapper; no-op without keys.
