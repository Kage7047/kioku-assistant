# Contributing

Thanks for taking a look. Kioku is a single-owner assistant published as a reference
implementation, so the bar for changes is: small, tested, and safe by default.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
docker compose -f docker-compose.test.yml up -d --wait     # Postgres + pgvector, Redis
pytest --cov
```

No API key is needed for the tests: agent runs use a scripted model (`tests/fakes.py`).

## Pull requests

- One change per PR, with a test that fails without it.
- Anything touching tools, the vault, approvals or the API needs a test in
  `tests/unit/test_security.py` and, if it changes a control, a line in
  [`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md).
- New external capabilities default to **gated**. Make the case in the PR for anything that should run
  without approval.
- Keep secrets and personal data out of commits, fixtures and screenshots. CI runs gitleaks.

## Reporting security issues

Privately, please: see [`SECURITY.md`](SECURITY.md).
