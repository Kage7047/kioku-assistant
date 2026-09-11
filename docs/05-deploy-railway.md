# Deploy on Railway

Railway fits this well: unlike Vercel it runs **persistent containers**, so the long-running
Celery worker/beat are fine. You already pay for it, and it removes most ops (managed Postgres
+ Redis, scheduled backups, deploy-on-push, logs/metrics/rollbacks, no OS patching). Two things
change vs a VPS — both handled in the scaffold.

## Services (one project)

| Service | Source | Start command |
|---|---|---|
| **postgres** | pgvector **template** (not default Postgres) | — |
| **redis** | Railway Redis | — |
| **api** (Telegram runs inside it) | this repo (Dockerfile) | `uvicorn kioku.api.main:app --host 0.0.0.0 --port $PORT` |
| **worker** (+ beat) | this repo (Dockerfile) | `celery -A kioku.worker.celery_app.app worker --beat` |

Services talk over Railway's private network; set `DATABASE_URL`/`REDIS_URL` from the DB/Redis
service variables. To save usage you can fold telegram into the api service later.

**Config-as-code:** the repo ships `railway.api.toml` and `railway.worker.toml`. Create two services from this repo and set each service's
*Config File Path* to the matching file (Settings → Config-as-code). Build + start command +
health check come from the file, so there's nothing to click per deploy.

## The two adaptations (already in the code)

### 1. pgvector — use the template, not default Postgres
Railway's standard Postgres image ships **without** pgvector; deploy the one-click **pgvector
template** instead. `schema.sql` then runs `CREATE EXTENSION vector` as normal.

### 2. Vault = git-backed, worker-owned
Railway containers are ephemeral and a volume attaches to a single service, so the markdown
vault can't just be a shared local dir. Fix (built in): the vault is a **private git repo**.
- Set `VAULT_GIT_REMOTE=https://x-access-token:<PAT>@github.com/<you>/vault.git` and
  `VAULT_GIT_BRANCH=main`.
- The **worker** owns the checkout (attach a small Railway **Volume** at `VAULT_PATH` so it
  doesn't re-clone/re-embed every deploy). It pulls device edits, and pushes after every write
  (`sync_vault_task` every 10 min + push-after-write). Your Obsidian devices sync the same repo
  (Obsidian Git plugin) — so it's more portable than a VPS dir, not less.
- All vault **mutations** now go through the worker: `/writes/{sha}/apply` enqueues
  `apply_write_task` instead of writing in the API process, so only the worker needs the volume.

## Embeddings — three ways, pick one (it's now a config flip)
`memory/embeddings.py` is pluggable via `EMBEDDING_BACKEND`:

- **`none` — do it all without embeddings.** Retrieval is BM25-only. Zero cost, zero infra,
  works today. You lose semantic/paraphrase matching, **cross-lingual** recall (a multi-language
  vault), and the dedup/contradiction sweeps (which need vectors). Perfectly fine for v1.
- **`openai` / `voyage` — hosted API (recommended on Railway).** CPU-only friendly, pennies/mo.
  A full re-embed of a personal vault is a few million tokens = cents; incremental is negligible.
  Set `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` (e.g. `text-embedding-3-small` with `EMBEDDING_DIM=384`,
  which right-sizes to match the schema, or `voyage-3.5-lite`), and for OpenAI-compatible providers
  `EMBEDDING_API_BASE`.
- **`local` — sentence-transformers.** Free + private, but **don't run it on Railway** (torch needs
  ~1.5–2 GB RAM = the priciest thing on the box). Run it on a **local-machine runner** (Phase 2) that
  writes vectors into Railway Postgres — best cheap+private option once runners exist.

Whatever you pick, `EMBEDDING_DIM` must equal the `vector(N)` column in `schema.sql`. Switching
backend/dim = change both, then `/reindex`. If embeddings ever fail, retrieval silently falls back
to BM25 — search never breaks.

## Local runners
Runners connect to Railway's **Redis over its TCP proxy** (public endpoint + strong password)
instead of Tailscale-to-VPS. Same outbound, allow-listed-tasks pattern.

## What it actually costs
Railway bills **~$10/GB-month RAM, ~$20/vCPU-month, ~$0.05–0.10/GB egress**, on top of your plan's
included usage (Hobby $5 includes $5; Pro $20 includes $20). RAM you *hold* continuously is the
driver; a personal assistant is idle most of the time, so vCPU stays low.

Calibrated against a real Railway app of the **same shape** (Acme: api + celery + beat +
redis + pgvector Postgres) that runs at **~$6-7/mo**. Kioku's base stack is the same, so it
lands in the same range:

| Service | ~RAM held | ~$/mo |
|---|---|---|
| postgres+pgvector | ~0.25 GB | ~$2.5 |
| redis | ~0.1 GB | ~$1 |
| api | ~0.15 GB | ~$1.5 |
| worker+beat (no torch) | ~0.2 GB | ~$2 |
| telegram (or fold into api → $0) | ~0.15 GB | ~$1.5 |
| vault volume + egress | small | ~$0.5 |
| **total usage** | **~1.0 GB** | **~$7-9/mo** |

The **only** thing that changes this picture is running the **local embedding model (torch)**
on Railway: it holds ~1.5-2 GB continuously → **+$15-20/mo**, which is where my earlier "$17+"
came from. Acme doesn't do this, and neither should Kioku — keep `EMBEDDING_BACKEND` at
`none`/`openai`/`voyage` and the footprint stays at Acme levels.

Separately: the ~$20 Anthropic **Agent SDK credit** is your *subscription*, not Railway infra —
don't add it to the hosting bill (Acme's Claude API calls are billed separately too).

Old (over-padded) estimate for reference — ignore:
Estimated held-RAM for this stack kept **lean (embeddings off Railway)**:

| Service | ~RAM held | ~$/mo |
|---|---|---|
| postgres+pgvector | ~0.5 GB | ~$5 |
| redis | ~0.25 GB | ~$2.5 |
| api | ~0.25 GB | ~$2.5 |
| worker+beat (no torch) | ~0.4 GB | ~$4 |
| telegram (or fold into api) | ~0.2 GB | ~$2 |
| volume + egress | small | ~$1 |
| **total usage** | **~1.6 GB** | **~$17/mo** |

**Bottom line:** with embeddings hosted or off, Kioku costs about what Acme costs — roughly
**$7-9/mo**, largely inside your Pro plan's included $20. Hetzner would be ~€5 flat, but you already
have Railway. The one bill-tripler to avoid is torch-on-Railway. Langfuse stays free; a future
Next.js dashboard can go on Railway or Vercel.

## Env checklist (Railway variables)
`ANTHROPIC` auth (MODE A: `CLAUDE_CODE_OAUTH_TOKEN`, no `ANTHROPIC_API_KEY`) ·
`DATABASE_URL` · `REDIS_URL` · `VAULT_PATH=/vault` · `VAULT_GIT_REMOTE` · `VAULT_GIT_BRANCH` ·
`TELEGRAM_BOT_TOKEN` · `TELEGRAM_ALLOWED_USER_ID` · `API_BASE_URL` (internal api URL) ·
`LANGFUSE_*`.
