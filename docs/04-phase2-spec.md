# Phase 2 — The multiplier (SPEC)

**Goal:** Kioku stops being one capped agent and becomes an orchestrated system with a
browser command center, safe multi-agent fan-out, and hands on your own machines. This is
where it starts doing real multi-step work you supervise instead of drive.

The vault-safety and budget primitives it depends on are already built (draft→apply,
preview-then-apply-with-hash, pre-flight + degrade). Phase 2 spends them.

---

## 2.1 Sub-agent fan-out

**What:** the orchestrator decomposes a task into sub-tasks, spawns Agent SDK **sub-agents**
(each isolated: own context window, own tool set, own model), and synthesizes their results.

**Design**
- **Sub-agents never write the vault.** They `stage_draft(run_id, path, content)`; the single
  orchestrator commits everything via `apply_drafts(run_id)` as one recoverable transaction.
  (Primitive already in `memory/pending.py` + `vault.apply_writes`.)
- **Per-sub-task routing** via `budget.route(difficulty, mode)` — most sub-agents on Haiku,
  the hard leaf on Sonnet, Opus only for genuine synthesis, Fable never automatically.
- **Fan-out budget cap:** pre-flight must estimate the *whole* fan-out, not one call. Add
  `max_subagents` and an aggregate-ceiling check; if the fan-out's projected ceiling exceeds
  remaining credit, reduce breadth (fewer sub-agents) or refuse. This is the #1 cost risk —
  the ~15× token multiplier lives here.
- **Interrupt & resume:** long fan-outs checkpoint sub-task state to a markdown checklist
  (DeepOrbit pattern) so a run can be paused/redirected/resumed without re-spending.

**New:** `agent/orchestrator.py::run_orchestrated(run_id, task)`; a `spawn_subagent` helper;
`stage_draft` used inside sub-agent tools; `budget.preflight_fanout(...)`.

**Acceptance:** a research task spawns N sub-agents, none writes directly, the orchestrator
applies one merged transaction, and the fan-out never exceeds its aggregate budget cap.

## 2.2 Command center (same-origin on Railway — MVP ✅ built 2026-08-18)

> **Hosting decision (2026-08-18):** served **same-origin from the FastAPI `api` service**, NOT
> Vercel. For a single private user this removes CORS, makes SSE + auth trivial, keeps one
> platform/one bill, and stays private by default. Revisit Vercel only if it ever goes public.
> **MVP shipped:** `api/static/index.html` (self-contained SPA), token middleware, and
> `GET /status` + `GET /runs` (assembled from Postgres `signals` + `runs` — the api never needs
> the vault volume). **To use it: set `DASHBOARD_TOKEN` and give the api a public domain.**

The one custom UI. Everything else stays adopted (Langfuse for traces/cost, Obsidian for graph).

**Panels**
- **Chat** — drive Kioku from desktop; same `/tasks` API as Telegram.
- **Live runs** — task queue + streaming events via SSE (`/tasks/{id}/stream`); status, model,
  mode, projected vs actual cost. Deep-link each run to its Langfuse trace.
- **Approval inbox** — the human-in-the-loop gate surface: pending writes (`GET /writes`),
  plus money/message/booking gates. Approve/reject → `POST /writes/{sha}/apply`.
- **Budget widget** — spend / remaining / mode, month-to-date sparkline from the `signals`
  self-metrics.
- **Vault graph** — parse wikilinks → `react-force-graph` (WebGL). v1 can defer to Obsidian's
  native graph; embed only if you want it in-browser.
- **Connector health** — from `connectors.yaml` + last signal timestamp per source.

**Plumbing:** worker → Redis pub/sub → FastAPI SSE → `EventSource`. Single-user token auth
(you only). No WebSockets needed — one-way streaming suffices.

**Acceptance:** you can watch a run stream live, approve a pending write from the browser, and
see budget + connector state at a glance.

> **Orchestrator cost upgrade (built 2026-08-19):** intent-based **tool narrowing** —
> `run_agent(intent=...)` sends only the tools an intent needs and, crucially, only mounts the
> external connector MCPs (Gmail/Drive/Notion + Composio session) for draft/plan/automate/
> research. recall/capture/code/command skip them → fewer tool defs = fewer input tokens.

## 2.3 Local runners (your machines, via Tailscale) — ⛔ Ollama tier NOT recommended

> **Decision (2026-08-19), see `docs/11-local-runner-analysis.md`:** skip the Ollama local
> triage tier — it optimizes a cost that's already pennies, needs always-on hardware a local
> machine can't guarantee, and adds a whole second platform. **Build the Claude Code hand-off instead**
> (heavy coding → laptop → separate interactive Pro pool, not the $20 credit). Keep local runners
> as an optional, use-case-gated capability (e.g. `index_repo`) only if a concrete need appears.

Cloud brain dispatches; machines execute. No heavy local media gen, so this is about local files, local
compute, and Claude Code hand-offs — not GPU rendering.

**Design**
- A Celery worker on the local machine / laptop connects **outbound** to the VPS Redis on a
  machine-specific queue (`gpu`, `laptop`). No port-forwarding, no exposed home box.
- **Allow-list only:** a runner runs *registered* tasks (`index_repo`, `ollama_triage`,
  `run_local_shell` with a strict command allow-list) — never arbitrary shell from the cloud.
- **Tailscale** puts VPS + machines on one private mesh for any live reach (a local MCP, SSH).
- **Ollama triage tier:** route the highest-volume, lowest-stakes calls (the always-on
  "nervous system") to a small local model — free while the PC is on, and it spares the $20.
- **Claude Code hand-off tool:** `handoff_to_claude_code(repo, task)` dispatches a supervised
  interactive session on the laptop. Key point: that draws on your **separate interactive Pro
  pool**, not the $20 Agent SDK credit — so heavy interactive coding doesn't touch Kioku's budget.
- **iPad = client only** (Telegram, dashboard, dispatch Claude mobile). iOS can't host a runner.

**Acceptance:** dispatching `index_repo` runs on the local machine and reports back; a runner
refuses any unregistered command; a Claude Code hand-off completes and posts its result.

## 2.4 People-CRM — ✅ populate built 2026-08-19

Populate the `people` table: who they are, context, last contact, notes path. Enables
**contact-aware prep** (before a call, assemble a brief from people + past threads + vault) and
**follow-up nudges** ("no reply in N days — draft one?"). This is the real version of the
"remember who X is and what they want" you originally hoped a Claude account could do.

> **Built:** `memory/people.py` (upsert/dedup by name+alias, merge context, source note),
> population folded into the digest Haiku call (near-free), `GET /people` + count on `/status`.
> ⏳ Still to do: the contact-prep brief surfaced as a command, and follow-up nudges (need a real
> last-contact signal, e.g. from Gmail).

## 2.5 Opportunity radar (toggleable, not central)

Job/gig pollers (Indeed/Upwork connectors) → `signals` → a ranked, deduped digest; optional
tailored draft bullets. Built as a connector + a digest task so it can be switched off the day
you don't need it — a capability, driven by config, never hardcoded.

## Phase 2 exit

You can hand Kioku a multi-step task, watch the fan-out in the browser, approve the writes it
proposes, have part of it run on your own hardware, and none of it silently blows the credit.
