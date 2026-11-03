"""Hybrid retrieval: Reciprocal Rank Fusion, the BM25 fallback, and chunking."""
from kioku.memory import index, retrieval
from kioku.memory import vault as V
from tests.conftest import write_note


def _hits(*paths):
    return [{"path": p, "excerpt": p.upper()} for p in paths]


# ---- RRF -------------------------------------------------------------------------------
def test_rrf_rewards_agreement_between_rankers():
    lexical = _hits("a", "b", "c")
    semantic = _hits("d", "b", "e")
    fused = [h["path"] for h in retrieval._rrf(lexical, semantic, k=4)]
    assert fused[0] == "b"                                   # 2nd in both beats 1st in one
    assert set(fused) == {"a", "b", "d", "c"}


def test_rrf_scores_follow_the_formula():
    fused = retrieval._rrf(_hits("a"), _hits("a"), k=1, c=60)
    assert fused[0]["rrf"] == round(2 / 61, 5)


def test_rrf_truncates_to_k_and_keeps_first_excerpt():
    fused = retrieval._rrf(_hits("a", "b", "c"), [{"path": "a", "excerpt": "other"}], k=2)
    assert len(fused) == 2
    assert fused[0]["excerpt"] == "A"


def test_rrf_handles_empty_lists():
    assert retrieval._rrf([], [], k=5) == []


# ---- hybrid search ---------------------------------------------------------------------
async def test_hybrid_falls_back_to_bm25_without_embeddings(vault, monkeypatch):
    write_note(vault, "infra.md", "pgvector stores embeddings next to the runs table")
    write_note(vault, "food.md", "pierogi recipe")
    write_note(vault, "trip.md", "Lisbon hotel near Alfama")    # BM25 idf needs a few docs
    monkeypatch.setattr(retrieval.embeddings, "embed_query", lambda q: None)
    hits = await retrieval.hybrid_search("pgvector embeddings", k=2)
    assert [h["path"] for h in hits] == ["infra.md"]
    assert "rrf" not in hits[0]


async def test_hybrid_fuses_when_vectors_are_available(vault, monkeypatch):
    write_note(vault, "budget-guard.md", "the budget guard refuses runs over the monthly credit")
    write_note(vault, "spending.md", "notes on overspending")
    write_note(vault, "trip.md", "Lisbon hotel near Alfama")

    async def vectors(query, k):
        return [{"path": "spending.md", "excerpt": "notes on overspending"}]

    monkeypatch.setattr(retrieval, "_vector_search", vectors)
    hits = await retrieval.hybrid_search("budget guard", k=3)
    assert {h["path"] for h in hits} == {"budget-guard.md", "spending.md"}
    assert all("rrf" in h for h in hits)


async def test_vector_search_degrades_quietly_when_db_is_down(monkeypatch):
    monkeypatch.setattr(retrieval.embeddings, "embed_query", lambda q: [0.1, 0.2])

    async def broken_pool():
        raise ConnectionRefusedError("no db")

    monkeypatch.setattr(retrieval, "pool", broken_pool)
    assert await retrieval._vector_search("anything", 3) == []


# ---- chunking --------------------------------------------------------------------------
def test_chunking_packs_paragraphs_up_to_the_limit():
    text = "\n\n".join(["a" * 40, "b" * 40, "c" * 40])
    assert index.chunk_note(text, max_chars=90) == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40]


def test_chunking_never_drops_an_oversized_paragraph():
    big = "x" * 500
    assert index.chunk_note(f"intro\n\n{big}\n\noutro", max_chars=100) == ["intro", big, "outro"]


def test_chunking_ignores_blank_paragraphs():
    assert index.chunk_note("\n\n\n  \n\nonly\n\n\n") == ["only"]


# ---- shipped fusion (see eval/RESULTS.md for why) ----------------------------------------------
def test_weighted_fusion_lets_the_semantic_first_hit_win():
    lexical = _hits("noise-a", "noise-b", "answer")       # weak keyword matches first
    semantic = _hits("answer", "noise-a")
    assert retrieval.fuse(lexical, semantic, k=3)[0]["path"] == "answer"
    # with equal weights the note in both lists on a weak match wins instead
    assert retrieval._rrf(lexical, semantic, k=3)[0]["path"] == "noise-a"


def test_fusion_counts_one_vote_per_note():
    long_note = [{"path": "long.md", "excerpt": f"chunk {i}"} for i in range(3)]
    fused = retrieval.fuse([], long_note + _hits("other.md"), k=2)
    assert [h["path"] for h in fused] == ["long.md", "other.md"]


def test_stopwords_only_matches_return_nothing_in_hybrid_mode(vault):
    write_note(vault, "a.md", "what is the plan")
    write_note(vault, "b.md", "pierogi recipe")
    write_note(vault, "c.md", "lisbon hotel")
    assert V.search("what is the", 3, stopwords=True) == []
    assert V.search("what is the", 3)                    # BM25-only mode keeps function words
