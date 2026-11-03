# 0001 — Files are truth; the database is an index

**Status:** Accepted

## Context
A personal memory has to outlive any one deployment, schema or embedding model. Notes also
need to be readable and editable by a human in ordinary tools (Obsidian, an editor, git).

## Decision
All knowledge lives as plain markdown in a git-backed vault. Postgres holds only what can be
recomputed from it — chunks and embeddings, the claim ledger, run history — plus operational
state (runs, signals). Dropping the database loses no knowledge: `reindex` rebuilds it.

## Consequences
- Portable and inspectable: the vault syncs to devices and every change is a reviewable commit.
- Re-indexing is incremental (mtime + content hash), so the index stays cheap to keep fresh.
- Two sources can drift; the index is always the one that yields. Writes go to the vault first.
- The vault becomes a security boundary of its own (see [0005](0005-outbound-gate-default-deny.md)
  and the threat model): `system/` and `.git/` are protected zones.
