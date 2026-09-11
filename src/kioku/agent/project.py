"""Phase 4.6 — autonomous project ownership machinery.

A project is a folder `projects/<name>/` containing a `charter.md` whose frontmatter declares the
goal, success metrics, guardrails, autonomy level, a per-project budget cap, and a check-in cadence.
A scheduled PM loop reads the charter, plans, does the low-risk steps its autonomy level allows,
stages the rest for approval, and reports. Until a charter exists the loop is dormant — the pilot
project is chosen by the user together with Kioku (Kioku researches options first).

Autonomy levels (least→most): `advise` (only plan + report) · `draft` (also prepare drafts/dev tasks,
nothing outbound) · `act-low-risk` (also do reversible low-risk steps directly). Anything outbound,
spending, or irreversible ALWAYS routes through the existing approval gate regardless of level.
"""
from datetime import date
from pathlib import Path

import frontmatter

from ..memory import vault as V

CHARTER_GLOB = "projects/*/charter.md"
_LEVELS = ("advise", "draft", "act-low-risk")


def list_charters() -> list[dict]:
    """Every project with a charter.md → {name, goal, metrics, guardrails, autonomy_level,
    budget_cap_usd, checkin, body}. Malformed charters are skipped, never fatal."""
    out = []
    base = Path(V.VAULT) / "projects"
    if not base.exists():
        return out
    for ch in sorted(base.glob("*/charter.md")):
        try:
            post = frontmatter.loads(ch.read_text(encoding="utf-8"))
            m = dict(post.metadata)
            lvl = str(m.get("autonomy_level", "draft")).strip()
            out.append({
                "name": ch.parent.name,
                "goal": str(m.get("goal", "")),
                "metrics": m.get("success_metrics") or m.get("metrics") or [],
                "guardrails": m.get("guardrails") or [],
                "autonomy_level": lvl if lvl in _LEVELS else "draft",
                "budget_cap_usd": float(m.get("budget_cap_usd", 5.0) or 5.0),
                "checkin": str(m.get("checkin", "weekly")).strip().lower(),   # daily | weekly
                "body": post.content,
            })
        except Exception:  # noqa: BLE001
            pass
    return out


def get_charter(name: str) -> dict | None:
    for c in list_charters():
        if c["name"] == name:
            return c
    return None


def pm_prompt(c: dict) -> str:
    """The instruction for one PM check-in run. Kept tight; the loop is budget-capped upstream."""
    return (
        f"You are running project **{c['name']}** as its project manager (autonomy: {c['autonomy_level']}).\n"
        f"GOAL: {c['goal']}\n"
        f"SUCCESS METRICS: {c['metrics']}\n"
        f"GUARDRAILS (never cross): {c['guardrails']}\n\n"
        "Read `projects/{name}/` for state and the charter body below. Then, in ONE tight pass:\n"
        "1. Assess progress vs the metrics (use the vault + connectors/web as needed, read-only).\n"
        "2. Write/update `projects/{name}/plan-{today}.md` — the next 3-5 ranked steps.\n"
        "3. DO the steps your autonomy level permits NOW: 'advise' = none; 'draft' = prepare drafts / "
        "queue dev tasks (handoff/dev_task); 'act-low-risk' = also do reversible low-risk vault/schedule "
        "steps. Anything OUTBOUND, spending, or irreversible: stage it (it auto-gates) — never force it.\n"
        "4. Write a short check-in to `_reports/project-{name}-{today}.md`: progress, what you did, what "
        "needs his approval, what's blocked. Lead with the single most important thing.\n"
        "Be concrete and brief. Don't manufacture busywork.\n\n"
        "CHARTER BODY:\n" + (c.get("body") or "")[:3000]
    ).replace("{name}", c["name"]).replace("{today}", date.today().isoformat())
