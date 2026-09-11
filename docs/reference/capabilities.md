# Reference · Capabilities — everything Kioku can do

Legend: **✅ built & tested** · **◒ scaffolded** (framework in, needs wiring/creds) · **○ planned** (spec).

## Talk to it (reactive loop)
- ✅ Natural language in, intent auto-routed — no modes (`recall / research / code / plan / draft / automate / capture / command`).
- ✅ Direct answer on demand (`/ask`, `kioku ask`).
- ✅ Grounded recall from your vault (hybrid BM25 + optional vectors), citing note paths.
- ◒ Deep research (needs a web-search MCP wired).
- ✅ Capture — "remember/todo/idea" filed as a structured card in `inbox/`.

## Feed the brain (ingestion)
- ✅ Ingest documents (pdf/docx/txt/md) via Telegram or `POST /ingest` → source copy + note + index.
- ✅ Ingest photos (stored immutably; ◒ text once vision is wired).
- ✅ Obsidian edits picked up (pulled every 10 min, reindexed).
- ✅ Immutable source capture (`sources/`) — a note always traces to its origin.

## Remember & stay healthy (memory)
- ✅ Vault as source of truth (markdown, git); Postgres as rebuildable index.
- ✅ Boot memory + ✅ persona + ○ profile loaded first each session.
- ✅ Decision journal after substantial runs (compounding).
- ◒ Claim ledger + ○ contradiction/staleness sweep.
- ✅ Hybrid retrieval; ◒ cross-lingual/semantic (flip `EMBEDDING_BACKEND`).

## Watch your world (proactive loop)
- ✅ Self-metrics poller (spend/mode over time).
- ✅ Deadline alerts from vault `due:` dates.
- ✅ Morning brief (task built; enable its beat entry).
- ◒ Real source pollers (gmail/sentry/vercel/indeed) — add adapters + enable in `connectors.yaml`.
- ✅ Budget-mode escalation pings.

## Get better (learning loop)
- ✅ Self-authored **skill library** — learned workflows matched before the generic agent.
- ✅ Propose a skill from recent journal work → approve by activating.
- ✅ Weekly review (retro + chained skill proposal).
- ○ Self-improvement: propose fixes to its own config, gated (Phase 4).

## Act (orchestration)
- ✅ Capped, budget-routed agent runs (Haiku/Sonnet/Opus; Fable never auto).
- ✅ Pre-flight cost estimate → allow / downgrade / refuse before spending.
- ✅ Vault tools (list/read/search/write) as in-process MCP.
- ◒ Calendar (stub → real Google Calendar MCP).
- ○ Sub-agent fan-out with aggregate budget cap (Phase 2).
- ○ Autonomous project ownership from a `charter.md` (Phase 4).
- ○ Computer-use hands (browser agent, gated) (Phase 4).

## On your machine (coding agent)
- ✅ CLI from any machine (`kioku …`).
- ○ Claude Code hand-off (interactive coding, uses your Pro interactive pool) (Phase 2/4).
- ○ Local runner: Agent SDK against your repo, registered dev tasks (`index_repo/run_tests/lint/
  review_diff/scaffold/open_pr`), allow-listed + gated (Phase 4).

## Interfaces
- ✅ Telegram (text, files, photos, commands).
- ✅ CLI. ✅ `POST /inbox` webhook (any app/cron/iOS Shortcut). ✅ `POST /ingest` upload.
- ✅ Obsidian (native). ✅ Claude Code (local, reads files).
- ○ Dashboard (design done — desktop + mobile mockups); ○ voice; ○ ambient (Phase 5).

## Governance (always on)
- ✅ Budget guard (pre-flight + degrade + notify). ✅ Caps on every run.
- ✅ Approval gates (sensitive writes; money/message/booking/PR). ✅ No deletes.
- ✅ Draft→apply transaction for fan-out safety. ✅ Langfuse traces + cost.
- ✅ "Capabilities are code, specifics are data" (`connectors.yaml`, vault).
