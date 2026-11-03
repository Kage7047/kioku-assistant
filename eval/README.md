# Retrieval evaluation

Does Kioku find the right note? `run_eval.py` answers that with numbers instead of intuition.

```bash
pip install -e ".[dev,local-embeddings]"
python eval/run_eval.py        # ~30 s on a laptop CPU after the model is cached
```

Results: [`RESULTS.md`](RESULTS.md) (also `results.json`).

## Method

- **Corpus:** [`examples/vault`](../examples/vault), 39 notes of a fictional owner across
  projects, infrastructure, people, meetings, health, finance, travel and recipes, five of them in
  German, Polish, Spanish or French.
- **Queries:** 40 in [`queries.yaml`](queries.yaml), each labelled with the note(s) that answer it,
  in four groups: *exact* (shared rare tokens: IDs, names, jargon), *paraphrase* (same meaning,
  different words), *cross-lingual* (query and note in different languages), *vague* (short and
  underspecified, the way people actually ask).
- **Code under test:** the production functions — `memory.vault.search` (BM25), `memory.index.chunk_note`,
  `memory.retrieval.fuse` / `_rrf` — and the pgvector query reproduced exactly in memory (cosine
  over chunks). Embeddings: `intfloat/multilingual-e5-small`, Kioku's default local model.
- **Metrics:** recall@5 (a relevant note is in the top five, which is what reaches the prompt),
  recall@1 and MRR@10.

## What it found

The first run showed the shipped hybrid **losing to vector search alone** (recall@5 0.82 vs 0.97).
Two causes: BM25 matched on function words ("what", "the"), and equal-weight fusion let a note that
appeared in both lists on such a weak match outrank the note the vector ranker put first. Dropping
function words inside hybrid search and weighting lexical evidence at 0.5 fixed it:

| | recall@5 | recall@1 | MRR@10 |
|---|---|---|---|
| hybrid before | 0.82 | 0.72 | 0.78 |
| **hybrid now** | **0.97** | **0.85** | **0.90** |
| vector alone | 0.97 | 0.82 | 0.89 |

Hybrid now matches vector recall and ranks the right note first more often, while keeping BM25's
guarantees: it works with embeddings off, and exact identifiers stay at 1.00.

## Caveats

- 40 queries on a 39-note vault is small: one query is 2.5 points. Treat differences under ~5 points as noise.
- The queries were written by the same author as the notes, which flatters every ranker.
- At this size BM25's IDF is unstable; on a real vault of thousands of notes, exact-match queries
  are where lexical search earns its place.
- The vector side is exact cosine; production uses an HNSW index, which is approximate.

To evaluate on your own vault, point `VAULT_PATH` at it and write a `queries.yaml` for it.
