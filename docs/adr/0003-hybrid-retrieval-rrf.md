# 0003 — Hybrid retrieval with Reciprocal Rank Fusion

**Status:** Accepted

## Context
Queries mix exact identifiers (a patent number, a library name, a person) with paraphrase
("overspending" for a note titled "budget guard") and other languages. Lexical and semantic
rankers each miss what the other catches, and their scores are not comparable.

## Decision
Run BM25 (read live from the vault) and pgvector side by side and fuse the two ranked lists by
Reciprocal Rank Fusion (`1 / (60 + rank)`), which needs no score normalisation. If embeddings are
off or the database is unavailable, fall back to BM25 alone.

## Consequences
- Search always works, even with `EMBEDDING_BACKEND=none` or a database outage.
- Pre-fetched context means most recall questions answer in one model turn instead of several
  tool round-trips, which saves more tokens than retrieval costs.
- Quality is measured, not assumed. The first measurement (`eval/`) showed equal-weight fusion
  losing to vector search alone, so the fusion was changed: function words are dropped from BM25
  inside hybrid search, lexical evidence is weighted 0.5, and each note gets one vector vote.
  Hybrid recall@5 went from 0.82 to 0.97 (recall@1 0.72 → 0.85) on the labelled set.
