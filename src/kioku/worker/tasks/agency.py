"""Proactive work: project charters, skill and idea proposals, the opportunity radar, self-review and the weekly learning pass."""
import json
from datetime import date


from ..celery_app import app
from ..._compat import run_sync
from ...config import settings
from ...agent.orchestrator import run_agent
from ...memory import db, vault, budget, switch
from ...frontdoor.notify import notify, notify_file

from ._common import _r, _record_and_notify


@app.task(name="kioku.worker.tasks.project_manager_task")
def project_manager_task(name: str):
    """Phase 4.6 — one project check-in: assess → plan → do the steps its autonomy level allows →
    report. Per-project aggregate budget cap (Redis); outbound/irreversible steps auto-gate."""
    if switch.is_paused():
        return {"paused": True}
    from ...agent import project
    c = project.get_charter(name)
    if not c:
        notify(f"🏗 No charter for project '{name}' — create projects/{name}/charter.md first.")
        return {"error": "no charter"}
    key = f"project:spend:{name}"
    spent = float(_r.get(key) or 0)
    if spent >= c["budget_cap_usd"]:
        notify(f"🏗 Project '{name}' has hit its ${c['budget_cap_usd']} cap (spent ${spent:.2f}) — "
               "its loop is paused until you raise the cap.")
        return {"capped": True, "spent": spent}
    run_id = db.create_run_sync("project_pm", f"project: {name}", "work")
    out = run_sync(run_agent(run_id, project.pm_prompt(c), "work", essential=False,
                             intent="automate", retrieve_query=f"{name} {c['goal']}"))
    cost = budget.cost_usd(out["model"], out.get("tokens_in", 0), out.get("tokens_out", 0))
    try:
        _r.incrbyfloat(key, cost)
        _r.expire(key, 60 * 86400)
    except Exception:  # noqa: BLE001
        pass
    if not out.get("skipped") and out.get("text"):
        notify(f"🏗 {name}:\n{out['text'][:2500]}")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.project_checkins_task")
def project_checkins_task():
    """Daily gate: run each project's PM check-in on its cadence (daily/weekly). No charters → no-op."""
    if switch.is_paused():
        return {"paused": True}
    import time as _t
    from ...agent import project
    ran = []
    for c in project.list_charters():
        name = c["name"]
        if c["checkin"] == "weekly":
            k = f"project:lastcheckin:{name}"
            if _t.time() - float(_r.get(k) or 0) < 6.5 * 86400:
                continue
            _r.set(k, str(_t.time()))
        project_manager_task.delay(name)
        ran.append(name)
    return {"ran": ran}


