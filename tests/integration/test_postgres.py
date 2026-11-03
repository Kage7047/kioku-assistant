"""Run ledger, budget spend, stale-run reaping, conversation continuity, signals and claims —
against a real Postgres."""
import pytest

from kioku.config import settings
from kioku.memory import budget, claims, db


async def test_run_lifecycle(pg):
    rid = await db.create_run("ask", "when is the dentist?", settings.model_triage)
    assert (await db.run_result(rid))["status"] == "running"
    await db.finish_run(rid, status="done", result_text="Thursday 9:30", tokens_in=1200,
                        tokens_out=40, cost_usd=0.0014)
    row = await db.run_result(rid)
    assert (row["status"], row["result_text"]) == ("done", "Thursday 9:30")
    runs = await db.recent_runs(5)
    assert runs[0]["id"] == rid and runs[0]["cost_usd"] == pytest.approx(0.0014)
    assert runs[0]["finished_at"] is not None


async def test_month_to_date_spend_drives_the_budget_guard(pg):
    for cost in (4.0, 6.5):
        rid = await db.create_run("ask", "x", "m")
        await db.finish_run(rid, status="done", cost_usd=cost)
    # a run from last month must not count
    await pg.execute("UPDATE runs SET created_at = now() - interval '40 days' "
                     "WHERE id = (SELECT id FROM runs ORDER BY created_at LIMIT 1)")
    assert await budget.month_to_date_spend() == pytest.approx(6.5)
    snap = await budget.check("work", essential=True)
    assert snap["spend"] == pytest.approx(6.5)
    assert snap["remaining"] == pytest.approx(settings.agent_sdk_monthly_credit_usd - 6.5)


async def test_reaper_closes_only_stale_running_rows(pg):
    stale = await db.create_run("ask", "stuck", "m")
    fresh = await db.create_run("ask", "in progress", "m")
    done = await db.create_run("ask", "finished", "m")
    await db.finish_run(done, status="done")
    await pg.execute("UPDATE runs SET created_at = now() - interval '1 hour' WHERE id = ANY($1::uuid[])",
                     [stale, done])
    assert await db.reap_stale_runs(15) == 1
    assert (await db.run_result(stale))["status"] == "error"
    assert (await db.run_result(fresh))["status"] == "running"
    assert (await db.run_result(done))["status"] == "done"


async def test_recent_turns_are_oldest_first_and_skip_background_jobs(pg):
    for kind, text in [("ask", "q1"), ("morning_brief", "brief"), ("input", "q2"), ("ask", "q3")]:
        rid = await db.create_run(kind, text, "m")
        await db.finish_run(rid, status="done", result_text=f"a-{text}")
    current = await db.create_run("input", "now", "m")
    turns = await db.recent_turns(limit=2, exclude_run_id=current)
    assert [t["input"] for t in turns] == ["q2", "q3"]


async def test_signals_round_trip(pg):
    await db.record_signal("sentry", "acme.errors", {"count": 3})
    await db.record_signal("sentry", "acme.errors", {"count": 5})
    assert (await db.latest_signal("acme.errors"))["value"]["count"] == 5
    recent = await db.recent_signals(10)
    assert len(recent) == 2


async def test_claims_are_replaced_per_note_and_go_stale(pg, monkeypatch):
    monkeypatch.setattr(claims.embeddings, "available", lambda: False)
    assert await claims.replace_claims("people/anna.md", ["Anna prefers mornings", " ", "Anna is in Kraków"]) == 2
    assert await claims.replace_claims("people/anna.md", ["Anna moved to Gdańsk"]) == 1
    assert await pg.fetchval("SELECT count(*) FROM claims") == 1
    await pg.execute("UPDATE claims SET freshness = now() - interval '200 days'")
    assert await claims.mark_stale(120) == 1
    assert await pg.fetchval("SELECT review_state FROM claims") == "stale"
