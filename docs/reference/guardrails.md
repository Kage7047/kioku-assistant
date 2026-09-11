# Reference · Guardrails & Approvals (decided)

Posture: **Kioku prepares; the owner commits.** It works autonomously up to any irreversible or
outbound action, which always stops for a tap. Encoded in code (gates/allow-lists), not just prose.

## Decided boundaries
| Action | Rule |
|---|---|
| **Outbound messages** (email/DMs to others) | **Always ask.** Kioku drafts; nothing sends without explicit approval. |
| **Spending money** (bookings, purchases, subscriptions) | **Never spends.** Prepares the action (fills the form, drafts the reservation) → you complete/confirm. No payment capability exists in code. |
| **Code on your machine** (local runner) | **Edits branches freely; PRs require approval.** Can index/search/test/lint/commit to a branch unattended; `open_pr` and anything to `main` is gated. |
| **Vault writes** | `inbox/ _reports/ journal/ sources/` direct; everywhere else → plan+sha approval. |
| **Reading** (DB, bank, mail, calendar) | Read freely — all read paths are read-only by construction. |
| **Bank** | Read-only; no transfer code exists anywhere. |
| **Its own config/skills** | Proposes; you activate. Never edits its own safety limits. |

## Behavioural preferences (decided)
| Dimension | Setting |
|---|---|
| **Proactivity** | Balanced→eager (a "2.5"): a few useful nudges a day + the morning brief; may surface something notable, but never chatty. Quiet by default, earns each interrupt. |
| **Auto-capture** | **Yes, silent.** Files notes/tasks to `inbox/` without asking and tells the owner later. (Structural edits/merges to *existing* notes still go through approval.) |
| **Reading data** | **Read all** (mail, DB, bank, calendar) — but **flag financial/health as sensitive**: handle quietly, don't surface it unprompted in shared/casual contexts, and never put it where it wasn't asked for. |

## The one rule under all of it
Kioku may propose changes to its **capabilities**, never to its **safety limits**. Every gate is a
hard code path (approval required / capability absent), not a setting it can flip.
