"""Shared fixtures.

Settings are read once at import time, so the environment is pinned here, before any `kioku`
module is imported. Unit tests never touch the network: Redis is replaced by fakeredis and the
Claude Agent SDK by the fakes in tests/fakes.py. Integration tests (marked `integration`) use the
real Postgres + pgvector and Redis from docker-compose.test.yml.
"""
import os

os.environ.setdefault("VAULT_PATH", "/nonexistent-vault")        # every test gets its own tmp vault
os.environ.setdefault("DATABASE_URL", "postgresql://kioku:kioku@localhost:55432/kioku_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/15")
os.environ.setdefault("CONNECTORS_PATH", "/nonexistent-connectors.yaml")
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["DASHBOARD_TOKEN"] = ""
os.environ["LANGFUSE_PUBLIC_KEY"] = ""

from pathlib import Path  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Path:
    """An empty vault directory wired into every module that resolves vault paths."""
    from kioku.memory import vault as V

    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(V, "VAULT", root)
    V._bm25_cache.update(sig=None, bm25=None, files=None, corpus=None)
    return root


def write_note(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def fake_redis(monkeypatch):
    """One in-memory Redis shared by every module that holds a client at import time."""
    from kioku.memory import approvals, switch

    r = fakeredis.FakeRedis()
    monkeypatch.setattr(approvals, "_r", r)
    monkeypatch.setattr(switch, "_r", r)
    return r


@pytest.fixture
def no_notify(monkeypatch):
    """Capture outbound notifications instead of sending them to Telegram."""
    sent: list[str] = []
    from kioku.frontdoor import notify as N

    monkeypatch.setattr(N, "notify", lambda text, *a, **k: sent.append(text))
    return sent
