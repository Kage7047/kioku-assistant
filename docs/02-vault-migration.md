# Vault Migration — Rebuilding the Second Brain

The second brain is now the heart of the system, so its structure matters. This migration is also **Kioku's first real job** — it's bounded, high-value, and exercises the exact core (read, dedup, classify, link, write, flag stale) that every other capability depends on. If Kioku can clean the vault well, it can do the spine of everything else.

You can start **step 1 today** with an existing tool (`claude-obsidian`, MIT, local-first) before Kioku exists — it de-risks the whole rebuild.

## The design choice underneath it

Your current vault is **human-organized, AI-assisted**. Flip it to **agent-maintained**: you feed it, the agent owns structure, ledgers, and links. Borrow the schema from `claude-obsidian` / `DeepOrbit`:

- **Immutable source capture** — before synthesis, keep a content-addressed copy of every source, so a note can always be traced to its origin.
- **Source + claim ledgers** — each important claim is a record with authority, freshness, support, contradiction, confidence, review-state (see `claims` table). This is what makes contradiction/staleness sweeps possible.
- **Maps of Content (MoC)** the agent maintains, plus clean zones: `projects/`, `people/`, `areas/`, `reference/`, `sources/`, `inbox/`, `_reports/`.
- **Boot memory** — `system/boot.md`: the note Kioku loads first every session (who you are, live projects, current focus).

## Target structure

```
vault/
  system/
    boot.md              # loaded first every session
    taxonomy.md          # the rules the agent maintains structure by
  inbox/                 # raw captures land here; agent triages out
  sources/               # immutable, content-addressed source copies
  projects/              # one folder per live project (Acme, kioku, ...)
  people/                # personal CRM notes
  areas/                 # ongoing responsibilities (studies, job-search, finance)
  reference/             # durable knowledge, MoCs
  _reports/              # audit + lint + review outputs (agent-written)
```

## Migration sequence

### Step 1 — Audit (touch nothing)
Point an agent at the whole vault → produce `_reports/audit-<date>.md`:
- inventory: file count, total size, by-folder breakdown, last-modified histogram
- **orphans** (no in/out links), **dead links**, **duplicates/near-duplicates**
- **stale facts** (notes asserting things you've since changed — e.g. a dropped dependency)
- rough topic clusters
This is the P0 `vault_audit_task`. Deterministic parts (link graph, dupes, sizes) in Python; only the summary/cluster naming uses the model. Cheap.

### Step 2 — Design the target taxonomy
Write `system/taxonomy.md`: the zones above, naming conventions, what a "source", "claim", "MoC" is, and the lint rules. This is the contract the agent maintains against.

### Step 3 — Migrate, never delete
- Snapshot the old vault as an immutable archive (`git tag pre-migration` or a dated zip).
- Agent moves live content into the new zones, dedups, re-links, and for each note proposes **keep / archive / kill** → you review the batch. Nothing is lost; "kill" means move to `archive/`, not delete.

### Step 4 — Re-ingest what matters, fresh
For important sources, re-run the originals through capture→ground→connect so they get proper ledger metadata — better than importing old half-finished notes. Do this as a **Batch API** job (50% off; it's async).

### Step 5 — Lint loop (ongoing)
A recurring Beat job runs contradiction + staleness + orphan sweeps and writes `_reports/lint-<date>.md`. The vault stays healthy instead of rotting again.

## Cost note
Steps 1 and 5 are mostly deterministic Python + light Haiku summarization. Step 4 (bulk re-ingest) is the only token-heavy part — run it via the Batch API overnight. Embeddings are local, so re-indexing is free.

## Acceptance
- [ ] `audit-<date>.md` exists and is accurate (spot-check orphans/dupes against Obsidian).
- [ ] `taxonomy.md` written and agreed.
- [ ] Old vault archived immutably before any move.
- [ ] Migration produces a keep/archive/kill review batch, not silent changes.
- [ ] Lint job scheduled and writing reports.

## Retired specifics (do-not-ingest / archive, don't rebuild around)

These are dead or ephemeral — keep them as archived vault data at most, never as code,
system-prompt content, connectors, or signals sources:

- **a retired crypto trading bot** — no longer maintained.
- **a local image/video generation workflow** — retired (creative gen, if any, uses a cloud API).
- Ephemeral: current job leads, current cert enrolments, a side-gig's registration status,
  shift scheduling, active job-search tracks.

Rule: capabilities are code; specifics are data. When one dies (like these), the cost is
*not adding it* — never a code change.
