"""Claim ledger — the backbone of a second brain that doesn't rot.

A *claim* is one durable, checkable statement extracted from a note ("the owner prefers concise replies",
"Acme's read-only role is acme_ro"). We store each with its source note, a confidence,
and a freshness timestamp. Two maintenance moves keep the brain honest:

  • staleness — claims older than a threshold get flagged for review (deterministic, free).
  • contradiction/near-duplicate — when embeddings are on, semantically-close claims are found
    by pgvector; a pair where one negates the other is flagged as a contradiction to resolve.

Population is folded into the digest pass (one Haiku call per note already happens), so the
ledger fills with almost no extra spend. The sweep writes a human-readable review report.
"""
import re
from datetime import date, datetime

from .db import pool
from .._compat import run_sync
from . import embeddings

_NEG = re.compile(r"\b(not|no|never|isn'?t|aren'?t|wasn'?t|won'?t|can'?t|cannot|"
                  r"doesn'?t|didn'?t|don'?t|none|nobody|neither|without)\b", re.I)


# ---------------------------------------------------------------- population ----
async def replace_claims(source_path: str, statements: list[str]) -> int:
    """Replace all claims for one note (idempotent — safe to re-run on re-digest)."""
    p = await pool()
    await p.execute("DELETE FROM claims WHERE source_path=$1", source_path)
    if not statements:
        return 0
    vectors = embeddings.embed_passages(statements) if embeddings.available() else None
    for i, stmt in enumerate(statements):
        stmt = stmt.strip()
        if not stmt:
            continue
        vec = vectors[i] if vectors and i < len(vectors) else None
        await p.execute(
            "INSERT INTO claims (statement, source_path, confidence, freshness, embedding) "
            "VALUES ($1,$2,$3,now(),$4::vector)",  # ::vector — asyncpg has no native vector codec
            stmt[:1000], source_path, 0.6, (str(vec) if vec is not None else None),
        )
    return len([s for s in statements if s.strip()])


def replace_claims_sync(source_path, statements):
    return run_sync(replace_claims(source_path, statements))


# ---------------------------------------------------------------- sweep ----
async def backfill_embeddings(batch: int = 256) -> int:
    """Embed claims that have none yet (e.g. created while embeddings were OFF). Cheap + safe:
    a no-op unless embeddings are available. Run after turning embeddings on."""
    if not embeddings.available():
        return 0
    p = await pool()
    rows = await p.fetch("SELECT id, statement FROM claims WHERE embedding IS NULL LIMIT $1", batch)
    if not rows:
        return 0
    vecs = embeddings.embed_passages([r["statement"] for r in rows]) or []
    n = 0
    for r, vec in zip(rows, vecs):
        await p.execute("UPDATE claims SET embedding=$2::vector WHERE id=$1", r["id"], str(vec))
        n += 1
    return n


async def mark_stale(days: int = 120) -> int:
    p = await pool()
    return int(await p.fetchval(
        "WITH upd AS (UPDATE claims SET review_state='stale' "
        "WHERE review_state='unreviewed' AND freshness < now() - ($1 || ' days')::interval "
        "RETURNING 1) SELECT count(*) FROM upd", str(days)) or 0)


async def contradiction_candidates(max_distance: float = 0.15, limit: int = 40) -> list[dict]:
    """Near-duplicate claim pairs (cosine distance < max_distance). A pair where exactly one
    side is negated is a likely contradiction. Needs embeddings; returns [] without them."""
    if not embeddings.available():
        return []
    p = await pool()
    rows = await p.fetch("SELECT id, statement, source_path FROM claims WHERE embedding IS NOT NULL")
    out, seen = [], set()
    for r in rows:
        near = await p.fetch(
            """SELECT id, statement, source_path, embedding <=> (
                     SELECT embedding FROM claims WHERE id=$1) AS d
               FROM claims WHERE id<>$1 AND embedding IS NOT NULL
               ORDER BY d ASC LIMIT 1""", r["id"])
        if not near:
            continue
        n = near[0]
        if n["d"] is None or float(n["d"]) > max_distance:
            continue
        key = tuple(sorted((r["id"], n["id"])))
        if key in seen:
            continue
        seen.add(key)
        a_neg, b_neg = bool(_NEG.search(r["statement"])), bool(_NEG.search(n["statement"]))
        out.append({"a": dict(r), "b": {k: n[k] for k in ("id", "statement", "source_path")},
                    "distance": round(float(n["d"]), 3),
                    "kind": "contradiction" if a_neg != b_neg else "near-duplicate"})
        if len(out) >= limit:
            break
    # persist contradiction links so they surface in recall/UI later
    for c in out:
        if c["kind"] == "contradiction":
            await p.execute("UPDATE claims SET contradicts_id=$2, review_state='unreviewed' "
                            "WHERE id=$1", c["a"]["id"], c["b"]["id"])
    return out


async def counts() -> dict:
    p = await pool()
    row = await p.fetchrow(
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE review_state='stale') AS stale, "
        "count(*) FILTER (WHERE contradicts_id IS NOT NULL) AS contradicting FROM claims")
    return dict(row) if row else {"total": 0, "stale": 0, "contradicting": 0}


def sweep_sync(stale_days: int = 120) -> dict:
    """Run the whole nightly sweep. Returns a summary and the report markdown."""
    async def _run():
        await backfill_embeddings()                 # light up claims made while embeddings were off
        staled = await mark_stale(stale_days)
        cands = await contradiction_candidates()
        c = await counts()
        return staled, cands, c
    staled, cands, c = run_sync(_run())

    contras = [x for x in cands if x["kind"] == "contradiction"]
    dups = [x for x in cands if x["kind"] == "near-duplicate"]
    lines = [f"# Claim review — {date.today().isoformat()}", "",
             f"- claims total: **{c['total']}**",
             f"- newly stale (>{stale_days}d): **{staled}** · stale total: **{c['stale']}**",
             f"- contradictions flagged: **{len(contras)}** · near-duplicates: **{len(dups)}**", ""]
    if not embeddings.available():
        lines.append("_Embeddings are OFF — contradiction/duplicate detection is skipped. "
                     "Turn embeddings on to enable it. Staleness still runs._\n")
    if contras:
        lines.append("## ⚠️ Possible contradictions (resolve these)")
        for x in contras:
            lines.append(f"- `{x['a']['source_path']}`: {x['a']['statement']}")
            lines.append(f"  vs `{x['b']['source_path']}`: {x['b']['statement']}  _(d={x['distance']})_")
        lines.append("")
    if dups:
        lines.append("## Near-duplicates (consider merging)")
        for x in dups[:20]:
            lines.append(f"- {x['a']['statement']}  ≈  {x['b']['statement']}  _(d={x['distance']})_")
    report = "\n".join(lines) + "\n"
    return {"stale_new": staled, "contradictions": len(contras),
            "near_duplicates": len(dups), "total": c["total"], "report": report,
            "generated_at": datetime.now().isoformat(timespec="seconds")}
