"""Chunk the vault and index chunks into pgvector, incrementally.

Incremental invalidation (DeepOrbit pattern): each file's chunks carry the file's
mtime_ns; if a file is unchanged we skip it, so re-indexing is cheap and embeddings
(which are local and free) only recompute for what changed. Chunk IDs are
path::ordinal::hash8 so identical paragraphs in different notes never collide.
"""
import hashlib

from .._compat import run_sync
from ..config import settings
from . import embeddings, vault as V
from .db import pool


def chunk_note(text: str, max_chars: int | None = None) -> list[str]:
    """Split on blank lines, greedily pack paragraphs up to ~max_chars."""
    max_chars = max_chars or settings.chunk_chars
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 > max_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def _hash8(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:8]


async def reindex(paths: list[str] | None = None) -> dict:
    """(Re)embed changed notes into `chunks`. Returns a small summary."""
    if not embeddings.available():
        return {"indexed": 0, "skipped": 0, "note": "embeddings unavailable — BM25 only"}

    p = await pool()
    files = V._md_files() if paths is None else [V.VAULT / x for x in paths]
    indexed = skipped = 0

    for f in files:
        rel = str(f.relative_to(V.VAULT))
        try:
            mtime_ns = f.stat().st_mtime_ns
        except FileNotFoundError:
            # A concurrent move/delete (e.g. a rename during a vault cleanup) removed the file
            # between listing and stat — skip it; the next reindex picks up the current tree.
            skipped += 1
            continue
        current = await p.fetchval("SELECT max(mtime_ns) FROM chunks WHERE path=$1", rel)
        if current == mtime_ns:
            skipped += 1
            continue

        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            skipped += 1
            continue
        parts = chunk_note(text)
        vecs = embeddings.embed_passages(parts) or []
        await p.execute("DELETE FROM chunks WHERE path=$1", rel)
        for i, (chunk, vec) in enumerate(zip(parts, vecs)):
            cid = f"{rel}::{i}::{_hash8(chunk)}"
            await p.execute(
                # $6::vector — asyncpg has no native vector codec; the explicit cast lets it send the
                # stringified list to the vector column reliably (see retrieval._vector_search).
                """INSERT INTO chunks (id, path, ordinal, content_hash, text, embedding, mtime_ns)
                   VALUES ($1,$2,$3,$4,$5,$6::vector,$7)
                   ON CONFLICT (id) DO NOTHING""",
                cid, rel, i, _hash8(chunk), chunk, str(vec), mtime_ns,
            )
        indexed += 1

    return {"indexed": indexed, "skipped": skipped}


def reindex_sync(paths: list[str] | None = None) -> dict:
    return run_sync(reindex(paths))
