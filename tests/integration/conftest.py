"""Integration fixtures: a real Postgres (pgvector) and Redis.

Locally: `docker compose -f docker-compose.test.yml up -d --wait`, then `pytest -m integration`.
In CI they run as service containers. If the services are unreachable the tests are skipped
locally, but KIOKU_REQUIRE_INTEGRATION=1 (set in CI) turns that into a hard failure.
"""
import hashlib
import math
import os
import re
from pathlib import Path

import asyncpg
import pytest
import redis

from kioku.config import settings
from kioku.memory import db

SCHEMA = Path(__file__).resolve().parents[2] / "src/kioku/memory/schema.sql"
REQUIRE = os.getenv("KIOKU_REQUIRE_INTEGRATION") == "1"


def _unavailable(reason: str):
    if REQUIRE:
        pytest.fail(f"integration services required but unavailable: {reason}")
    pytest.skip(f"integration services unavailable ({reason}) — see docker-compose.test.yml")


def pytest_collection_modifyitems(items):
    here = str(Path(__file__).parent)
    for item in items:
        if str(item.fspath).startswith(here):
            item.add_marker(pytest.mark.integration)


@pytest.fixture
async def pg():
    """Fresh schema per test; the module-level pool is reset so it binds to this test's loop."""
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=3)
    except (OSError, asyncpg.PostgresError) as e:
        _unavailable(f"postgres: {e}")
    try:
        await conn.execute("DROP TABLE IF EXISTS chunks, people, claims, signals, runs CASCADE")
        await conn.execute(SCHEMA.read_text())
    finally:
        await conn.close()
    db._pool = None
    pool = await db.pool()
    yield pool
    await pool.close()
    db._pool = None


@pytest.fixture
def real_redis(monkeypatch):
    r = redis.Redis.from_url(settings.redis_url)
    try:
        r.ping()
    except redis.ConnectionError as e:
        _unavailable(f"redis: {e}")
    r.flushdb()
    from kioku.memory import approvals, switch
    monkeypatch.setattr(approvals, "_r", r)
    monkeypatch.setattr(switch, "_r", r)
    yield r
    r.flushdb()


# ---- deterministic embeddings --------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+")


def hashed_embedding(text: str, dim: int = 384) -> list[float]:
    """Bag-of-words hashed into `dim` buckets, L2-normalised. Not semantic, but deterministic,
    free and good enough to exercise the real pgvector path (cosine distance, HNSW index)."""
    v = [0.0] * dim
    for w in _WORD.findall(text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture
def fake_embeddings(monkeypatch):
    from kioku.memory import embeddings
    monkeypatch.setattr(embeddings, "available", lambda: True)
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [hashed_embedding(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda q: hashed_embedding(q))