@app.task(name="kioku.worker.tasks.propose_skill_task")
def propose_skill_task(_label: str = "propose"):
    """Learning loop: draft a reusable skill from recent journal work → inbox/skills/ for approval."""
    if switch.is_paused():
        return {"paused": True}
    import glob
    import os
    from ...config import settings
    run_id = db.create_run_sync("propose_skill", "propose skill", "work")  # own row: valid id + budget accounting
    entries = ""
    for f in sorted(glob.glob(os.path.join(settings.vault_path, "journal", "*.md")))[-7:]:
        try:
            entries += open(f, encoding="utf-8").read()[:1500] + "\n"
        except Exception:  # noqa: BLE001
            pass
    if not entries.strip():
        db.finish_run_sync(run_id, status="done", result_text="no journal yet")
        return "no journal"
    prompt = ("From these recent journal entries, identify ONE workflow worth turning into a "
              "reusable skill. Output a skill card exactly as:\n"
              "---\nname: <kebab-name>\nwhen: <comma-separated trigger phrases>\nmodel: work\n---\n"
              "<clear step-by-step instructions>\n\nJournal:\n" + entries[:6000])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False))
    if not out.get("skipped") and out.get("text"):
        name = "proposed-skill"
        for line in out["text"].splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip() or name
                break
        path = vault.write(f"inbox/skills/{name}.md", out["text"])
        notify(f"🧠 proposed skill '{name}' → approve by moving to system/skills/\n{path}")
        out["result_path"] = path
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.propose_ideas_task")
def propose_ideas_task():
    """Proactive 'Kioku proposes things': mid-week, review the owner's world and surface 1-3 concrete,
    high-leverage ideas / fixes / risks / opportunities — specific to THEM, not generic advice.
    Non-essential + pausable. This is the 'works while you sleep, and comes back with something'."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("propose_ideas", "proactive proposals", "work")
    sig = db.recent_signals_sync(30)
    prompt = (
        "Act as the owner's proactive chief of staff / technical co-founder. Review what you know about "
        "them — their active projects (e.g. Acme's push to first paying users, Kioku "
        "itself), their goals, constraints, and the recent signals below; read the vault as needed.\n"
        "Surface 1-3 CONCRETE, high-leverage proposals — an idea worth pursuing, a fix or "
        "improvement, a risk to get ahead of, or an opportunity. For each: a one-line WHY it matters "
        "to them now, and a specific suggested NEXT STEP. Be specific to their situation, not generic. "
        "Prefer things you could help execute (draft, research, schedule). Rank by leverage. If you "
        "have only one genuinely good idea, give one — no padding.\n\n"
        "RECENT SIGNALS (JSON):\n" + json.dumps(sig, default=str)[:3500])
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="research",
                             retrieve_query="active projects goals priorities acme ideas risks"))
    if not out.get("skipped") and out.get("text"):
        path = vault.write(f"_reports/proposals-{date.today().isoformat()}.md", out["text"])
        out["result_path"] = path
        notify("💡 A few thoughts:\n" + out["text"][:2500])
        notify_file(path, "💡 Proposals — full note")
    elif out.get("limited"):
        notify("💡 Proposals skipped — usage limit.")
    _record_and_notify(run_id, out)
    return out.get("text")


@app.task(name="kioku.worker.tasks.opportunity_radar_task")
def opportunity_radar_task():
    """Proactive job scout: search the boards, score FIT against the owner's profile + CVs, and
    surface only genuine matches. Non-essential (budget-gated, pausable). Uses vault_read + web
    only (no connectors) and Sonnet for the scoring quality."""
    if switch.is_paused():
        return {"paused": True}
    run_id = db.create_run_sync("opportunity_radar", "opportunity radar", "work")
    boards = settings.job_boards
    floor = settings.job_fit_floor
    prompt = (
        "Scout fresh job opportunities that genuinely fit the owner. You already know them (target roles, "
        "stack, location, salary floor, and their CVs are in the vault — read them if useful).\n"
        f"1. Search these boards with WebSearch, preferring postings from the last ~10 days: {boards}.\n"
        "2. Take the 3-4 most promising, fetch each posting, and score FIT 0-100 against their profile, "
        "stack, location (their city or remote) and salary floor.\n"
        f"3. Keep ONLY roles scoring >= {floor}. Skip anything already in the latest opportunities report.\n"
        "For each kept role: **Role @ Company** · location/remote · comp if listed · FIT NN · one line "
        "on why it fits + any red flag · the link. Lead with the single best. If nothing clears the bar, "
        "say so plainly — do not pad."
    )
    # intent='recall' → vault_read + web tools only (no Composio); difficulty 'work' → Sonnet.
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="recall",
                             retrieve_query="job search target roles salary preferences CV"))
    if not out.get("skipped") and out.get("text"):
        path = vault.write(f"_reports/opportunities-{date.today().isoformat()}.md", out["text"])
        out["result_path"] = path
        notify("🎯 Opportunity radar:\n" + out["text"][:2500])
        notify_file(path, "🎯 Opportunities — full report")
    elif out.get("limited"):
        notify("🎯 Opportunity radar skipped — " + (out.get("text") or "usage limit")[:300])
    _record_and_notify(run_id, out)
    return out.get("text")


def _render_self_review(summ: dict, usage: dict, unused: list, cache: dict | None = None) -> str:
    """Deterministic (free) markdown for the weekly self-review — the numbers speak first."""
    cache = cache or {}
    bm = "\n".join(f"- {m['model']}: {m['runs']} runs · ${m['cost']}" for m in summ["by_model"]) or "- none"
    bk = "\n".join(f"- {k['kind']}: {k['runs']} runs · ${k['cost']}"
                   + (f" · ⚠️ {k['errors']} err" if k["errors"] else "") for k in summ["by_kind"]) or "- none"
    top = "\n".join(f"- ${t['cost']} · {t['kind']} ({t['model']}) · {t['tokens_in']}→{t['tokens_out']} tok · {t['input']}"
                    for t in summ["top_cost"]) or "- none"
    use = "\n".join(f"- {n}: {c}×" for n, c in usage.items()) or "- (no skills used)"
    un = ", ".join(unused) or "none"
    return f"""# Self-review — last {summ['days']} days

