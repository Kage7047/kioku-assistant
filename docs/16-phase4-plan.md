# Phase 4 — Agency & Character: detailed build plan  (drafted 2026-08-24)

Turns Kioku from a capable assistant into one that has a point of view, models you, acts on your
machine, and improves itself — all on the **same governor** (caps · budget guard · approval gates ·
allow-lists · git-versioned config). Voice + ambient stay in Phase 5.

**The hard line, everywhere below:** Kioku may propose changes to its *capabilities*, never to its own
*safety limits* (budget thresholds, the outbound gate, allow-lists, caps). Those live in code, not in
agent-editable config.

## Build status
- **Wave 1 (cloud-side trio) — ✅ built 2026-08-25.**
  - **4.2** `memory/patterns.py` + `db.active_hours` (tz-aware, from the runs table) → `system/patterns.json`
    (derived active-hours rhythm, editable narrative fields); loaded into every session via `_load_boot`;
    refreshed nightly by `self_heal`; `learn_task` maintains the narrative fields (draft→approve).
  - **4.4** `approvals.stage_config_edit` (a `config-edit` kind) + `execute_approved_task` applies it
    (append/create, git-versioned); `self_review_task` now proposes ONE appendable playbook lesson/week,
    staged for approval. Vault-config only → structurally can't touch code-level safety limits.
  - **4.3** `worker/interrupt.py` governor (daily interrupt budget · per-class weights · dedup · critical
    bypass); `alerts.py` fires through `notify_proactive(cls,…)`; `mute <class>`/`unmute <class>` tune it.
- **Wave 2 (machine-facing) — partial ✅ 2026-08-25.**
  - **4.5B** ✅ — hand-off queue gains a `kind`; `dev_task(kind, repo, args)` tool (run_tests / lint /
    index_repo / review_diff / scaffold); `runner/kioku_runner.py` dispatches by kind (bounded commands
    for the deterministic ones, Claude for review/scaffold/code) and REFUSES any unregistered kind.
    `open_pr`/`run_local_shell` deferred (need the approval gate).
  - **4.6** ✅ machinery — `agent/project.py` (charter model: goal/metrics/guardrails/autonomy_level/
    budget_cap_usd/checkin) + `project_manager_task` (per-project \$ cap; plan→act-by-level→report;
    outbound auto-gates) + daily `project_checkins_task` (dormant until a `projects/<name>/charter.md`
    exists). **Pilot project deferred** — Kioku researches income/business options, user sets the charter with it.
  - **4.7 computer-use — ✅ scaffold built 2026-08-25** (gated hardest). `browser_task(goal, site)` tool
    → site checked against `BROWSER_ALLOWED_SITES` (empty = refuses everything) → treated as OUTBOUND so
    it STAGES for approval → on approval queues a `kind="browser"` hand-off. Runner handler is OFF unless
    `KIOKU_BROWSER_ENABLED=1`, enforces `KIOKU_BROWSER_ALLOWED_SITES`, and its prompt forces a confirm at
    any commit step. **You finish the browser wiring** (D4: Claude-in-Chrome vs Playwright — how your
    local `claude` reaches a browser) and supervise it; it drives your real sessions. Money/legal steps
    never proceed without an explicit OK.

**Phase 4 is now functionally complete** (4.1–4.7 all built; 4.7 is a supervised scaffold you enable +
finish the browser surface on). Remaining hardening, when wanted: wire `open_pr`/`run_local_shell`
through the approval gate (4.5B), turn on bounded fan-out for 4.6 when usage headroom allows, and pick
a real pilot charter with Kioku.

---

## 0. Where we actually stand (Phase 4 already has a running start)

| Sub-phase | Spec status | Reality after Phases 1–3 |
|---|---|---|
| 4.1 Persona | seeded | ✅ **done** — `system/persona.md` loaded first every session |
| 4.2 Model of you | to build | 🟡 **partial** — `system/profile.md` + `reference/profile/*` + weekly `learn_task` exist; missing the active *patterns* model that shapes timing/routing |
| 4.3 Intelligent proactivity | to build | 🟡 **foundation exists** — `alerts.watch_signals()` fires threshold alerts; missing the judgment/interrupt layer |
| 4.4 Self-improvement loop | to build | 🟡 **half** — `self_review_task` analyses runs + flags issues; missing the propose-a-config-edit → approve → apply loop |
| 4.5A Claude Code hand-off | to build | ✅ **done (Phase 3.5)** — `handoff_code` + local runner shipped |
| 4.5B Delegated dev-task runner | to build | ⬜ new — extends the 3.5 runner with allow-listed dev tasks |
| 4.6 Autonomous project ownership | to build | ⬜ new — needs a charter model + a PM loop; touches the parked fan-out |
| 4.7 Computer-use hands | to build | ⬜ new — browser agent on the local runner; highest risk, built last |

