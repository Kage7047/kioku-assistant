# Interfaces & Making Kioku Universal

## Interfaces (input surfaces)

You have Telegram (built, now in the API process) and the Next.js dashboard (Phase 2). Ranked
by fit × effort for how you actually work:

| Interface | Fit | Effort | Notes |
|---|---|---|---|
| **CLI** (`kioku ask …`) | ★★★ | done | You live in a terminal; pipe files in, script it. Built. |
| **Obsidian inbox** | ★★★ | low | Write a `?` line / drop a note in `inbox/`; a Beat job answers it *inside the vault* where you already work. The most on-brand interface. |
| **iOS Shortcut** | ★★★ | low | A Shortcut that POSTs to `/tasks` gives you "Ask Kioku" + Siri on the **iPad** (which can't host a worker). Turns the iPad from client into input. |
| **Programmable API / webhooks** | ★★★ | tiny | The FastAPI *is* an interface — with an auth token, Acme, cron, or any script can call Kioku. Basically free. |
| **Email in** | ★★ | med | Forward things to a dedicated address → capture / read-it-later / reply. Uses the Gmail connector inbound. |
| **Voice via Telegram** | ★★ | med | Transcribe Telegram voice notes (hosted STT) → task. Cheapest path to voice before the Phase 3 Vosk work. |
| **Browser extension / bookmarklet** | ★★ | med | "Send this page/selection to Kioku" for research + capture. |
| **Linux quick-ask hotkey** | ★★ | low | rofi/GTK popup bound to a global key → `/tasks`. Spotlight-for-Kioku on the laptop. |
| **Slack** | ★ | low | Only if you want a work-workspace surface; Telegram already covers personal. |

## Feeding the brain (ingestion) — BUILT
You can now hand Kioku a file or photo and it learns on the fly:
- **Telegram** — send a document (pdf/docx/txt/md) or a photo → it saves an immutable copy in
  `sources/`, extracts text, files a note in `inbox/`, indexes it, and pushes. (`on_document`/`on_photo`)
- **Dashboard / any client** — `POST /ingest` (multipart) does the same.
- **Obsidian** — dropping a file in the vault is native; the nightly index picks it up.
- **Claude Code (local)** — reads files directly, as before.
Text/PDF/DOCX extract fully today; **images** are stored with a vision-transcription step to wire
against your pinned SDK (until then the image is kept and marked pending — never fake text).
Voice notes are the next slot (needs STT). Design: `agent/ingest.py`.

The pattern: **every interface is a thin client over the same `/tasks` + SSE + `/ingest` API.** Add surfaces
freely; none of them contain logic. Output channels (Telegram push, morning brief, dashboard,
email digest) are the mirror image.

## What makes it *universal* (not just a pile of features)

Universality doesn't come from 50 features — it comes from a few composable primitives plus a
skill library that grows. Build the backbone; domain features hang off it.

### The backbone (build these; everything else plugs in)
1. **Universal capture + triage.** One inbox for every input (Telegram/voice/email/CLI/Obsidian/
   browser). Kioku classifies each: task? note? person-update? project signal? someday-idea? and
   routes it. One door for all your thoughts.
2. **Intent router.** A cheap Haiku classifier reads any request and dispatches to the right
   capability (code / research / plan / draft / recall / automate) — you never pick a "mode."
3. **Unified project + goal state.** One layer spanning **work and personal**: every active thread
   (Acme, your goals, studies, side projects, life admin) with status / next-action /
   blocker, tied to quarterly goals. This is what makes it *your* system, not a chatbot.
4. **Self-authored skill library.** Kioku writes reusable sub-agent/skill definitions for tasks it
   repeats, and grows more capable without you coding. This is the engine of "universal."
5. **Proactive nervous system.** The always-on cheap loop that watches signals and surfaces things
   unprompted (deadline, recruiter reply, error spike, budget mode, a friend's birthday).

### Domain capabilities (hang off the backbone)

**Work**
- Acme co-pilot: feedback→backlog, changelog from git, support drafts, competitor/SEO watch.
- Code intelligence: repo-aware Q&A across your repos, PR review, CVE/dependency watch, house-style
  scaffolding, "explain this old project."
- Freelance ops: proposals, scoping, invoices, client comms; job-search CRM + follow-ups.
- Study system: curriculum + spaced repetition + exam/deadline tracker + cybersec practice.
- Security-posture agent: watch your exposed services + stack CVEs.

**Personal**
- Relationship/collab hub: shared project tracker, date planning, gift intelligence.
- Life-admin ops: draft correspondence, track tax/registration deadlines,
  explain bureaucracy, appointment booking, document tracking.
- Finance & runway: net-worth view, runway calc, invoice/subscription tracking.
- Travel & logistics (Booking.com); light health/routine rhythm-keeper; ambient apartment (P3).

**Meta (compounding)**
- Decision journal + failure log; contradiction flags vs past decisions.
- Goal/OKR tracking with weekly check-in and drift alerts.
- Personal knowledge graph (projects/people/concepts/decisions, queryable).
- Automation recipes Kioku authors from repeated patterns.

### Staying universal without becoming unmaintainable
- **Capabilities are code; specifics are data** (`connectors.yaml`, vault, boot memory). Dead things
  cost a deleted line, never a refactor.
- **Every capability is a skill/sub-agent** behind the intent router — add without touching the core.
- **One API, many thin clients.** Interfaces never hold logic.
- **The budget guard is the governor** — universality can't blow the credit because every run is
  pre-flighted and routed by cost.
