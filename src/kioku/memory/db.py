"""Thin async Postgres helpers. Postgres is an INDEX; the vault is truth."""
import asyncpg
from .._compat import run_sync  # tiny helper so Celery (sync) can call async db funcs
from ..config import settings

_pool: asyncpg.Pool | None = None


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    return _pool


async def create_run(kind: str, input_: str, model: str) -> str:
    p = await pool()
    rid = await p.fetchval(
        "INSERT INTO runs (kind, input, model, status) VALUES ($1,$2,$3,'running') RETURNING id",
        kind, input_, model,
    )
    return str(rid)   # asyncpg returns a uuid.UUID; keep run_id a plain str everywhere downstream


async def finish_run(run_id: str, *, status: str, result_path: str | None = None,
                     result_text: str | None = None, tokens_in: int = 0,
                     tokens_out: int = 0, cost_usd: float = 0.0, error: str | None = None):
    p = await pool()
    await p.execute(
        """UPDATE runs SET status=$2, result_path=$3, result_text=$4,
                  tokens_in=$5, tokens_out=$6, cost_usd=$7, error=$8, finished_at=now()
           WHERE id=$1::uuid""",
        run_id, status, result_path, result_text, tokens_in, tokens_out, cost_usd, error,
    )


# User-facing conversation kinds — background jobs (briefs, pollers, reviews) are excluded
# from continuity so their prompts don't bleed into a chat.
_CONVO_KINDS = ("ask", "input", "vault_audit", "ingest")


async def recent_turns(limit: int = 6, exclude_run_id: str | None = None) -> list[dict]:
    """The last few completed user-facing exchanges, oldest-first, for conversation continuity."""
    p = await pool()
    rows = await p.fetch(
        """SELECT input, result_text FROM runs
           WHERE kind = ANY($1) AND status='done'
                 AND result_text IS NOT NULL AND ($3::uuid IS NULL OR id <> $3::uuid)
           ORDER BY created_at DESC LIMIT $2""",
        list(_CONVO_KINDS), limit, exclude_run_id,
    )
    return [{"input": r["input"], "result_text": r["result_text"]} for r in reversed(rows)]


async def reap_stale_runs(minutes: int = 15) -> int:
    """Mark runs stuck in 'running' (task killed before finish_run) as errored. A run row is
    set 'running' at creation and only cleared when the task finishes — a worker restart / hard
    kill / lost message leaves zombies. minutes=0 reaps ALL running (safe on a fresh worker boot,
    single worker); a periodic sweep uses a threshold above the run timeout so it won't touch a
    genuinely in-progress run."""
    p = await pool()
    n = await p.fetchval(
        "WITH u AS (UPDATE runs SET status='error', "
        "  error='stale — worker restarted or timed out before finishing', finished_at=now() "
        "  WHERE status='running' AND created_at < now() - ($1||' minutes')::interval "
        "  RETURNING 1) SELECT count(*) FROM u", str(minutes))
    return int(n or 0)


# sync wrappers for Celery tasks
def create_run_sync(kind, input_, model): return run_sync(create_run(kind, input_, model))
def finish_run_sync(*a, **k): return run_sync(finish_run(*a, **k))
def reap_stale_runs_sync(minutes=15): return run_sync(reap_stale_runs(minutes))
def recent_turns_sync(limit=6, exclude_run_id=None):
    return run_sync(recent_turns(limit, exclude_run_id))


async def record_signal(source: str, key: str, value: dict):
    p = await pool()
    await p.execute(
        "INSERT INTO signals (source, key, value_json) VALUES ($1,$2,$3::jsonb)",
        source, key, __import__("json").dumps(value),
    )


async def recent_signals(limit: int = 30) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        "SELECT source, key, value_json, observed_at FROM signals "
        "ORDER BY observed_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


def record_signal_sync(source, key, value): return run_sync(record_signal(source, key, value))
def recent_signals_sync(limit=30): return run_sync(recent_signals(limit))


# ---- command-center reads (dashboard) ----
async def recent_runs(limit: int = 20) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        "SELECT id, kind, status, model, input, result_text, cost_usd, "
        "       created_at, finished_at "
        "FROM runs ORDER BY created_at DESC LIMIT $1", limit)
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["cost_usd"] = float(d["cost_usd"] or 0)
        for k in ("created_at", "finished_at"):
            d[k] = d[k].isoformat() if d[k] else None
        out.append(d)
    return out


async def run_result(run_id: str) -> dict | None:
    """Status + text of a run — lets the SSE stream close on DB state even if no 'done' event
    was published (e.g. command/capture inputs that don't run the agent)."""
    p = await pool()
    row = await p.fetchrow(
        "SELECT status, result_text, error FROM runs WHERE id=$1::uuid", run_id)
    return dict(row) if row else None


async def latest_signal(key: str) -> dict | None:
    p = await pool()
    row = await p.fetchrow(
        "SELECT value_json, observed_at FROM signals WHERE key=$1 "
        "ORDER BY observed_at DESC LIMIT 1", key)
    if not row:
        return None
    val = row["value_json"]
    if isinstance(val, str):
        val = __import__("json").loads(val)
    return {"value": val, "observed_at": row["observed_at"].isoformat()}


async def spend_series(limit: int = 48) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        "SELECT value_json, observed_at FROM signals WHERE key='agent.spend_mtd' "
        "ORDER BY observed_at DESC LIMIT $1", limit)
    js = __import__("json")
    out = []
    for r in reversed(rows):
        v = r["value_json"]
        v = js.loads(v) if isinstance(v, str) else v
        out.append({"t": r["observed_at"].isoformat(), "spend": v.get("spend"),
                    "fraction": v.get("fraction")})
    return out


