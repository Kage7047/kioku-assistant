# Reference · Feeding it a lot of data (new vault + exports)

## The distinction that matters: STORE vs STUDY
- **Store** = get the data into the brain so it's *searchable*. Cheap, deterministic, no model calls.
- **Study** = have Kioku *read, synthesize, and organize* it into structured notes/claims. Costs
  tokens, so it's batched and budget-guarded. Do this on the parts that matter, not everything.

You almost always want to **store everything, then study selectively.**

## Three inputs, three paths
1. **Already markdown/text** (Obsidian export, notes): just drop the files into the vault — they're
   already notes. BM25 searches them **live, instantly**; no processing. Bulk import files them into
   `reference/imported/` keeping your folder structure.
2. **Documents** (pdf/docx/csv): extracted → immutable copy in `sources/` + a note in `inbox/`.
3. **Images**: stored in `sources/` now; text once the vision step is wired.

## Bulk import (a lot at once)
1. Start a **new vault repo** (clean). 
2. Drop your export into `vault/_import/` (git-push it, or copy locally).
3. Trigger it:
   - CLI: `kioku import`  (or `kioku import <subdir>`)
   - API: `POST /bulk-ingest`  (optional `?subdir=_import`)
4. Kioku files markdown as notes, extracts documents, indexes once, and pushes. **No model cost.**
   With BM25 (your choice for now) everything is searchable the moment it lands.

## Then STUDY it (optional, when you want structure)
Ask Kioku to organize/synthesize — this is the migration flow in `02-vault-migration.md`:
- "audit my imported notes" → `/audit` gives the inventory (orphans, dupes, clusters).
- "organize reference/imported into a clean structure and flag what's stale" → it proposes
  moves/merges (sensitive writes go through approval).
- "summarize everything about <topic> into one note" → synthesis on demand.
Run heavy study passes as **Batch API** jobs overnight (50% cheaper) if the pile is large.

## Scale notes
- **Store** scales freely — it's just files + BM25; a big export costs nothing but disk (cents).
- **Study** is the only thing that costs; the budget guard caps it, so you can't overspend. Study in
  batches, on what's worth it — you don't need Kioku to read every old note, only the ones you'll use.
- Bulk import reads files from the worker's disk directly (no upload size limit); the 12 MB cap only
  applies to single-file uploads via Telegram/`/ingest`.
