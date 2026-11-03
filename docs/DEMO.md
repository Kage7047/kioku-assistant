# Demo

```bash
make demo          # builds and starts the stack, waits until it is healthy
# open http://localhost:8000 and enter the token: demo
make demo-down     # stop and delete the demo's data
```

Needs Docker only. No API key, no subscription, no Telegram bot.

## What is real and what is stubbed

| Part | In the demo |
|---|---|
| API, SSE streaming, command center | real |
| Celery worker, Redis, Postgres + pgvector | real |
| Intent router (heuristic path) | real |
| Budget pre-flight, run ledger, costs | real (the stub reports $0) |
| Retrieval over the vault (BM25) | real, over [`examples/vault`](../examples/vault) — a fictional owner |
| Outbound gate, vault guards, approvals | real |
| The model | **stub** (`MODEL_BACKEND=stub`, [`src/kioku/agent/stub.py`](../src/kioku/agent/stub.py)): it quotes the notes retrieval found instead of reasoning over them |
| Scheduled jobs (morning brief, pollers) | off (no Celery beat) |

## Things to try

- `what's blocking Jonas` — routed as recall; retrieval finds the meeting note and the person note.
- `that retry bug` — a vague query that still lands on the incident write-up.
- `remember: try Redis streams for the matcher queue` — captured to `inbox/` (it is a capture intent).
- `/audit` — a deterministic vault audit: orphans, dead links, notes per folder.

To run the same stack against a real model, use the main `docker-compose.yml` with your own `.env`
(see [QUICKSTART](QUICKSTART.md)).
