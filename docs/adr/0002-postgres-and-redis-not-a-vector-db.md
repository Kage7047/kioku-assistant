# 0002 — Postgres + pgvector and Redis, not a dedicated vector database

**Status:** Accepted

## Context
Kioku needs relational state (runs, costs, claims, people), vector search over a few thousand
to a few hundred thousand chunks, a task queue, and pub/sub for live run streaming. It runs as a
single-owner system on a small managed host.

## Decision
One Postgres with the pgvector extension (HNSW index, cosine distance) for relational data and
vectors; one Redis as the Celery broker, the pub/sub bus for SSE, and the approval queue.

## Consequences
- Two stateful services instead of four; one backup story for everything relational.
- Vector search and the data it filters on live in one transaction scope.
- pgvector's HNSW is ample at personal scale. A dedicated vector store would only pay off at
  tens of millions of vectors or with heavy filtered-ANN needs — not this system's shape.
- Redis is not durable by default: approvals carry a 24-hour TTL by design, and nothing in Redis is
  the only copy of knowledge.
