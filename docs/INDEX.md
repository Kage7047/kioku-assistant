# Kioku (記憶) — Documentation

A private, self-owned agentic personal assistant. A memory that never sleeps. Cloud brain, local
hands, three loops (reactive · proactive · learning), all behind one safety governor.

## Start here
- **[QUICKSTART](QUICKSTART.md)** — your first evening, end to end (deploy → import → live).
- **[Runbook](08-runbook.md)** — from nothing to Kioku running (Railway or local) → first `/audit`,
  first capture, first photo, first proposed skill.
- **[Master Plan](00-master-plan.md)** — vision, architecture, stack, cost model, roadmap, build status.
- **[README](../README.md)** — repo quickstart.

## Reference (everything, exactly)
- **[Architecture](reference/architecture.md)** — how it works, request lifecycle, freshness, governor.
- **[Commands](reference/commands.md)** — every Telegram + CLI command.
- **[API & Webhooks](reference/api.md)** — every endpoint, `/inbox` webhook, `/ingest`, SSE, iOS Shortcut, examples.
- **[Configuration](reference/configuration.md)** — every env var.
- **[Data Model](reference/data-model.md)** — Postgres tables + vault layout + write rules.
- **[Capabilities](reference/capabilities.md)** — full catalog of what it can do (built / scaffolded / planned).
- **[Modules](reference/modules.md)** — file-by-file code map.
- **[Connectors](reference/connectors.md)** — tool vs poller, `connectors.yaml`, how to add one.
- **[Connecting each one](reference/connecting.md)** — step-by-step per connector (incl. the bank, safely).
- **[Ingesting at scale](reference/ingesting-at-scale.md)** — new vault, bulk import, store-vs-study.
- **[Guardrails & Approvals](reference/guardrails.md)** — the decided ask/don't-ask boundaries.

## Design & concepts
- **[The Three Loops](07-the-three-loops.md)** — reactive / proactive / learning.
- **[Interfaces & Features](06-interfaces-and-features.md)** — surfaces + the universal backbone + ingestion.
- **[Vault Migration](02-vault-migration.md)** — rebuilding the second brain (Kioku's first real job).
- **Mockups** — `mockups/dashboard-desktop.html`, `mockups/dashboard-mobile.html` (the command center).

## Build phases
- **[Phase 0 — Skeleton](01-phase0-tech-task.md)** ✅ built.
- **[Phase 1 — Daily-useful + subscription-safe](03-phase1-spec.md)** ✅ mostly built.
- **[Phase 2 — Command center + fan-out + local runners](04-phase2-spec.md)** ○ spec.
- **[Phase 4 — Agency & Character](09-phase4-agency.md)** ○ next version (persona ✅ seeded, coding-agent, autonomy, computer-use, self-improvement).
- **[Phase 5 — Presence](10-phase5-presence.md)** ○ later (voice + ambient).

## Deploy
- **[Runbook](08-runbook.md)** · **[Railway guide](05-deploy-railway.md)** (pgvector template, git-backed vault, cost).

---

## Coverage — every idea from design, mapped to where it lives
| Idea | Where |
|---|---|
| Agent SDK orchestration, orchestrator→sub-agents | 00, 04, architecture |
| Second brain = the heart; files are truth | 00, 02, data-model |
| Hybrid BM25 + pgvector + RRF; local/hosted embeddings | 03, architecture, config |
| Budget guard, pre-flight, model routing, subscription credit | 00, 05, config, capabilities |
| Vault write safety (hash gate + draft→apply) | 01, data-model, modules |
| Three loops: router+capture, pollers+alerts, skills+journal+review | 07, capabilities |
| Ingestion (files/photos on the fly) | 06, api, capabilities |
| Interfaces: Telegram, CLI, `/inbox` webhook, Obsidian, iOS Shortcut, dashboard | 06, commands, api |
| Dashboard (desktop + mobile + living brain graph) | mockups/, 04 |
| Railway deploy, git-backed vault, cost vs Acme, volume cost | 05, 08 |
| Local coding agent (Claude Code hand-off vs runner), registered dev tasks | 09 |
| Autonomous project ownership; computer-use hands | 09 |
| Persona, model-of-you, intelligent proactivity, self-improvement | 09 |
| Voice + ambient (deferred) | 10 |
| Capabilities are code, specifics are data; retired examples | 00, 02, connectors.yaml |
