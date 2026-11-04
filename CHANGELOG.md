# Changelog

All notable changes. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-04

First tagged release of the reference implementation.

### Added
- **Test suite**: 220+ unit tests with a scripted stand-in for the Agent SDK (whole agent runs,
  deterministic, no API key) and integration tests on real Postgres + pgvector and Redis, in CI
  with coverage.
- **Threat model** (`docs/security/THREAT_MODEL.md`), `SECURITY.md` with private vulnerability
  reporting, `CONTRIBUTING.md`, and a regression test for every finding.
- **Retrieval evaluation** (`eval/`): 40 labelled queries — exact, paraphrase, cross-lingual,
  vague — over a fictional sample vault, against the production retrieval code.
- **`make demo`**: the real stack with a stub model; no API key. CI boots it and asks it a question.
- **Command center** rebuilt with Vite + React, GSAP, Lenis and React Bits, served same-origin;
  adds a knowledge graph drawn from real vault stats.
- Architecture decision records (`docs/adr/`), mypy on the typed core, project lint rules in CI.
- Container image on GHCR, signed with cosign, with an SBOM and build provenance.

### Fixed
- **Security** — the vault's protected zones could be reached with `..` or a symlink, and
  `.git/config` was writable (code execution on the next commit); reply / forward / invite tools
  ran without approval; hand-off tools that act on the owner's machine were auto-approved without
  ever reaching the gate; the gate failed open; an approved action re-ran with every check off; the
  API was open when no token was set; the browser allow-list matched substrings.
- **Budget** — spend was over-counted (each API response counted several times, then the session
  total on top), so the guard degraded early; cache reads and writes were not priced.
- **Retrieval** — hybrid search lost to vector search alone (recall@5 0.82 vs 0.97). Function words
  are now dropped inside hybrid search and lexical evidence is weighted 0.5: recall@5 0.97,
  recall@1 0.85.
- The intent classifier never parsed the SDK's replies; ambiguous messages always became "recall".
- A failed embedding call silently dropped a note from semantic search.
- The CLI never sent the dashboard token.

### Changed
- Default model tiers: `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`.
- `claude-agent-sdk` pinned to `>=0.2,<0.3` (the permission-callback API is required).
- The container runs as an unprivileged user.

[0.1.0]: https://github.com/Kage7047/kioku-assistant/releases/tag/v0.1.0
