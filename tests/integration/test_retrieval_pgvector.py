"""The real hybrid path: chunk → embed → pgvector (HNSW, cosine) → fused with BM25 by RRF."""
from kioku.memory import index, retrieval
from tests.conftest import write_note


async def test_reindex_is_incremental(pg, vault, fake_embeddings):
    write_note(vault, "infra/queue.md", "Celery uses Redis as the broker.\n\nBeat schedules the jobs.")
    write_note(vault, "life/trip.md", "Lisbon trip in November.")
    assert await index.reindex() == {"indexed": 2, "skipped": 0}
    assert await pg.fetchval("SELECT count(*) FROM chunks") == 2

    assert await index.reindex() == {"indexed": 0, "skipped": 2}          # nothing changed

    write_note(vault, "life/trip.md", "Lisbon trip moved to December.")
    assert await index.reindex() == {"indexed": 1, "skipped": 1}          # only the edited note
    assert "December" in await pg.fetchval("SELECT text FROM chunks WHERE path='life/trip.md'")


async def test_reindex_replaces_chunks_of_a_shrinking_note(pg, vault, fake_embeddings, monkeypatch):
    monkeypatch.setattr(index.settings, "chunk_chars", 30)
    note = write_note(vault, "long.md", "\n\n".join(f"paragraph number {i}" for i in range(5)))
    await index.reindex()
    assert await pg.fetchval("SELECT count(*) FROM chunks WHERE path='long.md'") == 5
    note.write_text("just one paragraph now")
    await index.reindex()
    assert await pg.fetchval("SELECT count(*) FROM chunks WHERE path='long.md'") == 1


async def test_reindex_without_embeddings_is_a_noop(pg, vault):
    write_note(vault, "a.md", "text")
    out = await index.reindex()
    assert out["indexed"] == 0 and "BM25 only" in out["note"]


async def test_vector_search_uses_pgvector(pg, vault, fake_embeddings):
    write_note(vault, "infra/queue.md", "celery redis broker worker")
    write_note(vault, "life/garden.md", "tomatoes basil water sun")
    await index.reindex()
    hits = await retrieval._vector_search("redis worker", k=2)
    assert hits[0]["path"] == "infra/queue.md"


async def test_hybrid_search_fuses_both_rankers(pg, vault, fake_embeddings):
    write_note(vault, "infra/queue.md", "celery redis broker worker")
    write_note(vault, "infra/db.md", "postgres pgvector hnsw index")
    write_note(vault, "life/garden.md", "tomatoes basil water sun")
    await index.reindex()
    hits = await retrieval.hybrid_search("pgvector index", k=2)
    assert hits[0]["path"] == "infra/db.md"
    assert "rrf" in hits[0]                                                # fused, not BM25-only
