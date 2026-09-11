# Reference · Data Model

Two stores. **The vault (markdown on disk) is truth.** **Postgres is a rebuildable index** — drop
it and `/reindex` rebuilds it from the vault. **Redis** is ephemeral (queue, pub/sub, cache, pending
plans/drafts with TTL).

## Postgres (`src/kioku/memory/schema.sql`)

### `runs` — every task/agent run (history, cost, provenance)
`id, kind, status, model, input, result_path, result_text, tokens_in, tokens_out, cost_usd,
error, created_at, finished_at`. Month-to-date `cost_usd` drives the budget guard.

### `signals` — the awareness store (proactive loop)
`id, source, key, value_json, observed_at`. Filled by pollers (`self` is real; others as wired).
Read by the morning brief and reviews.

### `claims` — the claim ledger (healthy second brain)
`id, statement, source_path, confidence, freshness, contradicts_id, review_state, embedding`.
Backbone of contradiction/staleness sweeps. (Population is a Phase 1 TODO.)

### `people` — personal CRM (Phase 2)
`id, name, aliases, context, last_contact_at, notes_path`.

### `chunks` — hybrid retrieval (pgvector side)
`id (path::ordinal::hash8), path, ordinal, content_hash, text, embedding vector(384), mtime_ns,
indexed_at`. Incremental: only changed files re-embed. HNSW cosine index. `vector(N)` must equal
`EMBEDDING_DIM`.

## Vault (markdown on disk, git-versioned)

```
vault/
  system/
    boot.md         # live projects + current focus (loaded first each session)
    persona.md      # Kioku's character (loaded first; Phase 4)
    profile.md      # its model of you (loaded first; Phase 4)
    taxonomy.md     # the rules the agent maintains structure by
    skills/         # ACTIVE learned skills (matched by the router)
  inbox/            # captures land here; triaged out. Writable without approval.
    skills/         # PROPOSED skills awaiting activation (move to system/skills/)
  sources/          # immutable copies of ingested files/photos. Writable w/o approval.
  journal/          # dated decision journal (the compounding loop). Writable w/o approval.
  _reports/         # audit / brief / weekly / lint outputs. Writable w/o approval.
  projects/         # one folder per project; charter.md for autonomous ownership (Phase 4)
  people/           # CRM notes
  areas/            # ongoing responsibilities (studies, job-search, finance)
  reference/        # durable knowledge, Maps of Content
```

**Write rules:** `_reports/`, `inbox/`, `journal/`, `sources/` are writable directly. Everywhere
else a write returns a **plan + sha256** that you approve (`/approve <sha>` or `POST /writes/{sha}/apply`)
— the preview-then-apply-with-hash gate. Nothing is ever deleted.

**Frontmatter conventions:** capture cards carry `type: note|task|person|idea`; ingested files carry
`type: source, kind, origin, file, source`; a note with `due: YYYY-MM-DD` triggers the deadline alert.
