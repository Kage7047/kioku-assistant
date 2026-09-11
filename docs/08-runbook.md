# Runbook — from nothing to Kioku running

Goal: an empty Railway project → Kioku awake on Telegram → your first `/audit`, first captured
note, first ingested photo, and first proposed skill. ~30–45 min the first time.

Two paths: **A. Railway** (managed, recommended) or **B. Local** (`docker compose`, fastest to try).
Do B first if you just want to see it work; A when you want it always-on.

---

## 0. Before you start (have these ready)

- The **`kioku`** repo pushed to GitHub (private).
- A **second, private "vault" repo** (can be empty, or your existing Obsidian vault) — this is
  Kioku's memory, source of truth.
- **Claude Pro** subscription (for the Agent SDK credit).
- A **Telegram bot token** (below) and your **numeric Telegram user id**.
- Optional: **Langfuse** cloud keys (free tier) for traces.

### Telegram bot + your id
1. In Telegram, message **@BotFather** → `/newbot` → name it → copy the **token**.
2. Message **@userinfobot** → it replies with your numeric **id**. That locks the bot to only you.

### Subscription auth token (MODE A — bills your Pro credit, not the API)
On your machine with Claude Code installed:
```bash
claude setup-token        # prints an OAuth token: sk-ant-oat01-...
```
Keep it. **Never set `ANTHROPIC_API_KEY`** anywhere — if it's set it silently overrides and bills
pay-as-you-go.

---

## A. Deploy on Railway

### A1. Databases
- New project → **Add pgvector template** (the pgvector one, *not* plain Postgres).
- **Add Redis**.

### A2. Two services from the repo
Create two services, both pointing at the `kioku` repo, each with its **Config File Path** set:
- **api** → `railway.api.toml` (Telegram runs inside it; single instance)
- **worker** → `railway.worker.toml` (Celery + beat; owns the vault)

### A3. Volume for the vault
On the **worker** service → add a **Volume** mounted at `/vault`. (So it doesn't re-clone/re-embed
every deploy.)

### A4. Environment variables (both services unless noted)
```
CLAUDE_CODE_OAUTH_TOKEN = sk-ant-oat01-...     # subscription auth; DO NOT set ANTHROPIC_API_KEY
DATABASE_URL            = ${{Postgres.DATABASE_URL}}
REDIS_URL              = ${{Redis.REDIS_URL}}
VAULT_PATH             = /vault
VAULT_GIT_REMOTE       = https://x-access-token:<GitHub-PAT>@github.com/<you>/vault.git   # worker
VAULT_GIT_BRANCH       = main
EMBEDDING_BACKEND      = none                   # BM25-only to start
TELEGRAM_BOT_TOKEN     = <from BotFather>       # api service
TELEGRAM_ALLOWED_USER_ID = <your numeric id>    # api service
# API_BASE_URL — LEAVE UNSET on Railway. Telegram runs in-process and auto-targets
#   http://localhost:$PORT. Setting it to :8000 breaks the bot when Railway's $PORT differs.
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST   # optional
```