async def source_last_seen() -> dict:
    p = await pool()
    rows = await p.fetch("SELECT source, max(observed_at) AS last FROM signals GROUP BY source")
    return {r["source"]: r["last"].isoformat() for r in rows if r["last"]}


async def runs_summary(days: int = 7) -> dict:
    """Deterministic self-analysis of Kioku's own runs over a window — feeds the weekly self-review
    (meta-cognition). No model tokens: it's all SQL over the runs table."""
    p = await pool()
    w = "created_at >= now() - ($1||' days')::interval"
    overall = await p.fetchrow(
        f"SELECT count(*) n, COALESCE(sum(cost_usd),0) cost, "
        f"count(*) FILTER (WHERE status='error') errors, "
        f"COALESCE(avg(tokens_in),0) ati, COALESCE(avg(tokens_out),0) ato FROM runs WHERE {w}",
        str(days))
    by_model = await p.fetch(
        f"SELECT COALESCE(model,'?') m, count(*) n, COALESCE(sum(cost_usd),0) c "
        f"FROM runs WHERE {w} GROUP BY m ORDER BY c DESC", str(days))
    by_kind = await p.fetch(
        f"SELECT COALESCE(kind,'?') k, count(*) n, COALESCE(sum(cost_usd),0) c, "
        f"count(*) FILTER (WHERE status='error') e FROM runs WHERE {w} GROUP BY k ORDER BY c DESC",
        str(days))
    top = await p.fetch(
        f"SELECT COALESCE(kind,'?') k, COALESCE(model,'?') m, COALESCE(cost_usd,0) c, "
        f"COALESCE(tokens_in,0) ti, COALESCE(tokens_out,0) too, left(COALESCE(input,''),60) inp "
        f"FROM runs WHERE {w} ORDER BY cost_usd DESC NULLS LAST LIMIT 5", str(days))
    return {
        "days": days, "total_runs": overall["n"],
        "total_cost": round(float(overall["cost"]), 4), "errors": overall["errors"],
        "avg_tokens_in": int(overall["ati"]), "avg_tokens_out": int(overall["ato"]),
        "by_model": [{"model": r["m"], "runs": r["n"], "cost": round(float(r["c"]), 4)} for r in by_model],
        "by_kind": [{"kind": r["k"], "runs": r["n"], "cost": round(float(r["c"]), 4), "errors": r["e"]} for r in by_kind],
        "top_cost": [{"kind": r["k"], "model": r["m"], "cost": round(float(r["c"]), 4),
                      "tokens_in": r["ti"], "tokens_out": r["too"], "input": r["inp"]} for r in top],
    }


async def skill_usage(days: int = 30) -> dict:
    """How often each skill was applied (from 'skill.used' signals) — for skill maturation."""
    p = await pool()
    rows = await p.fetch(
        "SELECT value_json->>'name' n, count(*) c FROM signals "
        "WHERE key='skill.used' AND observed_at >= now() - ($1||' days')::interval "
        "GROUP BY n ORDER BY c DESC", str(days))
    return {r["n"]: int(r["c"]) for r in rows if r["n"]}


async def cache_stats(days: int = 7) -> dict:
    """Aggregate prompt-cache usage from 'cache.usage' signals — proves caching is hitting."""
    p = await pool()
    rows = await p.fetch(
        "SELECT value_json FROM signals WHERE key='cache.usage' "
        "AND observed_at >= now() - ($1||' days')::interval", str(days))
    js = __import__("json")
    read = write = fresh = 0
    for r in rows:
        v = r["value_json"]
        v = js.loads(v) if isinstance(v, str) else v
        read += v.get("read", 0) or 0
        write += v.get("write", 0) or 0
        fresh += v.get("input", 0) or 0
    total = read + fresh
    return {"cache_read": read, "cache_write": write, "fresh_input": fresh,
            "hit_ratio": round(read / total, 3) if total else 0.0, "samples": len(rows)}


def runs_summary_sync(days=7): return run_sync(runs_summary(days))
def skill_usage_sync(days=30): return run_sync(skill_usage(days))
def cache_stats_sync(days=7): return run_sync(cache_stats(days))


async def spend_by_model() -> dict:
    """Month-to-date cost grouped by the run's model/tier — feeds the budget tier breakdown."""
    p = await pool()
    rows = await p.fetch(
        "SELECT model, COALESCE(SUM(cost_usd),0) AS c FROM runs "
        "WHERE created_at >= date_trunc('month', now()) AND model IS NOT NULL "
        "GROUP BY model")
    return {r["model"]: float(r["c"] or 0) for r in rows}


async def active_hours(days: int = 30, tz: str = "UTC") -> dict:
    """Histogram of the LOCAL hour-of-day you actually interact — user-initiated runs (ask/input) over
    the last N days. created_at is stored UTC; convert to `tz` for a real active-rhythm model (Phase 4.2)."""
    p = await pool()
    rows = await p.fetch(
        "SELECT extract(hour from created_at AT TIME ZONE $2)::int AS h, count(*) AS n FROM runs "
        "WHERE kind IN ('ask','input') AND created_at >= now() - ($1||' days')::interval "
        "GROUP BY h ORDER BY h", str(days), tz)
    return {int(r["h"]): int(r["n"]) for r in rows}


def active_hours_sync(days=30, tz="UTC"): return run_sync(active_hours(days, tz))
