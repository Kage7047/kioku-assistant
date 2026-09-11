# Kioku local hand-off runner (Phase 3.5)

Lets Kioku dispatch **heavy coding** to Claude Code on *your* machine — a separate interactive Pro
pool (not the $20 Agent-SDK credit), at full quality, with access to your **local files**. Kioku
scopes the task; this runner executes it and sends the result back to the vault + Telegram.

## How it flows
1. In Telegram you ask for something heavy — e.g. *"hand off to Claude Code: refactor the billing
   module in acme"*. Kioku calls its `handoff_code` tool → the task lands in a queue.
2. This runner (on your PC) polls `GET /handoffs/claim`, claims the task, and runs
   `claude -p "<task>"` inside the target repo.
3. It posts the result back; Kioku files it to `_reports/handoff-<id>.md` and pings you.

Nothing runs unless this script is running — so your PC never needs to be always-on.

## Setup
Requires: Python 3.10+, the `claude` CLI installed and logged in (`claude` / `claude setup-token`).

Set these environment variables (the token is the `DASHBOARD_TOKEN` you set on the api service):

```bash
export KIOKU_API_URL="https://<your-kioku-api-domain>"
export KIOKU_TOKEN="<your DASHBOARD_TOKEN>"
export KIOKU_REPOS="kioku=/path/to/kioku;acme=/path/to/acme"
# optional:
export KIOKU_DEFAULT_DIR="/path/to/code"
export KIOKU_CLAUDE_ARGS="--permission-mode acceptEdits"   # or bypassPermissions if you trust it fully
export KIOKU_POLL_SECONDS=30
```

Then run it (leave it running while you want hand-offs to execute):

```bash
python runner/kioku_runner.py
```

## Dev tasks (Phase 4.5B)
Beyond free-form `handoff_code`, Kioku can dispatch **registered** dev tasks the runner runs on your
repo: `run_tests`, `lint`, `index_repo`, `review_diff`, `scaffold`. The runner executes ONLY these
kinds and refuses anything else. Configure the deterministic ones:

```bash
export KIOKU_TEST_CMD="pytest -q"       # your project's test command
export KIOKU_LINT_CMD="ruff check ."    # your linter
```

`run_tests`/`lint`/`index_repo` run those bounded commands (no model); `review_diff`/`scaffold`/
free-form `code` run Claude Code. `open_pr` and `run_local_shell` are intentionally **not** enabled
yet — they need the approval gate wired first.

## Computer-use / browser tasks (Phase 4.7 — OFF by default)
Kioku can dispatch a real browser action (fill a form, book, submit) via `browser_task`. It's gated
hardest: staged for your approval, allow-listed sites only, and it runs here only if you opt in:

```bash
export KIOKU_BROWSER_ENABLED=1
export KIOKU_BROWSER_ALLOWED_SITES="example.com,example.org"   # domains it may drive; nothing else
```

Your local `claude` must have a way to reach a browser (Claude-in-Chrome, or a Playwright MCP) — that's
your call. The task prompt forces a stop-for-confirmation at any commit step (submit/pay/book), and it
drives YOUR real logged-in sessions, so **supervise it**. Leave `KIOKU_BROWSER_ENABLED` unset to keep
it fully disabled.

## Safety
- The runner only runs tasks **you** initiated through Kioku; Kioku dispatches, it doesn't invent work.
- `--permission-mode acceptEdits` (the default) auto-accepts file edits but still gates other actions.
  Use `bypassPermissions` only if you're comfortable with fully-autonomous edits on the mapped repos.
- A hand-off naming an unknown repo runs in `KIOKU_DEFAULT_DIR`; keep that to a safe sandbox.
- Each task is capped at `KIOKU_TASK_TIMEOUT` seconds (default 1h).
