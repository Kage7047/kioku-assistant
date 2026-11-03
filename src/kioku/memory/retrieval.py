"""Hybrid retrieval = BM25 (lexical) + pgvector (semantic), fused with Reciprocal Rank
Fusion. Falls back to BM25-only if embeddings/vector search are unavailable.

WHY hybrid (not BM25 alone):
- BM25 matches exact terms — great for identifiers (EP3859566B1, `pgvector`, a name),
  useless when your words differ from the note's ("overspending" vs "budget guard").
- Vectors match meaning — great for paraphrase and CROSS-LINGUAL recall (a query in one
  language matching a note in another), but blur rare exact tokens and can rank a near-miss above the exact hit.
- Fusing both gets lexical precision AND semantic recall. RRF needs no score
  normalization between the (incomparable) BM25 and cosine scores — it fuses on RANK.
- Bonus: tighter, more relevant context = fewer input tokens = less credit burned.
- And embeddings unlock what BM25 can't do at all: near-duplicate detection and
  contradiction/staleness sweeps over the claim ledger.
"""
import logging

from . import embeddings, vault as V
from .db import pool
from .._compat import run_sync

log = logging.getLogger("kioku.retrieval")


# Lexical evidence counts half as much as semantic evidence in the fusion. Measured in eval/:
# with equal weights, notes that appear in both lists on weak keyword matches outrank the note
# the vector ranker put first (recall@1 0.80 → 0.85, MRR 0.87 → 0.90 on the sample set).
LEXICAL_WEIGHT = 0.5


def _rrf(*ranked_lists, k: int, c: int = 60, weights: tuple[float, ...] | None = None) -> list[dict]:
    """Fuse ranked lists of {path, excerpt} by (weighted) Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    best: dict[str, dict] = {}
    weights = weights or (1.0,) * len(ranked_lists)
    for lst, w in zip(ranked_lists, weights, strict=True):
        for rank, item in enumerate(lst):
            path = item["path"]
            scores[path] = scores.get(path, 0.0) + w / (c + rank + 1)
            best.setdefault(path, item)
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return [{**best[p], "rrf": round(s, 5)} for p, s in ordered]


async def _vector_search(query: str, k: int) -> list[dict]:
    qv = embeddings.embed_query(query)
    if qv is None:
        return []
    try:
        p = await pool()
        # Cast the bound param explicitly to vector: asyncpg has no native vector codec, so a bare
        # $1 (Python list stringified) can be inferred as text and `vector <=> text` has no operator
        # → the query errors and semantic search silently degrades to BM25. `$1::vector` fixes that.
        rows = await p.fetch(
            """SELECT path, text FROM chunks
               ORDER BY embedding <=> $1::vector LIMIT $2""",
            str(qv), k,
        )
        return [{"path": r["path"], "excerpt": r["text"][:400]} for r in rows]
    except Exception as e:  # noqa: BLE001  (no chunks table / no pgvector → BM25 fallback)
        log.warning("vector search unavailable, falling back to BM25 — %s: %s",
                    type(e).__name__, str(e)[:160])
        return []


def _one_per_note(hits: list[dict]) -> list[dict]:
    """The vector query returns chunks; keep each note's best chunk so a long note gets one vote."""
    seen: set[str] = set()
    out = []
    for h in hits:
        if h["path"] not in seen:
            seen.add(h["path"])
            out.append(h)
    return out


def fuse(lexical: list[dict], semantic: list[dict], k: int) -> list[dict]:
    return _rrf(lexical, _one_per_note(semantic), k=k, weights=(LEXICAL_WEIGHT, 1.0))


async def hybrid_search(query: str, k: int = 6) -> list[dict]:
    semantic = await _vector_search(query, k * 3)
    if not semantic:
        return V.search(query, k)               # graceful: BM25-only, function words kept
    return fuse(V.search(query, k * 3, stopwords=True), semantic, k)


def hybrid_search_sync(query: str, k: int = 6) -> list[dict]:
    return run_sync(hybrid_search(query, k))
