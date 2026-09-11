# Reference · Commands

## Telegram

Locked to `TELEGRAM_ALLOWED_USER_ID` (only you). Free text and files are routed automatically.

| Command | Does |
|---|---|
| `/start` | Wake it — greeting + command list |
| `/ask <text>` | Force a direct answer (bypasses the router) |
| `/audit` | Run the vault audit → `_reports/audit-<date>.md` |
| `/budget` | Current spend / remaining / mode |
| `/skills` | List learned skills |
| `/approve <sha>` | Apply a pending vault write (enqueues on the worker) |
| *plain text* | Routed by intent: capture / recall / research / code / plan / draft / automate / command |
| *send a document* (pdf/docx/txt/md) | Ingested into the brain (`sources/` + note + index) |
| *send a photo* | Ingested (image stored; text once vision is wired) |
| *"remember …", "todo …"* | Captured as a note/task card in `inbox/` |
| *"research …", "draft …", "plan …"* | Routed to the matching capability |
| *"propose a skill"* | Drafts a reusable skill from recent work → `inbox/skills/` |
| *"weekly review"* | Generates a retro → `_reports/weekly-<date>.md` |
| *"reindex"* | Rebuilds the search index |

## CLI (`kioku`)

Thin client over the API; works from any machine that can reach it. Install: `pip install -e .`

```bash
kioku ask "summarize my Acme notes"     # direct answer
echo "long text" | kioku ask -                # read prompt from stdin
kioku audit                                   # run the vault audit
kioku budget                                  # spend / remaining / mode (JSON)
kioku "remember to renew my residence card"   # no subcommand → routed by intent
```

- `ask` forces a direct answer; anything else (no recognized subcommand) goes through the intent router.
- Point it at a remote instance with `API_BASE_URL`.

## Router intents (what plain text maps to)
`recall` (question about your world) · `research` (external/deep) · `code` · `plan` · `draft` ·
`automate` · `capture` (store a note/task/person/idea) · `command` (audit/reindex/budget/review/propose).
Difficulty tiers: capture/recall/command → Haiku · draft/plan/research/automate → Sonnet · code → Opus (Fable never auto).
