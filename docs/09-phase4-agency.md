# Phase 4 — Agency & Character (NEXT VERSION)

The version that turns Kioku from a capable assistant into one that has a point of view,
understands you, acts on your machine, and improves itself — all behind the existing governor
(caps · budget · approval gates · allow-lists · git-versioned config). Voice + ambient are
deliberately deferred to Phase 5.

Ordering: cheap→risky. Persona (seeded now) → model-of-you → intelligent proactivity →
self-improvement → local coding agent → autonomous project ownership → computer-use hands.

---

## 4.1 Persona — a persistent character  (SEEDED)
A `system/persona.md` loaded first every session (already wired into `_load_boot`): how it
addresses you, its humor, when it's terse vs warm, when it pushes back, its opinions. This is
what turns "an assistant" into *your* assistant. Effort: tiny. Risk: none.
**Acceptance:** editing `persona.md` visibly shifts tone/behaviour; voice is consistent across sessions.

## 4.2 A model of you  (`system/profile.md` + profile layer)
Beyond facts — a model of your *patterns*: energy rhythms (sharp mornings), what you avoid
(admin), your decision style, your tendency to over-commit. Built from the journal + feedback
over time; also loaded by `_load_boot`. Used to shape scheduling, nudges, and routing.
Effort: medium. Risk: privacy/accuracy → keep it **transparent and editable** (you can read and
correct what it thinks). **Acceptance:** it adapts timing/nudges to your patterns; you can inspect/edit the model.

## 4.3 Intelligent proactivity (judgment, not thresholds)
The nervous system already fires threshold alerts. This adds *judgment*: a priority/interrupt
model over signals + your state that decides **whether** to interrupt. "Recruiter call in 20 min,
brief unopened." "Six projects touched, nothing shipped — pick one?" Builds on the proactive loop
+ 4.2. Effort: medium-high. Risk: annoyance → **quiet by default, earn interruptions**, with a
snooze/feedback loop. **Acceptance:** interrupts are rare and right; sensitivity is tunable; false interrupts fall over time.

## 4.4 Self-improvement that closes the loop
Weekly reflection (extends `weekly_review_task`) reviews failures + journal, spots patterns
("I keep misrouting these"), and proposes concrete fixes to its **own config** — a router rule, a
new skill, a prompt tweak — which you approve, after which it edits its configuration via the
same plan→approve write gate on `system/`. Effort: medium. Risk: drift → every self-edit is gated,
git-versioned (revertible), and **it may propose changes to its capabilities but never to its own
safety limits.** **Acceptance:** ≥1 concrete self-improvement/week with rationale; approved changes
measurably cut a failure class; all changes revert via git.

## 4.5 Local coding agent (on your machine)  ← the "coding agent" you asked about
Two mechanisms, two meanings of "my coding agent," both running on your hardware:

**A. Interactive + supervised → hand off to Claude Code.**
Kioku doesn't try to out-code Claude Code — the Agent SDK *is* its engine. For pairing sessions,
Kioku dispatches `handoff_to_claude_code(repo, task)`, which runs a supervised Claude Code session
on your laptop. Key: this draws on your **separate interactive Pro pool**, not the $20 Agent SDK
credit — heavy coding never touches Kioku's budget.

**B. Delegated + autonomous → a local runner.**
A Celery worker on your local machine / laptop, connected outbound to Redis on a machine-specific
queue (via Tailscale, or Railway's Redis TCP proxy). Kioku dispatches a coding task → it runs an
**Agent SDK session against your actual repo, on your disk, with your toolchain**, and reports back.
That's a coding agent working directly on your machine, orchestrated by Kioku.

**Registered dev tasks** (allow-listed — a runner runs ONLY these, never arbitrary shell):
`index_repo` · `run_tests` · `lint` · `review_diff` · `scaffold` (your house style) ·
`open_pr` (gated) · `run_local_shell` (strict command allow-list, gated).

The split: *interactive/supervised* → Claude Code (Pro pool); *delegated/autonomous* → runner
(Agent SDK credit, budget-guarded). Both on your machine; they differ only in whether you're driving.
Effort: medium-high. Risk: high → allow-list only, destructive/PR/spend actions hit an approval gate,
Tailscale ACLs tight. **Acceptance:** dispatching `run_tests` executes on the local machine and reports
back; the runner refuses any unregistered command; `open_pr` stops for approval; a Claude Code hand-off completes and posts its result.

## 4.6 Autonomous project ownership  (the endgame)
Hand Kioku a bounded goal ("Acme's first 10 paying users", "ship the MVP") via a
`projects/<name>/charter.md` (goal · metrics · guardrails · autonomy level). A project-manager agent
runs on a schedule: **plan → spawn work (fan-out) → measure vs metrics → weekly report → approval on
big moves → adjust**, over weeks. Supervised first; autonomy earned per-project. Builds on
orchestration + fan-out + budget + gates + journal + 4.5. Effort: high. Risk: cost/direction →
aggregate budget cap per project, weekly checkpoints, gates on anything irreversible.
**Acceptance:** given a charter, it produces a weekly plan+report, executes low-risk steps, stops for
approval on the rest, and adapts to the metrics.

## 4.7 Computer-use hands  (the last mile — built last, gated hardest)
A browser agent (Claude-in-Chrome / Playwright MCP) that *does* the last mile Kioku currently can
only draft: books the reservation, fills the form, navigates a residence/tax portal,
submits the application. Effort: high. Risk: **highest** → site allow-list, dry-run/preview before
acting, a human confirm at the commit step **always**, never autonomous for money/legal.
**Acceptance:** completes a bounded web task end-to-end with a human confirm at commit; refuses off-allowlist sites.

## The governor scales with autonomy
Everything above rides the same rails already built: pre-flight + post-run **budget guard**,
**caps** on every run, **approval gates** for writes/money/messages/bookings/PRs, **allow-lists**
for local runners and computer-use, and **git-versioned config** so any change reverts. The hard
line: **Kioku may propose changes to its capabilities, never to its own safety limits.** That's what
makes full agency safe rather than terrifying.

## Dependencies
Phase 4 assumes Phase 1 fully wired and Phase 2's **command center** (you need a real surface to
supervise autonomous work, approve computer-use, and watch project loops). Persona (4.1) is already
seeded and usable now.
