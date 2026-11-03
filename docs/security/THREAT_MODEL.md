# Threat model

Kioku is an agent that reads untrusted text (email, web pages, ingested files) and holds tools that
act on the world (send mail, drive a browser, run Claude Code on the owner's machine). The central
question is therefore not "can the model be tricked?" — assume it can — but **what can a tricked
model actually do?** Every control below is enforced in code, outside the model, and pinned by a
regression test in [`tests/unit/test_security.py`](../../tests/unit/test_security.py) (test names
start with the finding id).

## Assets

| Asset | Why it matters |
|---|---|
| The owner's accounts behind connectors (mail, calendar, drive, chat) | Sending, sharing or deleting as the owner |
| The owner's machine, via the local runner | Open-ended Claude Code sessions with local file access |
| The vault's `system/` spine (persona, playbook, profile) | Loaded into every run: a rewrite persists as a standing injection |
| The vault's `.git/` | `core.fsmonitor` / `core.hooksPath` run commands on the worker at the next commit |
| The API and its token | Full control: tasks, approvals, pause |
| The monthly agent credit | Runaway loops burn real money |

## Actors and trust boundaries

```
 owner ──(Telegram, locked to one user id / dashboard token)──▶ API ──▶ worker ──▶ model
                                                                          │
   untrusted text ─▶ email · web pages · ingested files · notes ─────────┘  (reaches the prompt)
                                                                          │
                                       tool calls ─▶ [ outbound gate ] ─▶ connectors · runner · browser
```

- **Trusted:** the owner, the code, the deployment's environment.
- **Untrusted:** everything the model reads. Any of it can contain instructions.
- **The boundary that matters is the outbound gate**, a `can_use_tool` callback the SDK calls before
  any tool that isn't pre-approved. No text in the prompt can lift it.

## Findings and controls

| Id | Finding (before) | Control (now) |
|---|---|---|
| T1 | The `system/` guard checked the path *as written*, so `inbox/../system/persona.md` or a symlink could delete or move the config spine | All vault operations resolve the path first, then check the zone |
| T2 | `vault_write` could overwrite `system/` (a persistent injection) and `.git/config` (code execution on the worker at the next commit) | `.git/` is never writable; `system/` needs `approved=True`, which only trusted internal writers and an owner-approved config edit pass. Moves *into* either zone are refused |
| T3 | If staging an approval raised (e.g. Redis down), the gate returned **Allow** | The gate fails closed: any error → Deny, "it did NOT run" |
| T4 | Outbound tools were found by a name deny-list (`send`, `post`, `delete`…). `REPLY_TO_THREAD`, `FORWARD_MESSAGE`, `INVITE_USER`, `CREATE_ISSUE_COMMENT` slipped through | External tools are **default-deny**: free only if the action is clearly a read (`GET`, `LIST`, `SEARCH`, `FETCH`…) or a draft. Write verbs beat read verbs. Calendar events are free unless they invite someone |
| T5 | If the SDK lacked the permission callback, the run fell back to `bypassPermissions` **with connectors mounted** | Without a gate, connectors and hand-off tools are not mounted at all; an approved action refuses to run |
| T6 | `handoff_code`, `dev_task` and `browser_task` were in `allowed_tools`, which the SDK auto-approves **without calling the gate** — so they never asked, despite comments saying they did | Only `handoff_status` is pre-approved; the rest reach the gate. `handoff_code`, `browser_task` and `dev_task(scaffold)` are staged for approval |
| T7 | The browser allow-list matched substrings: `linkedin.com.evil.io` passed for `linkedin.com`, and an empty site passed | Hostname matching: exact host or a subdomain of an allow-listed host; empty never matches. Same rule in the runner |
| T8 | Token compared with `==`; with no token set the API was open to anyone who could reach it | `hmac.compare_digest`; with no token only loopback clients pass (the in-process bot, a local CLI) unless `ALLOW_UNAUTHENTICATED=1` |
| T9 | Retrieved notes were pasted into the prompt as plain text | Excerpts are fenced as `<vault_excerpt>` *data* and a note cannot close the fence. Defence in depth only — the gate is the control |
| T10 | `/approve <prefix>` accepted any prefix, even one character, and took the first match | At least 6 characters and unique; ambiguous → nothing |
| T11 | An approved action re-ran the model with `bypassPermissions`: the "call this one tool" constraint lived only in the prompt, which also contained the (attacker-influenced) staged arguments | The approved run gets a gate that allows **exactly** the approved tool with **identical** arguments, **once**, and pre-approves nothing |

## Residual risks (accepted, documented)

- **Exfiltration through reads.** `WebFetch` is free, so a tricked model could encode vault content
  into a URL it fetches. Mitigations if this matters for your deployment: an egress allow-list on
  the worker, or gating `WebFetch` for runs that ingested untrusted content.
- **Vault vandalism.** The vault is deliberately free for the model to curate, so an injection can
  write junk notes or delete non-protected ones. The vault is git-backed: every change is revertible.
- **Connector scope.** Kioku is only as constrained as the connector credentials you give it. Grant
  the narrowest scopes your provider offers (read-only database roles, no bank transfer scope —
  the bank poller has no transfer code at all).
- **The runner trusts approved tasks.** It runs `claude -p` with `--permission-mode acceptEdits` in
  the mapped repo. Keep `KIOKU_REPOS` to repos you are happy to have edited; leave browser tasks off
  (`KIOKU_BROWSER_ENABLED` unset) unless you supervise them.
- **Telegram.** The bot answers only `TELEGRAM_ALLOWED_USER_ID`; anyone holding the bot token can
  still impersonate the bot to you. Treat the token as a secret.

## Reporting

See [`SECURITY.md`](../../SECURITY.md).
