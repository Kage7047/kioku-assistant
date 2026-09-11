# Reference · Architecture — how Kioku works, exactly

## Components (what runs)

| Component | Process | Responsibility |
|---|---|---|
| **API + Telegram** | `uvicorn kioku.api.main:app` (single worker) | HTTP gateway, SSE streams, and the Telegram bot (embedded via FastAPI lifespan) |
| **Worker + Beat** | `celery -A kioku.worker.celery_app.app worker --beat` | Runs all agent work + scheduled loops; **owns the vault** |
| **Postgres + pgvector** | managed / container | Index & state: runs, signals, claims, people, chunks |
| **Redis** | managed / container | Celery broker + pub/sub (live events) + cache + pending plans/drafts |
| **Vault** | markdown on disk (git) | **Source of truth** for all knowledge |
| **Langfuse** | cloud (free tier) | Trace tree, tokens, latency, cost per run |

Everything is one API with many thin clients. The vault is truth; Postgres is a rebuildable index.

## Request lifecycle (a natural-language message)

```
You (Telegram / CLI / /inbox / dashboard)
   → POST /tasks {kind:"input"}  (or /inbox)
   → runs row created (status=running)
   → Celery: handle_input_task(run_id, text)
       → router.classify(text)                     # heuristic fast-path, else Haiku
           ├─ capture  → capture.triage_capture()  → note card in inbox/  (no model)
           ├─ command  → audit / reindex / budget / review / propose
           └─ recall/research/code/plan/draft/automate
                 → skills.find_matching(text)?      # a learned skill, if one matches
                 → budget.preflight(difficulty)     # estimate ceiling → allow / downgrade / refuse
                 → run_agent(): Claude Agent SDK session
                       system = BOOT (cached) + boot.md + persona.md + profile.md
                       tools  = vault (list/read/search/write) + calendar
                       cap    = max_turns; events streamed to Redis run:{id}
                 → journal.maybe_journal()          # compounding memory
   → cost recorded on the run; budget threshold → Telegram ping
   → events relayed: Redis pub/sub → GET /tasks/{id}/stream (SSE) → client
```

## The three loops (see `07-the-three-loops.md`)
- **Reactive:** router + capture + skills → act on any input.
- **Proactive:** Beat → pollers → `signals`; alert rules → `notify`.
- **Learning:** journal → propose-skill → weekly review; skills matched before the generic agent.

## Retrieval
Hybrid: **BM25** (reads vault files live every query — always fresh) fused with **pgvector**
(persistent, refreshed on write / after each git pull / nightly) via **Reciprocal Rank Fusion**.
With `EMBEDDING_BACKEND=none` it's BM25-only and still works; vectors are additive.

## Data freshness
- Kioku's own writes/ingests → **indexed immediately** (event-driven).
- Device edits (Obsidian via git) → **pulled every 10 min**, reindexed after the pull.
- **Nightly** full reindex as a safety net.

## Safety governor (applies everywhere)
Pre-flight + post-run **budget guard** · **caps** on every run (`max_turns`, timeout) ·
**approval gates** (writes outside `_reports/`,`inbox/`,`journal/`,`sources/` need `/approve`;
money/messages/bookings/PRs gated) · **allow-lists** (local runners run only registered tasks) ·
**git-versioned config** (revertible) · **never simulate a capability** (detect/degrade instead).

## Vault as truth, DB as index
Drop Postgres and lose nothing — it rebuilds from the vault via `/reindex`. The vault is plain
markdown in git, so it's portable, versioned, and editable by you and your devices independently.

## Module map
See `reference/modules.md` for a file-by-file description. Top level:
`api/` gateway+SSE · `worker/` tasks+beat+pollers+alerts · `agent/` orchestrator+router+capture+
skills+journal+ingest+tools · `memory/` vault+retrieval+index+embeddings+budget+pending+
connectors+vaultsync+db · `frontdoor/` telegram+notify · `observability/` langfuse.
