# Phase 1 — Daily-useful + subscription-safe (✅ COMPLETE — 2026-08-18)

**Goal:** Kioku becomes something you actually use every day, and stays comfortably inside
the ~$20 Agent SDK credit. This is where the awareness layer, real memory, and the hybrid
knowledge index come alive.

> **Status recheck (2026-08-18), verified against code:** Phase 1 is functionally complete.
> Done: auto-journal wired, morning-brief Beat entry live, real pollers (self/vercel/sentry/
> github/db/bank), web research on the real built-in tools, **digest+connect ingestion**
> (`agent/digest.py`), **conversation continuity**, and the **claim ledger** (population folded
> into digest + nightly `claim_sweep_task`). **Not blocking; accounted for:** (1) embeddings are
> wired but OFF by choice — one env flip completes hybrid retrieval (see below); (2) calendar
> stays a stub because real Google Calendar is served by the Composio MCP router; (3) prompt-
> cache hit verification needs a live Langfuse look; (4) the Anthropic **Batch API is
> intentionally skipped** — it requires a metered `ANTHROPIC_API_KEY`, which contradicts the
> chosen Mode-A (subscription-only) billing; (5) gmail/indeed pollers → gmail is covered by the
> Composio MCP, indeed has no usable API.
>
> **Adopted from Kioku-repo research (khoj, rezaulhreza/kioku) — validated our design, two
> upgrades queued for Phase 2:** (a) **intent-based tool narrowing** — send only the 3-8 tools
> relevant to the intent instead of all of them every run (fewer input tokens = cheaper);
> (b) **semantic history retrieval** — once embeddings are on, recall *relevant* past exchanges,
> not just the last N (we do recency now).

## Scope

### A. Knowledge & memory (mostly scaffolded)
- **Hybrid retrieval live** — BM25 + pgvector fused by RRF. ✅ code in; needs the embedding
  model installed + a first `/reindex`.
- **Incremental indexing** — only changed files re-embed (mtime + hash). ✅ `memory/index.py`.
  Auto-reindex fires after any vault write. ✅
- **Boot memory** — `system/boot.md` loads first every session (live projects, current focus).
  ✅ loaded by the orchestrator; you author the file.
- **Episodic memory = decision journal → vault.** After a substantive run, Kioku writes a
  dated note (rationale, outcome) into the vault; it gets indexed, so "what did we decide about
  X" becomes a normal hybrid search. ✅ `journal.maybe_journal` wired into `handle_input_task`.
- **Digest + connect ingestion** ✅ (new 2026-08-18) — `agent/digest.py`: deterministic index/MAP
  rebuild (kills orphans) + batched Haiku enrichment (summary/type/tags/[[links]]) + nightly
  `self_heal_task`. Imports are now understood and connected, not dumped.
- **Claim ledger population** ✅ (2026-08-18) — claims are extracted in the *same* Haiku call as
  digestion (near-free) into the `claims` table with `confidence/freshness/source_path`.
  `claim_sweep_task` (nightly): marks stale claims, and — once embeddings are on — finds
  near-duplicate/contradicting pairs via pgvector (`memory/claims.py`), writing
  `_reports/claim-review-<date>.md`. `backfill_embeddings` lights up older claims after the flip.

### B. Awareness layer (framework scaffolded)
- **Declarative connectors** — `connectors.yaml` lists sources; enabling one is a config edit.
  ✅ loader in `memory/connectors.py`.
- **Signals store** — normalized `signals` table + `record_signal`/`recent_signals`. ✅
- **Self poller** — records Kioku's own spend/mode over time (real, no external API). ✅
  hourly via Beat.
- **Morning brief** — non-essential background run that summarizes recent signals and pushes
  to Telegram; pauses itself when the budget is tight. ✅ task in + Beat entry `brief-daily` live.
- **Real source pollers** — ✅ real adapters for self/vercel/sentry/github/db/bank (each raises
  cleanly until its token is set — never fake data). ⏳ gmail/indeed still to add.

### C. Connectors & research
- **Calendar** — ⏳ still the deliberate stub in `agent/tools/calendar.py`. Real Google Calendar
  is available via the Composio MCP router (memory), so the native stub is low-priority.
- **Web research** — ✅ real: `WebSearch`/`WebFetch` built-ins are allowed in the orchestrator
  (no extra key, billed on the SDK credit). No fake search tool shipped.

### D. Cost hardening (mostly in)
- Pre-flight ceiling + post-run metering + graceful degrade. ✅
- BM25 index cached (was rebuilt from every file on every query). ✅ (2026-08-18)
- **Prompt caching** — static persona prefix kept constant; `boot.md` loaded separately so the
  prefix stays cacheable. ✅ structured for it; ⏳ TODO: confirm cache hits in Langfuse.
- Batch API for the nightly lint + bulk re-ingest during migration. ⏳ TODO.

## Acceptance checklist
- [ ] `/reindex` builds the pgvector index; a paraphrased/cross-lingual query beats BM25-only.  *(blocked only on turning embeddings on)*
- [x] `system/boot.md` visibly shapes answers.  *(loaded first every session by the orchestrator)*
- [x] Substantive runs leave a dated decision-journal note that's later retrievable.  *(`journal.maybe_journal`)*
- [x] Enabling a connector in `connectors.yaml` starts producing signals with no code change.  *(loader + poller registry)*
- [x] Morning brief lands in Telegram and pauses itself under `conserve`+ budget modes.  *(task + Beat entry + budget gate)*
- [ ] Langfuse shows cache hits on the stable prefix.  *(needs live verification)*
