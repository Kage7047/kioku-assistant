# Phase 3 — Agency: from answering to acting & learning

> Phases 0–2 made Kioku reliable, cheap, and proactive-by-schedule. Phase 3 makes it **act** (prepare
> real work up to the outbound step) and **learn** (sharpen its model of you over time) — all under the
> same governor: budget guard, draft→apply, and the on/off switch. Nothing here auto-sends, auto-spends,
> or fans out. (Sub-agent fan-out stays in the backlog — it raises usage.)

## Guardrails that apply to everything below
- **Budget-gated + pausable.** Every new job checks the budget pre-flight and `switch.is_paused()`.
- **Draft→apply for anything outbound.** Emails, calendar events, applications, profile edits are
  *prepared* and staged for one tap; Kioku never sends/books/posts on its own.
- **Deterministic-first.** Do the free Python work (diffing signals, scanning the vault) before a model call.
- **Cheap by default.** Haiku unless the task needs Sonnet; strict turn caps; scheduled work is non-essential.

---

## 3.1 Event-driven proactivity  *(cheap, mostly deterministic — do first)*
Move from a once-a-day brief to **timely nudges** when something actually changes.
- A `watch_signals_task` (every ~15 min) diffs the latest poll results against the previous snapshot and
  fires `notify()` only on meaningful deltas: a deploy went **down**, CI **failing**, an error **spike**,
  budget mode **escalated**, a **recruiter reply** detected, a deadline within 3 days, an opportunity ≥ high fit.
- Extends the existing `alerts.py` rule engine (deterministic; no model tokens for detection).
- Dedup so the same alert doesn't repeat (Redis "last fired" per rule).
- **Value: high. Cost: ~zero. Risk: low.**

## 3.2 Self-education — deepen the model-of-you  *(moderate)*
Kioku's picture of you should sharpen every week, not stay static.
- A weekly `learn_task`: scan recent **calendar + notable mail + GitHub activity** (connectors already
  mounted) and the newly-digested second-brain, then propose updates to `reference/profile/*` and the
  **claim ledger** — as a **draft** you approve (profile edits are not silent).
- Fold connector highlights into `signals` so recall and briefs improve.
- Periodic **profile synthesis**: distil `reference/profile/` + claims into a tighter `system/profile.md`
  (draft→apply), so the loaded context stays sharp without bloating.
- **Value: high (compounding). Cost: one weekly Sonnet pass. Risk: low (draft-gated).**

## 3.3 Acting with the gate — prepare real work  *(highest user value)*
Let Kioku take things to the one-tap-from-done line.
- **Draft replies / applications** for radar hits and recruiter mail: tailored to the matching CV, staged
  as a Gmail **draft** (Composio) — you review and send. Never auto-send.
- **Calendar events from context**: propose events from mail/threads → approve → book.
- **Prep commands**: `contact-prep <name>` (People-CRM → a one-page briefing before a meeting);
  `apply <opportunity>` (draft a targeted application from the best-fit CV + the posting).
- All writes/outbound go through the existing hash-gate / draft→apply. 
- **Value: very high. Cost: moderate. Risk: contained by the outbound gate — the critical invariant.**

## 3.4 Meta-cognition — self-improvement  *(cheap-ish)*
Kioku reviews and tunes itself.
- Weekly **self-review** of its own `runs`: cost outliers, failures, slow paths, model mix → a short
  report + concrete tuning suggestions (routing thresholds, turn caps).
- **Skill maturation**: it already proposes skills from the journal; add usage tracking so unused skills
  are pruned and used ones are trusted.
- A **"why did that cost so much"** self-audit command over a run's trace.
- **Value: medium (keeps it cheap as it grows). Cost: low. Risk: low.**

## 3.5 Heavy-work hand-off (Claude Code)  *(decided direction)*
Route heavy coding to a **separate Pro pool** via a Claude Code hand-off, off the $20 Agent-SDK credit
(per docs/11). Kioku scopes the task + context; the hand-off does the build; results flow back to the vault.
- **Value: high for the Acme/Kioku build cadence. Cost: off the $20. Risk: low.**

## 3.6 Interfaces breadth  *(optional, later in the phase)*
The universality backbone (docs/06): Obsidian-inbox sync, an iOS Shortcut for capture, inbound webhooks.
Capture→route→state→skills already exists; these are thin adapters.

---

## Explicitly NOT in Phase 3
- **Sub-agent fan-out** — backlog (raises usage; revisit when limits are comfortable).
- **Voice + ambient** — Phase 5 (docs/10).
- **Computer-use hands / autonomous project ownership** — Phase 4 (docs/09), after agency is proven.

