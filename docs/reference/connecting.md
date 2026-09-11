# Reference · Connecting each connector (step by step)

Three auth patterns. Find your connector, follow its steps, set the env var(s), flip
`enabled: true` in `connectors.yaml`, redeploy the **worker** (or restart it locally).

| Pattern | Connectors | How you authenticate |
|---|---|---|
| **A. MCP tool** | calendar, gmail, drive, notion, sheets, canva, figma | a remote MCP server URL + a token; mounted in-run |
| **B. Service token (poller)** | sentry, vercel, github | a personal/API token from the service's settings |
| **C. Special** | db (read-only role), **bank** (read-only aggregator) | your own DB role / a banking-data provider |

Rule of thumb: **pollers run headless**, so they need a real token stored as an env secret —
not the interactive "Connect" button on claude.ai (that authorises *your* Claude app, not Kioku's
worker).

---

## A. MCP tool connectors (calendar, gmail, drive, notion, sheets, canva, figma)

These are mounted as tools during a run. You need a **remote MCP server** for the service and a
token, then point the connector's `url` + `auth_env` at it.

Where the MCP server comes from (pick one):
- A hosted MCP the vendor publishes (e.g. Notion's official MCP), or
- A community/registry MCP server you run (many are one-container deploys), or
- Compose it via an MCP gateway (e.g. a Composio/Zapier-style MCP endpoint that fronts Google,
  Notion, etc. with one token).

Steps:
1. Get the MCP server's **URL** (e.g. `https://mcp.notion.com/mcp`) and an **auth token** for it.
2. In `connectors.yaml`, set that connector's `url:` and keep its `auth_env:` name.
3. Put the token in that env var (e.g. `NOTION_MCP_TOKEN=...`).
4. `enabled: true`, redeploy the worker.
Kioku mounts it and can use its tools the next run. If `url` still has `<your-…>` or the token is
missing, it's skipped cleanly.

> Note: the consumer connectors on claude.ai (the ones you "Connect" in the app) authorise the
> Claude apps, not your headless worker. For Kioku you either reuse a server that accepts a bearer
> token, or run the vendor's MCP with your own OAuth/token. Verify the server `type` (`http` vs
> `sse`) against `agent/mcp_servers.py`.

---

## B. Service-token pollers

### Vercel
1. Vercel → **Account Settings → Tokens → Create** (scope to the team/project).
2. `VERCEL_TOKEN=...` → enable `vercel`.

### Sentry
1. Sentry → **Settings → Developer Settings → Auth Tokens** (or an Internal Integration) with
   `project:read` / `event:read`.
2. `SENTRY_AUTH_TOKEN=...`, `SENTRY_ORG=<org-slug>`, `SENTRY_PROJECT=<project-slug>` → enable `sentry`.

### GitHub
1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained token**.
   Scope it to only the repos you want, **read-only** (Contents: Read, Pull requests: Read,
   Issues: Read, Metadata: Read). No write scopes needed for the poller.
2. `GITHUB_TOKEN=github_pat_...`, `GITHUB_REPOS=you/acme,you/kioku` → enable `github`.

---

## C. The DB (Acme) — read-only, your queries only

Kioku never introspects your whole DB; it runs **only the SELECTs you name**.

1. Create a **read-only Postgres role** (do NOT reuse your app's write role):
   ```sql
   CREATE ROLE kioku_ro LOGIN PASSWORD '…';
   GRANT CONNECT ON DATABASE acme TO kioku_ro;
   GRANT USAGE ON SCHEMA public TO kioku_ro;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO kioku_ro;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO kioku_ro;
   ```
2. `APP_DB_URL=postgresql://kioku_ro:…@host:5432/acme`
3. Name the metrics you want as `name:SQL;name:SQL` (each must return one value):
   ```
   APP_DB_QUERIES=signups:SELECT count(*) FROM users;active7:SELECT count(*) FROM users WHERE last_seen > now() - interval '7 days';mrr:SELECT coalesce(sum(amount),0) FROM subscriptions WHERE status='active'
   ```
4. Enable `db`. Three layers protect you: the read-only role, the read-only connection, and the
   in-code SELECT-only check that refuses anything else.

---

## C. The bank — read-only, transfers impossible by construction

**Do not point Kioku at your bank's raw login.** Consumer banks don't offer a safe API, and you
never want write access in reach. Use an **aggregation provider** that issues **read-only** tokens.

Options (pick per what covers Revolut / your EU banks):
- **GoCardless Bank Account Data** (formerly Nordigen) — free tier, EU/PSD2 coverage incl. Revolut,
  **read-only by design** (balances + transactions; it cannot move money).
- **Plaid** (has EU coverage) — request **only the read products** (Balances, Transactions); do
  **not** enable Payment Initiation. Heavier/paid.
- **Salt Edge / TrueLayer (data-only scope)** — similar EU aggregators.

Why this is safe: these are *account-information* services. With a data-only connection the token
**physically cannot initiate a transfer** — the payment capability is a separate product you simply
don't enable. That's the outer wall. Kioku adds two inner walls: it issues **GET only**, and there
is **no transfer/payment code anywhere** in it to call.

Steps (GoCardless shown; others analogous):
1. Create the provider account → get **API credentials**; connect your bank in **read/transactions**
   scope (never a payments scope).
2. It gives you a **read-only access token** and an accounts endpoint.
3. `BANK_API_BASE=https://…` (the provider's base URL), `BANK_TOKEN=<read-only token>`.
4. Leave `BANK_ALLOW_TRANSFERS=false` (it's inert regardless — no transfer code exists).
5. Enable `bank`, **start with the longest poll interval**, watch one cycle land in `signals`,
   confirm it's only reading, then rely on it.

Recommended posture for v1: **balances + recent transactions only**, refresh every 6h, and let it
feed the runway/finance view. Transfers, if ever, become a separate, deliberately-built, hard-gated
feature — never a config flip.

---

## After enabling anything
- Redeploy/restart the **worker** (pollers run there; MCP mounts load per run).
- Poller landed? Ask Kioku "what signals do you have?" or check the `signals` table / morning brief.
- MCP tool working? Ask something that needs it ("what's on my calendar tomorrow?").
- Nothing? Check the token/env name matches `auth_env`, and that `enabled: true`.
