"""Personal CRM — populate the `people` table so Kioku can do contact-aware prep
("before this call, who is X and what do they want?") and, later, follow-up nudges.

Population is folded into the digest pass (same Haiku call), like the claim ledger: a note
about a person yields {name, context}, which we upsert here (dedup by name/alias, merge
context, remember the source note). DB-only + defensive — never fatal to a digest.
"""
from .db import pool
from .._compat import run_sync


async def upsert_person(name: str, context: str | None = None,
                        notes_path: str | None = None) -> str:
    """Insert a person or merge into an existing one (matched by name or alias, case-insensitive)."""
    name = (name or "").strip()
    if not name:
        return ""
    p = await pool()
    row = await p.fetchrow(
        "SELECT id, context FROM people WHERE lower(name)=lower($1) "
        "OR EXISTS (SELECT 1 FROM unnest(coalesce(aliases,'{}')) a WHERE lower(a)=lower($1)) LIMIT 1",
        name)
    ctx = (context or "").strip()
    if row:
        merged = row["context"] or ""
        if ctx and ctx.lower() not in merged.lower():
            merged = (merged + " · " + ctx).strip(" ·")[:1000]
        await p.execute(
            "UPDATE people SET context=$2, notes_path=COALESCE($3, notes_path), "
            "last_contact_at=now() WHERE id=$1",
            row["id"], merged, notes_path)
        return str(row["id"])
    new_id = await p.fetchval(
        "INSERT INTO people (name, context, notes_path, last_contact_at) "
        "VALUES ($1,$2,$3,now()) RETURNING id",
        name, ctx[:1000], notes_path)
    return str(new_id)


def upsert_person_sync(name, context=None, notes_path=None):
    return run_sync(upsert_person(name, context, notes_path))


async def list_people(limit: int = 100) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        "SELECT id, name, aliases, context, notes_path, last_contact_at "
        "FROM people ORDER BY last_contact_at DESC NULLS LAST, name LIMIT $1", limit)
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["last_contact_at"] = d["last_contact_at"].isoformat() if d["last_contact_at"] else None
        out.append(d)
    return out


async def find_person(q: str) -> list[dict]:
    p = await pool()
    rows = await p.fetch(
        "SELECT name, context, notes_path FROM people "
        "WHERE name ILIKE '%'||$1||'%' "
        "OR EXISTS (SELECT 1 FROM unnest(coalesce(aliases,'{}')) a WHERE a ILIKE '%'||$1||'%') "
        "LIMIT 10", q)
    return [dict(r) for r in rows]
