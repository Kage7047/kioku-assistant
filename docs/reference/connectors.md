# Reference · Connectors

Two jobs, declared in `connectors.yaml`. Adding a connector is a config line (+ a small adapter
for pollers). Retiring one is deleting the line. *Capabilities are code; which sources exist is
this file.*

## The two jobs

| `kind` | When it runs | What it does | Example |
|---|---|---|---|
| `mcp` | **on-demand, in a run** | mounted as a **tool** the agent can call | "what's on my calendar Friday?" |
| `poller` | **on a schedule** (Beat) | pulls into the `signals` store for briefs/alerts | Sentry error spikes |
| `metrics` | scheduled | built-in poller (Kioku's own stats) | `self` |

Most of what you already have on your Claude account (Gmail, Calendar, Drive, Notion) fits `mcp` —
Kioku's orchestrator mounts them, so it's config, not a hand-written API client. The awareness feed
(what changed while you were away) needs `poller`s, which are real adapters.

## `connectors.yaml` schema
```yaml
- {name: calendar, kind: mcp, enabled: false, url: "https://…/mcp", auth_env: CALENDAR_MCP_TOKEN, note: "…"}
- {name: sentry,   kind: poller, enabled: false, schedule: 3600, note: "…"}
```
- `enabled` — false = a slot, ignored until you flip it.
- `url` + `auth_env` — for `mcp`: the server URL and the **env var** holding its token.
- `schedule` — for pollers/metrics: seconds between polls.

## Auth (the gotcha)
Kioku's **worker is headless**. MCP servers on claude.ai are authed interactively through your
Claude account — that works for *tool* use in a live run, but background **pollers can't do an
interactive OAuth dance**, so they use proper per-service tokens stored as env/secrets:
`SENTRY_AUTH_TOKEN` + `SENTRY_ORG` + `SENTRY_PROJECT`, `VERCEL_TOKEN`, etc. For `mcp` connectors,
put each server's token in the env var named by its `auth_env`.

> Step-by-step setup for each connector (tokens, the DB role, the bank aggregator): **`connecting.md`**.

## Read-only & guardrailed connectors
- **db** (`poll_db`) runs only your named `APP_DB_QUERIES` and **enforces SELECT-only in code**
  (`_is_readonly`), *and* opens the connection read-only. Use a **read-only DB role** as a third layer.
- **bank** (`poll_bank`) is **strictly read-only**: Kioku issues **GET only**, never POST/PUT/PATCH/
  DELETE. There is **no transfer/payment code anywhere** in the system; `BANK_ALLOW_TRANSFERS` is inert
  by design. Use a read-only API scope on the bank side too. Start it disabled, test, then enable.

## Wired now
- `self` (metrics) — spend/mode over time. ✅
- `sentry` (poller) — unresolved issues + 24h events. ✅ needs `SENTRY_*`.
- `vercel` (poller) — recent deploys + error states. ✅ needs `VERCEL_TOKEN`.
- `github` (poller) — open PRs + issue counts per repo. ✅ needs `GITHUB_TOKEN`, `GITHUB_REPOS`.
- `db` (poller) — app metrics via read-only SELECTs. ✅ needs `APP_DB_URL` (read-only role), `APP_DB_QUERIES`.
- `bank` (poller) — balances/txns, **read-only, no transfers**. ✅ needs `BANK_API_BASE`, `BANK_TOKEN`.
- `calendar`/`gmail`/`drive`/`notion`/`sheets`/`canva`/`figma` (mcp) — mount when you set `url` + token.
  Calendar falls back to the local stub until configured.

## Add a tool connector (mcp)
1. Add a line with `kind: mcp`, its `url`, and an `auth_env`.
2. Set that env var to the server's token.
3. `enabled: true`. The orchestrator mounts it next run (`agent/mcp_servers.py`).

## Add a poller
1. Write `poll_<name>()` in `worker/pollers.py` → `db.record_signal_sync(source, key, value)`.
2. Register it in `REGISTRY`.
3. Add `{name: <name>, kind: poller, enabled: true, schedule: 3600}` to `connectors.yaml`.
It's picked up by `poll_all_task` (hourly) and flows into briefs + alerts.

Verify the external-MCP config shape and `allowed_tools` naming against your pinned
`claude-agent-sdk` version (`agent/mcp_servers.py` has a note).
