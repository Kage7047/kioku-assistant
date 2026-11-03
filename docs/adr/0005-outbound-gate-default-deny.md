# 0005 — Outbound actions are default-deny, enforced outside the model

**Status:** Accepted

## Context
Kioku reads untrusted text and holds tools that act as its owner. Any instruction to the model
("never send without asking") can be overridden by text the model reads. See the
[threat model](../security/THREAT_MODEL.md).

## Decision
Every run is wired to a permission callback (`can_use_tool`) that the model cannot influence.
Kioku's own tools and reads run freely; every external action that is not clearly a read or a
draft is staged for one-tap approval. The gate fails closed, nothing that can act outside the
vault is ever placed in `allowed_tools` (which the SDK auto-approves without the callback), and an
approved action may run exactly once with exactly the approved arguments. Without the callback
API, external tools are not mounted at all.

## Consequences
- New connectors are safe by default: an unrecognised action asks first.
- Some harmless writes (e.g. updating a document) need a tap until they are classified.
- The control is testable without a model: `tests/unit/test_security.py`.