### A5. First deploy + database schema
- Deploy both services. Watch logs until `api` serves and `worker` is ready.
- Load the schema once (the pgvector template won't auto-run it). From Railway's Postgres
  **Query** tab or locally:
  ```bash
  psql "$DATABASE_URL" -f src/kioku/memory/schema.sql
  ```
- Health check: open the api service URL + `/health` → `{"ok": true}`.

Skip to **First contact** below.

---

## B. Run locally (docker compose)

```bash
cp .env.example .env
# edit .env: CLAUDE_CODE_OAUTH_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID,
#            VAULT_PATH=./vault  (or your Obsidian vault path), EMBEDDING_BACKEND=none
docker compose up --build
```
Schema loads automatically (mounted into the pgvector container). `GET localhost:8000/health` → ok.
The CLI works too: `kioku ask "what's in my vault?"` (after `pip install -e .`).

---

## First contact (both paths)

1. **Wake it.** In Telegram, message your bot: `/start` → "Kioku 記憶 — awake."
2. **First real job — audit the brain.** Send `/audit`. Kioku walks the vault and writes
   `_reports/audit-<date>.md` (orphans, dead links, dupes). If the vault is empty, it says so —
   that's fine.
3. **Just talk (the router decides).**
   - Capture: `remember to renew my residence card` → filed as a task card in `inbox/`.
   - Recall: `what do I know about Acme?` → grounded answer citing note paths.
   - Check spend: `/budget` → spend / remaining / mode.
4. **Feed it a photo or file.** Send a **photo** (whiteboard, receipt) or a **PDF/DOCX** as a
   Telegram document. Kioku stores an immutable copy in `sources/`, extracts text, files a note in
   `inbox/`, indexes it, and replies "📎 learned from …". (Images are stored now; text is extracted
   once you wire the vision step — see notes.)
5. **Let it get better.** After a few substantive tasks, send `propose a skill`. Kioku drafts a
   reusable skill from your recent journal into `inbox/skills/`. **Activate it** by moving that file
   into `system/skills/` (edit the vault, commit — or just move it in Obsidian). Next time a matching
   request comes in, Kioku applies the skill automatically. `/skills` lists what it's learned.

That's the whole loop live: **talk → it acts → it remembers → it proposes new skills → it watches
in the background**, all inside your Pro credit.

---

## Turn on the proactive loop (optional, once it's stable)
- The **self-metrics poller** and **deadline scanner** already run on beat. To get deadline pings,
  put `due: YYYY-MM-DD` in a note's frontmatter (e.g. your exam) — you'll get an alert when it's ≤3 days out.
- Enable the **morning brief** by uncommenting its beat entry in `worker/celery_app.py`.
- Wire real sources (gmail/sentry/vercel/indeed) by adding adapters in `worker/pollers.py` and
  flipping them to `enabled: true` in `connectors.yaml`.

## Add semantic search later (when you want it)
Set `EMBEDDING_BACKEND=openai` (or `voyage`), add `EMBEDDING_API_KEY`, keep `EMBEDDING_DIM=384`
(text-embedding-3-small right-sizes to it), then `/reindex`. Cross-lingual + paraphrase recall turns on.

---

## How fresh is recall? (data freshness)
Three paths, so it's fresher than a simple poll:
- **Kioku's own writes/ingests** (a filed note, an ingested photo, a report) → **indexed immediately**,
  event-driven (`reindex_vault_task` fires for that file right after the write). Searchable in seconds.
- **Edits from your devices** (Obsidian on laptop/iPad, synced via git) → the worker **pulls every
  10 min** (`sync_vault_task`) and now **reindexes what changed** right after the pull.
- **Nightly full reindex** (3:30am) as a safety net.

Important: with `EMBEDDING_BACKEND=none` (the default), **BM25 recall reads the files live on every
query**, so device edits are searchable the instant the 10-min pull lands them on the worker — the
pull cadence is the only latency, not an index. The reindex-after-pull matters once you turn on
embeddings (the pgvector side is a persistent store that needs refreshing). Want it snappier? Lower
the `sync-vault-10min` interval in `worker/celery_app.py`, or have Obsidian's Git plugin push on save.

## Troubleshooting
- **Billing pay-as-you-go unexpectedly** → `ANTHROPIC_API_KEY` is set somewhere. Unset it; use the OAuth token.
- **Telegram double-replies** → more than one uvicorn worker. Run the api with a single worker (default).
- **`vector` type errors** → you used plain Postgres, not the pgvector template. Recreate the DB from the template.
- **Vault changes vanish on redeploy** → `VAULT_GIT_REMOTE` unset or the worker has no volume. Set both.
- **Agent errors on the SDK call** → pin `claude-agent-sdk` and confirm `query()` / `ClaudeAgentOptions`
  signatures against the installed version; confirm model IDs.
- **Nothing recalled from the vault** → run `/reindex`; check `VAULT_PATH` points at the real vault.
