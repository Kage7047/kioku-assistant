"""Pluggable embeddings so retrieval works anywhere:

  EMBEDDING_BACKEND = local  -> sentence-transformers on your box/runner (free, private, needs RAM)
                      openai -> any OpenAI-compatible /embeddings endpoint (pennies, CPU-only OK)
                      voyage -> Voyage AI (Anthropic's multilingual embeddings partner)
                      none   -> no vectors; retrieval is BM25-only (zero cost, still works)

On Railway (CPU-only) prefer 'openai'/'voyage' or offload 'local' to a local-machine runner.
The output dim MUST match the vector(N) column in schema.sql (embedding_dim). OpenAI v3 models
accept a `dimensions` param, so text-embedding-3-small with dimensions=384 drops in cleanly.

Any failure returns None and retrieval falls back to BM25 — it never breaks search.
"""
from functools import lru_cache

from ..config import settings


# ---------- local ----------
@lru_cache(maxsize=1)
def _local_model():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(settings.embedding_model)
    except Exception:  # noqa: BLE001
        return None


def _encode_local(texts, is_query):
    m = _local_model()
    if m is None:
        return None
    pre = "query: " if is_query else "passage: "     # e5 convention
    vecs = m.encode([pre + t for t in texts], normalize_embeddings=True)
    return [[float(x) for x in v] for v in vecs]


# ---------- hosted ----------
def _openai_model() -> str:
    """The configured model, unless it's a local (HF-style 'org/name') id left over from the
    'local' default — then fall back to text-embedding-3-small so flipping ONLY
    EMBEDDING_BACKEND=openai works without also remembering to change EMBEDDING_MODEL."""
    m = settings.embedding_model
    return "text-embedding-3-small" if "/" in m else m


def _encode_openai(texts, is_query):
    import httpx
    model = _openai_model()
    body = {"model": model, "input": texts}
    if "3-" in model or "3." in model:
        body["dimensions"] = settings.embedding_dim         # v3 models can right-size to 384
    r = httpx.post(f"{settings.embedding_api_base}/embeddings",
                   headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
                   json=body, timeout=60)
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]


def _encode_voyage(texts, is_query):
    import httpx
    r = httpx.post("https://api.voyageai.com/v1/embeddings",
                   headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
                   json={"model": settings.embedding_model, "input": texts,
                         "input_type": "query" if is_query else "document",
                         "output_dimension": settings.embedding_dim}, timeout=60)
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]


_BACKENDS = {"local": _encode_local, "openai": _encode_openai, "voyage": _encode_voyage}


def available() -> bool:
    b = settings.embedding_backend
    if b == "none":
        return False
    if b == "local":
        return _local_model() is not None
    return bool(settings.embedding_api_key)


def _encode(texts, is_query=False):
    fn = _BACKENDS.get(settings.embedding_backend)
    if fn is None:
        return None
    try:
        return fn(texts, is_query)
    except Exception:  # noqa: BLE001  (any failure -> BM25 fallback)
        return None


def embed_passages(texts: list[str]):
    return _encode(texts, is_query=False)


def embed_query(text: str):
    out = _encode([text], is_query=True)
    return out[0] if out else None