**So the real Phase 4 work is: deepen 4.2, build 4.3 · 4.4 · 4.5B · 4.6 · 4.7.**

---

## Cross-cutting design decisions (settle these first)

1. **Budget model for autonomous coding (4.5B/4.6/4.7).** Two pools: the **$20 Agent-SDK credit**
   (Kioku's cloud brain) and your **local Claude Code Pro pool** (the 3.5 runner). *Recommendation:*
   route heavy/iterative autonomous work through the **local runner's Pro pool** wherever possible
   (off the $20), and reserve the Agent-SDK credit for orchestration/decisions. This keeps Phase 4
   affordable — the single biggest risk to this project is burning the $20 or the 5-hr window.
2. **Sub-agent fan-out (needed by 4.6).** Currently parked (raises usage). 4.6 can ship a **linear
   (no-fan-out) PM loop first** and turn on bounded fan-out later, per your call, behind the existing
   `SUBAGENTS_ENABLED` + per-run \$ cap. *Recommendation:* linear first.
3. **Self-edit gate (4.4).** Config self-edits must be **staged for approval**, not applied silently.
   *Recommendation:* reuse the **approvals queue** built in this session (a new `config-edit` kind) so
   proposed diffs to `system/` show in the command center + Telegram `/approve <id>`.
4. **Where computer-use runs (4.7).** The Railway worker has no browser; your PC does. *Recommendation:*
   computer-use runs on the **local runner** (Claude-in-Chrome or a Playwright MCP there), never on the
   cloud worker.

---

## 4.2 — A model of you (deepen)  · effort: medium · risk: low (privacy)

**Goal:** move from *facts* about you to a model of your *patterns* — energy rhythm (sharp mornings),
what you avoid (admin), decision style, over-commitment tendency — and actually **use** it to shape
timing, nudges, and routing.

**Build:**
- `reference/profile/patterns.md` — a structured, human-readable, **editable** patterns note
  (frontmatter: `energy_peak`, `avoids`, `decision_style`, `overcommit_risk`, `best_nudge_times`, …),
  seeded from the existing `*_detailed.md` + journal, refreshed by `learn_task`.
- Extend `learn_task` (weekly) to derive patterns **deterministically first** (run timestamps →
  active-hours histogram; recurring "later"/"skip" language → avoidance list) and only then a cheap
  Haiku pass to phrase them. Proposals stay **draft→approve** (never silent).
- Wire it in: `_load_boot` already loads `profile.md`; add a compact patterns digest to the boot
  context; `morning_brief`/`propose_ideas`/scheduler read `best_nudge_times`.

**Acceptance:** nudges/briefs land in your actual active windows; you can open and correct
`patterns.md`; a wrong pattern you edit stays corrected (learn_task doesn't re-overwrite an edit).

**Files:** `agent/…learn` (existing task), `reference/profile/patterns.md`, small `_load_boot` add.

---

## 4.3 — Intelligent proactivity (judgment, not thresholds)  · effort: medium-high · risk: annoyance

**Goal:** decide **whether** to interrupt, not just detect a threshold. "Recruiter call in 20 min,
brief unopened." "Six projects touched, nothing shipped — pick one?" Quiet by default; earn interrupts.

**Build:**
- `worker/interrupt.py` — a deterministic **priority/interrupt scorer**. Inputs: recent signals,
  calendar proximity, budget mode, your `patterns.md` state, and an **interrupt budget** (e.g. ≤N
  proactive pings/day, Redis-counted). Output: for each candidate, a score; notify only if
  `score ≥ threshold` AND interrupt budget remains.
- Candidate sources (all already flowing): calendar events within X min, unopened brief, deploy
  down, error spike, deadline < 3 days, opportunity ≥ fit floor, "many projects touched, none shipped".
- **Feedback loop:** each interrupt Telegram offers `snooze`/`not useful`; a `not useful` on a class
  lowers that class's weight (stored in Redis/`system/interrupt-weights.json`). False interrupts fall
  over time.
- Runs inside the existing `watch_signals_task` (every 15 min) — deterministic, ~zero model cost.

**Acceptance:** interrupts are rare and mostly right; a daily cap holds; marking one "not useful"
measurably reduces that class; sensitivity is tunable.

**Files:** `worker/interrupt.py`, hook in `worker/alerts.py`/`watch_signals_task`, Telegram
snooze/feedback handlers, `system/interrupt-weights.json`.

---

## 4.4 — Self-improvement that closes the loop  · effort: medium · risk: drift (gated)

**Goal:** Kioku spots its own failure patterns and proposes concrete fixes to its **own config** —
a router rule, a new skill, a prompt tweak — which you approve, then it applies via the write gate.

**Build:**
- Extend `self_review_task` (weekly): after the deterministic run analysis, add a pass that reads the
  week's **errors + turn-capped runs + misroutes** and proposes 0–3 concrete config diffs, each with
  a rationale and the exact file/lines (`agent/router.py` rule, a new `system/skills/*.md`, a
  `system/playbook.md` line).
- **Staging = the approvals queue** (built this session): a new `config-edit` approval kind holds
  `{target_path, diff, rationale}`; it surfaces in the command center + `/approve <id>`. On approval,
  `execute_approved_task` applies the edit (git-versioned → revertible) and notifies.
- **Guardrail (enforced in code):** the proposer may target `system/` config, skills, playbook, and
  router *rules data* — but a denylist blocks any edit to budget thresholds, the outbound gate, caps,
  and allow-lists. It proposes capabilities, never safety limits.
- Measure: tag the failure class each fix targets; the next self-review reports whether that class's
  rate dropped.

**Acceptance:** ≥1 concrete, rationale-backed self-improvement proposed/week; approved changes cut a
failure class measurably; everything reverts via git; safety-limit edits are refused.

**Files:** `worker/tasks.self_review_task` (extend), `memory/approvals.py` (+`config-edit` kind),
`execute_approved_task` (apply a config edit), a small code denylist for safety-limit paths.

---

## 4.5B — Delegated autonomous dev-task runner  · effort: medium-high · risk: high (allow-list)

**Goal:** beyond the interactive hand-off (4.5A, done), a runner that executes **registered dev tasks**
directly on your repo/disk/toolchain and reports back — a coding agent working on your machine,
orchestrated by Kioku.

**Build (extends `runner/kioku_runner.py`):**
- A **registered dev-task allow-list** — the runner runs ONLY these, never arbitrary shell:
  `index_repo` · `run_tests` · `lint` · `review_diff` · `scaffold` (your house style) ·
  `open_pr` (**gated**) · `run_local_shell` (strict per-command allow-list, **gated**).
- Kioku side: a `dev_task(kind, repo, args)` tool (mounted on code/automate) → the handoff queue
  gains a `kind` field; the runner dispatches by kind to a typed handler (each handler a known,
  bounded command — `pytest`, the linter, `git diff`, a scaffold template — **not** free-form).
- **Two engines, your call per task:** `run_tests`/`lint`/`index_repo` are deterministic (no model);
  `review_diff`/`scaffold` can run through the **local Claude Code Pro pool** (off-budget) or a
  budget-guarded Agent-SDK session. *Recommendation:* Pro pool for the model-y ones.
- **Gates:** `open_pr` and `run_local_shell` stage an approval (the same queue) before executing; the
  runner refuses any kind not in the allow-list and any shell command not in its command allow-list.
- Optional (**4.5B-full**): a real **Celery worker on your PC** on a machine-specific queue (Tailscale
  or Railway Redis TCP proxy) so Kioku can dispatch without the poll loop. *Recommendation:* keep the
  simpler **poll-based runner** first; add the Celery variant only if you want push-latency.

**Acceptance:** dispatching `run_tests` on the local machine runs pytest there and reports pass/fail;
`review_diff` returns a review; the runner refuses an unregistered kind; `open_pr` stops for approval.

**Files:** `agent/tools/devtask.py`, `memory/handoff.py` (+`kind`), `runner/kioku_runner.py`
(typed handlers + allow-list), approvals for `open_pr`/`run_local_shell`.

---

## 4.6 — Autonomous project ownership (the endgame)  · effort: high · risk: cost/direction

**Goal:** hand Kioku a bounded goal ("Acme's first 10 paying users", "ship the MVP")
and it runs a **plan → work → measure → weekly report → approve big moves → adjust** loop over weeks.

**Build:**
- `projects/<name>/charter.md` — `goal` · `success_metrics` · `guardrails` · `autonomy_level`
  (advise / draft / act-low-risk) · `budget_cap_usd` · `checkin_cron`.
- `project_manager_task(name)` — scheduled per charter: reads the charter + project notes + metrics
  signals → produces `projects/<name>/plan-<date>.md` (next steps, ranked) → executes **low-risk**
  steps within the autonomy level (draft outreach, run a dev task, schedule a follow-up) → stages the
  rest for approval → weekly `_reports/project-<name>-<date>.md` + Telegram.
- **Budget:** a per-project aggregate \$ cap (Redis-tracked, checked pre-flight); pauses + notifies at
  the cap. Weekly checkpoints; gates on anything irreversible.
- **Fan-out:** ships **linear first** (one loop, sequential). Bounded fan-out (`SUBAGENTS_ENABLED` +
  per-run cap) is a later flip *only when your usage headroom is comfortable* — this is the #1 cost risk.

**Acceptance:** given a charter, produces a weekly plan+report, executes low-risk steps, stops for
approval on the rest, respects the per-project cap, and adapts to the metrics.

**Files:** `worker/tasks.project_manager_task`, `agent/project.py` (charter parse + loop),
`system/skills/run-project.md` (exists — evolve it), per-project budget in `memory/budget.py`.

**Decision needed:** which 1 project to pilot (recommend Acme-first-users or a revenue sprint),
and its starting autonomy level (recommend **draft**, i.e. it prepares everything, you approve moves).

---

## 4.7 — Computer-use hands (the last mile)  · effort: high · risk: highest · built LAST

**Goal:** actually *do* the web tasks Kioku can only draft today — book, fill a form, navigate the
a residence/tax portal, submit — with a human confirm at the commit step, always.

**Build (on the LOCAL runner — your PC has the browser):**
- A browser capability on the runner: **Claude-in-Chrome** (your logged-in sessions) or a **Playwright
  MCP** in a profile you control. Kioku dispatches a `browser_task(goal, site)` (allow-listed sites).
- **Safety, hardest tier:** site **allow-list**; **dry-run/preview** of the intended actions before
  any click; a **human confirm at the commit step ALWAYS** (submit/pay/book) via the approvals queue;
  **never autonomous for money or legal** — those require an explicit per-action tap.
- Runs off the local Pro pool (Claude-in-Chrome) — off the $20.

**Acceptance:** completes a bounded, allow-listed web task end-to-end with a human confirm at commit;
refuses off-allow-list sites; a money/legal step cannot proceed without an explicit tap.

**Files:** runner browser handler, `agent/tools/browser.py` (dispatch), site allow-list in
`connectors.yaml`/config, commit-step approvals.

---

## Recommended build order (cheap→risky, budget-aware)

1. **4.2 deepen** (model-of-you patterns) — cheap, compounding, low risk. *~a day.*
2. **4.4 self-improvement loop** — reuses the approvals queue; cheap; makes everything after it better. *~1–2 days.*
3. **4.3 intelligent proactivity** — mostly deterministic; high daily value; tune the interrupt budget. *~2 days.*
4. **4.5B dev-task runner** — extends the shipped 3.5 runner; off-budget via the Pro pool; unlocks real coding help. *~2–3 days.*
5. **4.6 project ownership (linear)** — the endgame; pilot ONE project at autonomy=draft; strict per-project cap. *~3–4 days.*
6. **4.7 computer-use** — built last, gated hardest; only after 4.5B's runner + gates are proven. *~3–4 days.*

Fan-out for 4.6 and any Agent-SDK-credit autonomy stay **off until you say usage headroom is comfortable**.

## Open decisions for you
- **D1 — Budget routing:** confirm autonomous coding prefers the **local Pro pool** over the $20 credit. *(rec: yes)*
- **D2 — Fan-out:** linear 4.6 first, flip bounded fan-out later? *(rec: yes)*
- **D3 — Pilot project for 4.6:** which one, and at what autonomy level? *(rec: Acme-first-users, autonomy=draft)*
- **D4 — Computer-use surface:** Claude-in-Chrome (your sessions) vs a dedicated Playwright profile? *(rec: Claude-in-Chrome, allow-listed)*
- **D5 — Scope for this pass:** all of 4.2–4.7, or land 4.2+4.4+4.3 first and review before the machine-facing 4.5B/4.6/4.7?
