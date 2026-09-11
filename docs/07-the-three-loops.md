# The Three Loops — the "J.A.R.V.I.S." architecture

"A never-sleeping assistant that learns and gets better" isn't magic; it's three loops running
on the backbone. Named plainly so it's buildable, not vibes.

## 1. Reactive loop — "you just talk, it acts"  (BUILT: capture + router)
Any input (Telegram / CLI / Obsidian / email / webhook) hits **one entry** and the **intent
router** decides what you want — no modes.

```
input ──► /inbox or /tasks(kind=input) ──► handle_input_task
                                              │
                 router.classify(text)  ──────┤
                                              ├─ capture  → file a note/task/person/idea into the vault
                                              ├─ command  → audit / reindex / budget
                                              └─ recall/research/code/plan/draft/automate
                                                          → run_agent (priced by intent's difficulty)
```
- `agent/router.py` — fast heuristic + cheap Haiku classify (fallback-safe). 8 intents.
- `agent/capture.py` — universal capture → structured card in `inbox/` (vault = truth).
- Every surface is a thin client; the brain lives in one place.

## 2. Proactive loop — "always watching"  (BUILT)
The nervous system runs on Celery Beat and surfaces things unprompted.
- Built: **poller registry** (`worker/pollers.py`) driven by `connectors.yaml` — `self` is real,
  others raise until wired (never fake data); **alert engine** (`worker/alerts.py`) with a real,
  no-external-deps **deadline scanner** over vault `due:`/`deadline:` dates; morning brief; nightly
  reindex; vault sync. Beat runs poll-all hourly + alerts each morning.
- Next: real adapters for gmail/sentry/vercel/indeed (drop into the registry); more alert rules.
- Governor: the budget guard pre-flights every run, so "always on" can't drain the credit —
  non-essential loops pause first.

## 3. Learning loop — "gets better"  (BUILT)
Compounding memory so tomorrow's Kioku is smarter than today's.
- **Built:** `agent/journal.py` (decision journal after substantial runs → indexed → recallable);
  **self-authored skill library** (`agent/skills.py`) — skills are markdown cards in
  `system/skills/`, matched by the router *before* the generic agent, so Kioku applies learned
  workflows automatically; **`propose_skill_task`** drafts a new skill from recent journal work into
  `inbox/skills/` for you to approve (move it into `system/skills/` to activate — gains capability
  without you coding); **`weekly_review_task`** writes a retro and chains a skill proposal.
- **Next:** claim-ledger contradiction sweep; a thumbs up/down feedback signal to tune routing.

## Why this is the whole game
- Loop 1 makes it feel like **one mind** instead of a command palette.
- Loop 2 makes it **present** instead of waiting to be asked.
- Loop 3 makes it **yours and improving** instead of static.
All three ride the same primitives (capture → route → orchestrate → remember) and the same safety
governor (caps + budget + approval gates), so it scales in capability without scaling in risk or cost.
