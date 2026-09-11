# QUICKSTART — your first start (deploy → import → live)

The single narrative for standing Kioku up the first time and feeding it your exports. Deeper detail
in `08-runbook.md`, `reference/ingesting-at-scale.md`, `reference/connecting.md`. Your guardrails and
persona are already decided and shipped in `vault/system/` — you don't re-decide them here.

## Scope your first night (don't do everything)
- **Night one:** deploy empty → confirm it breathes → bulk-import your exports → verify recall.
- **This week:** wire Google Calendar, GitHub, the read-only DB. Author the real `boot.md` blanks.
- **Later:** more connectors, semantic search, the bank aggregator, the dashboard, Phase 4.

---

## 1. Clean vault repo
```bash
mkdir kioku-vault && cd kioku-vault && git init
mkdir -p system inbox sources journal _reports _import reference
```
Copy the shipped `kioku/vault/system/` files (`boot.md`, `persona.md`, `profile.md`) into `system/`.
Edit `boot.md`'s `(edit)` blanks (Acme milestone). Commit → push to a **private** GitHub repo.
That URL = `VAULT_GIT_REMOTE`.

## 2. Curate exports into `_import/`
Put only what you actually want it to learn here — **not** your whole outdated old vault (that
reintroduces the stale data you're leaving behind).
- Markdown/text → dropped in as-is (filed into `reference/imported/`, structure preserved, searchable instantly).
- PDF/DOCX/CSV → text extracted, original kept in `sources/`.
- ChatGPT/Claude export → convert `.json`/`.html` to md/txt first.
- Images → stored now; text once vision is wired.
Commit → push (large exports ride the vault repo, not chat — no size limit).

## 3. Deploy empty (Railway)
Follow `08-runbook.md`: pgvector template + Redis + **api** and **worker** services (each with its
`railway.*.toml`), worker volume at `/vault`, run `schema.sql` once, set env
(`CLAUDE_CODE_OAUTH_TOKEN` — never `ANTHROPIC_API_KEY`; `VAULT_PATH=/vault`; `VAULT_GIT_REMOTE`;
`EMBEDDING_BACKEND=none`; Telegram token + your user id). Confirm `/health` → ok, `/start` replies.

## 4. Bulk import
```
kioku import          # or POST /bulk-ingest, or tell it in Telegram
```
Files markdown, extracts documents, indexes once, pushes. **No model cost.** It pings you with counts.

## 5. Verify
Ask something you know is in there: *"what do I have on Acme?"* BM25 reads live from disk, so if
the file's there, it's found.

## 6. Study selectively (optional — this is the part that costs tokens)
- `/audit` → inventory (orphans, dupes, clusters).
- *"organize reference/imported and flag anything stale"* → proposes moves/merges (gated).
- *"summarize everything about &lt;topic&gt; into one note"* → synthesis on demand.
Store everything; study only what you'll use. Big passes → run overnight as Batch jobs.

## 7. Wire the first connectors (this week)
Per `reference/connecting.md`: **Google Calendar** (MCP tool — you'll need a calendar MCP server +
token; the claude.ai "Connect" button authorises the app, not the headless worker), **GitHub**
(fine-grained read-only PAT + `GITHUB_REPOS`), **DB** (a read-only Postgres role + your named
queries). Flip `enabled: true`, restart the worker, confirm signals land / the morning brief fills.

## Decided already (shipped — for reference)
- **Prepares, never commits:** never sends a message, spends money, or opens a PR/touches `main` without your tap.
- **Auto-capture:** files notes silently, tells you later; edits to existing notes still gated.
- **Reads all**, flags financial/health as sensitive. **Proactivity ~2.5/3.** Morning brief **on** (07:00).
- **Bank:** read-only, no transfer code exists. **DB:** SELECT-only, three enforced layers.

## Nothing to fear losing
The vault is git (durable in GitHub); Postgres is a rebuildable index (`/reindex` rebuilds it). You
can wipe and redeploy freely — your knowledge lives in the vault repo, not on Railway.
