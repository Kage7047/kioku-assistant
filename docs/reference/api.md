# Reference · API & Webhooks

Base URL = your api service (Railway) or `http://localhost:8000` (local). Single-user; put it
behind an auth token / private network before exposing it. Every interface (Telegram, CLI,
dashboard, iOS Shortcut, cron, your other apps) is a client of this API.

## Endpoints

### `GET /health`
Liveness. → `{"ok": true}`

### `GET /budget`
Current credit state. → `{mode, model, spend, credit, remaining, fraction, allowed}`

### `POST /tasks`
Submit work. Body:
```json
{ "kind": "input|ask|vault_audit", "input": "text", "difficulty": "triage|work|orchestrator|hard", "essential": true }
```
- `kind:"input"` → intent router (recommended; natural language).
- `kind:"ask"` → direct agent answer at `difficulty`.
- `kind:"vault_audit"` → runs the audit.
→ `{ "run_id": "...", "stream": "/tasks/{run_id}/stream" }`

### `POST /inbox`
Universal capture/ask (natural language, always routed). Body `{ "input": "text" }`.
→ `{ run_id, stream }`. **This is the webhook to point any interface at** (iOS Shortcut, email
forwarder, another app, cron).

### `POST /ingest`  (multipart)
Upload a file/photo to learn from it. Field `file`. ≤ 12 MB inline (larger → object storage later).
→ `{ run_id, file }`. Stores an immutable copy in `sources/`, extracts text, files a note in
`inbox/`, indexes, pushes.

### `GET /tasks/{run_id}/stream`  (SSE)
Live events for a run. Each `data:` line is JSON with a `type`:
`preflight` (budget decision) · `start` (model, mode) · `text` (streamed output) ·
`usage` (tokens) · `done`. Clients forward milestones (Telegram) or render live (dashboard/CLI).

### `POST /reindex`
Rebuild the search index (incremental). → `{ "status": "reindex enqueued" }`

### `GET /skills`
List learned skills. → `[{ name, when }]`

### `GET /writes`
List pending vault writes awaiting approval. → `[{ sha256, path }]`

### `POST /writes/{sha}/apply`
Approve a pending write (enqueues application on the worker, then indexes + pushes).
→ `{ "status": "apply enqueued", "sha": "..." }` · `404` if the plan expired/unknown.

## Examples
```bash
# ask
curl -sXPOST $API/tasks -H 'content-type: application/json' \
  -d '{"kind":"input","input":"how is Acme this week?"}'
# capture via the inbox webhook
curl -sXPOST $API/inbox -H 'content-type: application/json' \
  -d '{"input":"remember: exam due 2026-09-01"}'
# ingest a file
curl -sXPOST $API/ingest -F 'file=@whiteboard.jpg'
# approve a pending write
curl -sXPOST $API/writes/9f3ac1.../apply
```

## iOS Shortcut (make the iPad an input device)
A Shortcut with a "Get Contents of URL" action → `POST {API}/inbox`, body `{"input": <dictated text>}`,
gives you "Ask Kioku" + Siri on iOS (which can't run a worker). Add it to the Share Sheet to send
selected text/links straight into the brain.

## Notes
- Telegram uses **polling** in-process (no public webhook needed). To use a Telegram *webhook*
  instead, terminate it at the api service URL.
- Long files ride the Celery broker as base64 (≤12 MB). For heavy media, point `sources/` at object
  storage (R2/B2) and store a reference.