## Recommended order
**3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6.** Cheapest/safest first (event alerts), then the compounding
self-education, then the high-value acting layer, then self-tuning, then the hand-off and interfaces.

## Decisions (settled 2026-08-20)
1. **Outbound autonomy:** **Calendar** create/update/RSVP is auto-approved (the owner's standing grant; deletes
   still confirm). **Email and job applications stay draft-only** — Kioku prepares, the owner taps send.
2. **Self-education cadence:** **weekly** (Sunday pass).
3. **Start point:** **3.1 event-driven alerts** — building first.

## Status
- **3.1 event-driven alerts — ✅ built (2026-08-20).** `alerts.watch_signals()` + `watch_signals_task`
  every 15 min: deterministic, deduped alerts on deploy down/recovered (Vercel), error spikes (Sentry),
  and new PRs (GitHub). Free (no model tokens), pausable. More rules plug in as new signals flow
  (recruiter-reply detection arrives with a Gmail signal in 3.2/3.3).
- **3.2 self-education — ✅ built (2026-08-20).** `learn_task` (weekly, Sunday 18:00 + on-demand
  `learn`): a Sonnet pass reviews the week (calendar + mail read-only + dev/ops signals) against what
  Kioku knows and PROPOSES a tightened `system/profile.md` — staged via the hash-gate for approval,
  never a silent rewrite. Writes `_reports/learn-<date>.md`; pings with the count of proposed updates.
  Router hardened so common verbs (learn/review/connect/propose) only command when bare/slash.
- **3.3 acting-with-gate — ✅ built (2026-08-20).** Two workflow **skills** (data, editable in
  `system/skills/`): `apply-to-role` (pick best-fit CV → tailor to the posting → save to
  `inbox/drafts/` + create a Gmail **draft**, never send) and `contact-prep` (People-CRM + mail +
  calendar → a one-page briefing in `_reports/`). Skills now declare their own `intent` so they get
  the right tools regardless of how the message classifies. **Email/applications = draft-only;
  calendar = act directly** (Composio; the built-in calendar tools are now honest stubs that redirect
  there). Acting policy written into the playbook. Triggers: "draft an application for …", "apply to
  …", "prep me for my call with …".
- **3.4 meta-cognition — ✅ built (2026-08-20).** `self_review_task` (weekly Sun 20:00 + on-demand
  `introspect`): **deterministic** analysis of Kioku's own `runs` (cost, errors, model mix, most
  expensive runs, avg tokens) + **skill maturation** (usage counts from `skill.used` signals → flags
  unused/prune-candidate skills) + a cheap Haiku read for concrete tuning suggestions. Writes
  `_reports/self-review-<date>.md`. Nearly free (one small model call on top of SQL).
- **Autonomy layer — ✅ built (2026-08-20).** (a) **Self-scheduling**: Kioku can create its own
  recurring tasks via `schedule_add` (5-field cron, vault-stored in `system/schedules.json`, editable);
  a per-minute tick runs due ones with the full toolset and Telegrams the result — "send me X every
  Friday" now works. (b) **System-file enforcement + cache verification**: persona/playbook/profile are
  declared binding in the cached BOOT prefix, verified present hourly (`system.files`, warns if
  missing), and cache hit-ratio is measured (`cache.usage` → self-review). (c) Playbook: schedule your
  own tasks, ask when stuck, propose fixes, curate Drive.
- **3.5 Claude Code hand-off — ✅ built (2026-08-24).** `handoff_code(task, repo, context)` +
  `handoff_status` tools (mounted for code/heavy intents) stage a job in a Redis queue
  (`memory/handoff.py`); the API exposes `/handoffs`, `/handoffs/claim`, `/handoffs/{id}/result`; a
  standalone **local runner** (`runner/kioku_runner.py`, stdlib-only) on the user's PC polls, runs
  `claude -p` inside the target repo (separate Pro pool, off the $20 credit, local-file access), and
  posts the result back → `handoff_result_task` files it to `_reports/handoff-<id>.md` + notifies.
  **User setup:** run the runner with `KIOKU_API_URL`/`KIOKU_TOKEN`/`KIOKU_REPOS` set (see
  `runner/README.md`). Drive file curation still works via Composio for cloud files.
- **3.6 interfaces breadth — deferred (optional).** Obsidian-inbox sync, iOS Shortcut capture,
  inbound webhooks — thin adapters over the existing capture→route backbone; build when wanted.
  **With 3.5 done, Phase 3 is functionally complete** (3.6 is the optional breadth tail).
