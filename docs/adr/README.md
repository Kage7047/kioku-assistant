# Architecture decision records

Short records of the decisions that shape Kioku: the context, the choice, and what it costs.
New decisions get the next number; a reversed decision is marked *Superseded* and links its successor.

| # | Decision | Status |
|---|---|---|
| [0001](0001-files-are-truth.md) | The markdown vault is the source of truth; Postgres is a rebuildable index | Accepted |
| [0002](0002-postgres-and-redis-not-a-vector-db.md) | Postgres + pgvector and Redis instead of a dedicated vector database | Accepted |
| [0003](0003-hybrid-retrieval-rrf.md) | Hybrid retrieval: BM25 + vectors fused by Reciprocal Rank Fusion | Accepted |
| [0004](0004-budget-guard.md) | A pre-flight budget guard with graceful degradation | Accepted |
| [0005](0005-outbound-gate-default-deny.md) | Outbound actions are default-deny, enforced outside the model | Accepted |
| [0006](0006-agent-sdk-over-raw-api.md) | Claude Agent SDK rather than a hand-written tool loop | Accepted |