**{summ['total_runs']} runs · ${summ['total_cost']} · {summ['errors']} errors** · avg {summ['avg_tokens_in']}→{summ['avg_tokens_out']} tok/run

## Cost by model
{bm}

## By kind
{bk}

## Most expensive runs
{top}

## Skill usage (30d)
{use}

**Unused skills (prune candidates):** {un}

## Prompt cache (7d)
- cache reads: **{cache.get('cache_read', 0)}** tok · writes: {cache.get('cache_write', 0)} · fresh input: {cache.get('fresh_input', 0)}
- **hit ratio: {int(cache.get('hit_ratio', 0) * 100)}%** over {cache.get('samples', 0)} runs {'✅' if cache.get('hit_ratio', 0) >= 0.3 else '— low; check for a cache invalidator' if cache.get('samples', 0) else '(no data yet)'}
"""


@app.task(name="kioku.worker.tasks.self_review_task")
def self_review_task():
    """Phase 3.4 — meta-cognition. Deterministic analysis of Kioku's own runs (cost, errors, model
    mix, skill usage) + a cheap Haiku read for concrete tuning suggestions. Non-essential + pausable."""
    if switch.is_paused():
        return {"paused": True}
    from ...agent import skills as SK
    summ = db.runs_summary_sync(7)
    usage = db.skill_usage_sync(30)
    cache = db.cache_stats_sync(7)
    unused = [s["name"] for s in SK.load() if s["name"] not in usage]
    report = _render_self_review(summ, usage, unused, cache)

    run_id = db.create_run_sync("self_review", "self review", "triage")
    prompt = ("These are Kioku's own operating stats for the last 7 days (JSON). In 4-6 lines give the owner "
              "concrete tuning suggestions ONLY where the data warrants it — model routing, turn caps, "
              "error hotspots, or skills to prune/trust. No filler; if it's healthy, say so plainly.\n\n"
              + json.dumps({"runs": summ, "skill_usage": usage, "unused_skills": unused}, default=str)[:3500])
    out = run_sync(run_agent(run_id, prompt, "triage", essential=False, intent="recall"))
    insights = out.get("text", "") if not out.get("skipped") else ""
    if insights:
        report += "\n## Kioku's read\n" + insights + "\n"
    rpath = vault.write(f"_reports/self-review-{date.today().isoformat()}.md", report)
    notify(f"🔍 Self-review (7d): {summ['total_runs']} runs · ${summ['total_cost']} · "
           f"{summ['errors']} error(s)." + (f"\n{insights[:1400]}" if insights else ""))
    notify_file(rpath, "🔍 Self-review — full report")
    _record_and_notify(run_id, out)

    # Phase 4.4 — close the loop: propose AT MOST ONE concrete, appendable playbook lesson from the
    # week's failures/cost, STAGED for approval (never applied silently). Only when the data warrants
    # it (errors present or enough runs to learn from). Vault-config only → can't touch safety limits.
    try:
        from ...memory import approvals
        if not out.get("skipped") and (summ.get("errors") or summ.get("total_runs", 0) >= 20):
            pr_id = db.create_run_sync("self_review_propose", "propose playbook lesson", "triage")
            pr = run_sync(run_agent(pr_id,
                ("From your own 7-day operating stats below, propose AT MOST ONE concrete operating "
                 "lesson to APPEND to your playbook that would prevent a repeat failure or cut cost — "
                 "one '- ' bullet, specific and actionable. If nothing is clearly worth it, reply with "
                 "exactly NONE. Output ONLY the bullet (starting '- ') or NONE.\n\n"
                 + json.dumps(summ, default=str)[:2500]),
                "triage", essential=False, intent="recall"))
            line = (pr.get("text") or "").strip()
            _record_and_notify(pr_id, pr)
            if line.startswith("- ") and line[:10].lower().find("none") == -1:
                approvals.stage_config_edit(
                    "system/playbook.md",
                    f"## Learned (self-review {date.today().isoformat()})\n{line}",
                    "operating lesson from this week's self-review", mode="append")
    except Exception:  # noqa: BLE001
        pass
    return {"summary": summ, "unused_skills": unused}


@app.task(name="kioku.worker.tasks.learn_task")
def learn_task():
    """Phase 3.2 — weekly self-education. Review the past week (calendar, notable mail, dev/ops
    signals) against what Kioku already knows, and PROPOSE a tightened system/profile.md — staged
    for approval, never a silent rewrite of the owner's curated profile. Non-essential + pausable."""
    if switch.is_paused():
        return {"paused": True}
    from ...memory import pending
    run_id = db.create_run_sync("learn", "weekly learning pass", "work")
    sig = db.recent_signals_sync(40)
    prompt = (
        "Weekly learning pass — sharpen your model of the owner, don't just recap.\n"
        "Read system/profile.md and reference/profile/ for what you already know. Then review the "
        "PAST WEEK: check their calendar (this week + next) and scan recent mail for anything that "
        "changes their world — read only, do NOT draft or send. Fold in the dev/ops signals below.\n"
        "Find GENUINELY NEW or CHANGED durable facts: project status, work moves, people, "
        "commitments, deadlines, preferences. Ignore ephemeral chatter and anything already known.\n"
        "Then:\n"
        "1. If their core profile is materially out of date, use vault_write to save an UPDATED "
        "system/profile.md — keep it TIGHT (it loads every session); it will stage for their approval.\n"
        "2. MODEL-OF-THE-OWNER PATTERNS: `system/patterns.json` holds how they OPERATE. Its `active_hours`/"
        "`best_nudge_hours`/`hour_histogram` are auto-derived — do NOT touch them. But if you've learned "
        "a durable PATTERN (energy rhythm, what they AVOID, decision style, over-commitment tendency), "
        "add/update the narrative fields `energy`/`avoids`(list)/`decision_style` by vault_write-ing the "
        "JSON back — PRESERVE every existing key. Only when you genuinely see it; don't invent.\n"
        "3. Summarise in 6-10 lines: what changed this week and what you've proposed. If the week "
        "was quiet, say so and propose nothing — don't manufacture updates.\n\n"
        "DEV/OPS SIGNALS (JSON):\n" + json.dumps(sig, default=str)[:3500])
    before = len(pending.list_plans())
    # intent='draft' → vault read/write + calendar + web + Composio (mail); 'work' → Sonnet.
    out = run_sync(run_agent(run_id, prompt, "work", essential=False, intent="draft"))
    if not out.get("skipped") and out.get("text"):
        new_plans = max(0, len(pending.list_plans()) - before)
        path = vault.write(f"_reports/learn-{date.today().isoformat()}.md", out["text"])
        out["result_path"] = path
        notify_file(path, "🧠 Weekly learning — full note")
        msg = "🧠 Weekly learning:\n" + out["text"][:1900]
        if new_plans:
            msg += f"\n\n📝 {new_plans} profile update(s) proposed — review in the dashboard or /approve."
        notify(msg)
    elif out.get("limited"):
        notify("🧠 Weekly learning skipped — " + (out.get("text") or "usage limit")[:300])
    _record_and_notify(run_id, out)
    return out.get("text")
