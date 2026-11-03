# Security policy

Kioku drives real tools on its owner's behalf, so security reports are welcome and taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting instead:
**Security → Report a vulnerability** on this repository. Include what you found, how to reproduce
it, and what an attacker could do with it.

You'll get an acknowledgement within a few days. Fixes land with a regression test in
`tests/unit/test_security.py` and a line in [`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md).

## Scope

In scope: anything that lets untrusted text (email, web pages, notes, ingested files) or a network
client make Kioku act beyond what its owner approved — bypassing the outbound gate, escaping the
vault, writing its config spine, reaching the API without the token, or running code on the worker
or the owner's machine.

Out of scope: risks the threat model already lists as accepted, and issues that need the owner's own
credentials or a compromised host.

## Deploying safely

- Set `DASHBOARD_TOKEN` (a long random value). Without it the dashboard, CLI and runner can't reach the API.
- Set `TELEGRAM_ALLOWED_USER_ID` so the bot answers only you.
- Give connectors the narrowest scopes they offer; use a read-only role for `APP_DB_URL`.
- Never commit `.env`. CI runs gitleaks over the full history on every push.
