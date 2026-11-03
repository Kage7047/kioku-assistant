# Tests

```bash
pip install -e ".[dev]"
pytest                       # unit tests; integration tests skip if services are down
docker compose -f docker-compose.test.yml up -d --wait
pytest --cov                 # everything, with coverage
```

| Layer | Where | Talks to |
|---|---|---|
| Unit | `tests/unit/` | nothing: fakeredis, a tmp vault, and a scripted model (`tests/fakes.py`) |
| Integration | `tests/integration/` | real Postgres + pgvector and Redis (`docker-compose.test.yml`, CI service containers) |

**The scripted model.** `FakeQuery` replaces `claude_agent_sdk.query` and yields the same
message shapes the SDK streams (text blocks, a result, usage with cache tokens). Each test says
exactly what the model answers and how many tokens it reports, so agent runs are deterministic,
free, and need no API key or Claude Code subprocess. `RecordingOptions` captures the options a run
was configured with, so tests can assert on the tool surface, permission mode and turn caps.

**Embeddings in integration tests** are hashed bag-of-words vectors: not semantic, but deterministic
and enough to exercise the real pgvector path (cosine distance over an HNSW index).
Retrieval *quality* is measured separately, in `eval/`.

In CI `KIOKU_REQUIRE_INTEGRATION=1` turns a skipped integration test into a failure, so a broken
service container can never pass silently.
