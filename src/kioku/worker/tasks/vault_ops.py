"""Vault upkeep: audit, re-index, git sync, ingest (single and bulk), digestion, the claim sweep, applying staged writes."""
import json
from datetime import date


from ..celery_app import app
from ..._compat import run_sync
from ...config import settings
from ...agent.orchestrator import run_agent
from ...memory import db, vault, budget, switch
from ...observability.langfuse import trace_run
from ...frontdoor.notify import notify

from ._common import _paused_finish, _record_and_notify


@app.task(name="kioku.worker.tasks.vault_audit_task")
def vault_audit_task(run_id: str):
    """Kioku's first real job. Deterministic inventory (free) + a light model summary."""
    if _paused_finish(run_id):
        return switch.PAUSED_MSG
    with trace_run(run_id, kind="vault_audit", model="triage"):
        try:
            inv = vault.audit_inventory()
            summary_prompt = (
                "Here is a vault audit inventory as JSON. Write a 6-8 line plain-language "
                "summary: health, biggest issues, and the 3 highest-value cleanup actions.\n\n"
                + json.dumps(inv, ensure_ascii=False)[:6000]
            )
            out = run_sync(run_agent(run_id, summary_prompt, "triage", essential=True))
            report = _render_report(inv, out["text"])
            path = vault.write(f"_reports/audit-{date.today().isoformat()}.md", report)
            out["result_path"] = path
            _record_and_notify(run_id, out)
            return path
        except Exception as e:  # noqa: BLE001
            db.finish_run_sync(run_id, status="error", error=str(e))
            raise


def _inert_links(s: str) -> str:
    """Neutralize [[wikilinks]] so an audit report doesn't self-poison: if the report writes a
    dead-link target as a live [[x]], the NEXT audit scans the report and counts it as a fresh
    dead link (runaway: 30→100→200). Single brackets don't match the WIKILINK regex (\\[\\[)."""
    return s.replace("[[", "[").replace("]]", "]")


def _render_report(inv: dict, narrative: str) -> str:
    dirs = "\n".join(f"- `{d}` — {n}" for d, n in inv["by_dir"].items())
    orphans = "\n".join(f"- {o}" for o in inv["orphans"][:40])
    dead = "\n".join(f"- `{_inert_links(d)}`" for d in inv["dead_links"][:40])
    return f"""# Vault audit — {inv['generated_at']}

{narrative}

## Inventory
- files: **{inv['file_count']}**, size: **{inv['total_kb']} KB**
- orphans: **{inv['orphan_count']}**, dead links: **{inv['dead_link_count']}**

### By directory
{dirs}

### Orphans (first 40)
{orphans or '- none'}

### Dead links (first 40)
{dead or '- none'}
"""


@app.task(name="kioku.worker.tasks.reindex_vault_task")
def reindex_vault_task(paths=None):
    """(Re)embed changed notes into pgvector. Cheap: local embeddings, only changed files."""
    from ...memory import index
    return index.reindex_sync(paths)


@app.task(name="kioku.worker.tasks.apply_write_task")
def apply_write_task(sha: str):
    """Apply an approved write ON THE WORKER (which owns the vault checkout), then index+push."""
    from ...memory import pending, vaultsync
    path = pending.apply_plan(sha)
    reindex_vault_task.delay([path])
    vaultsync.commit_push(f"apply {path}")
    notify(f"✅ applied {path}")
    return path


@app.task(name="kioku.worker.tasks.sync_vault_task")
def sync_vault_task():
    """Pull device edits, reindex what changed, then commit+push Kioku's own changes.
    Note: BM25 recall reads files live, so it's already fresh the moment a pull lands;
    the reindex keeps the pgvector side current too (incremental — no-op if embeddings off)."""
    from ...memory import vaultsync
    vaultsync.ensure_repo()            # pull device edits from git
    reindex_vault_task.delay()         # incremental: only changed files re-embed
    vaultsync.commit_push("periodic sync")


@app.task(name="kioku.worker.tasks.ingest_task")
def ingest_task(run_id: str, b64: str, filename: str, origin: str = "telegram"):
    """Ingest a file/photo (base64) into the brain: source copy + note + index + push."""
    import base64
    from ...agent import ingest
    data = base64.b64decode(b64)
    res = ingest.ingest_bytes(data, filename, origin)
    reindex_vault_task.delay([res["note"]])
    from ...memory import vaultsync
    vaultsync.commit_push(f"ingest {filename}")
    db.finish_run_sync(run_id, status="done", result_path=res["note"],
                       result_text=f"ingested {filename} ({res['kind']}, {res['chars']} chars)")
    notify(f"📎 learned from {filename} → {res['kind']} · {res['note']}")
    return res


def _flatten_wrapper(rel):
    """Collapse an import's wrapper ancestors to zone/filename so the map groups by real zone.
    `second-brain.md-export/second-brain/conversations/01.md` → `conversations/01.md`. Files at
    the import root or already at zone/file depth are left as-is."""
    from pathlib import Path
    parts = Path(rel).parts
    return Path(rel) if len(parts) <= 2 else Path(parts[-2], parts[-1])


@app.task(name="kioku.worker.tasks.bulk_ingest_task")
def bulk_ingest_task(subdir: str = "_import"):
    """Bulk-ingest a folder of exports dropped into the vault (default _import/). Deterministic and
    cheap: markdown/text is filed as notes as-is (preserving structure); other files (pdf/docx/csv/
    images) are extracted → source copy + note. One reindex + push at the end. NO model calls here —
    for an LLM 'study/organize' pass, ask Kioku afterwards (batched, budget-guarded)."""
    from pathlib import Path
    from ...agent import ingest
    from ...memory import vaultsync
    base = Path(vault.VAULT) / subdir
    if not base.exists():
        return {"error": f"drop your export into vault/{subdir}/ first"}
    dest = Path(vault.VAULT) / "reference" / "imported"
    ing = moved = skipped = 0
    for f in base.rglob("*"):
        if f.is_dir() or f.name == ".gitkeep":
            continue
        ext = f.suffix.lower()
        try:
            if ext in (".md", ".markdown", ".txt"):
                # Keep folder structure, but strip redundant single-child wrapper dirs (e.g. an
                # export nested as second-brain.md-export/second-brain/<zone>/…) so the map/graph
                # groups by real zone (conversations/projects/cvs) instead of one giant blob.
                target = dest / _flatten_wrapper(f.relative_to(base))
                target.parent.mkdir(parents=True, exist_ok=True)
                f.replace(target)
                moved += 1
            elif ext in ingest.IMAGE_EXT or ext in (".pdf", ".docx", ".csv"):
                ingest.ingest_bytes(f.read_bytes(), f.name, origin="import")
                f.unlink()                            # extracted → remove the original from _import
                ing += 1
            else:                                     # unknown type: preserve it, but out of _import
                target = dest / "_unprocessed" / f.name
                target.parent.mkdir(parents=True, exist_ok=True)
                f.replace(target)
                skipped += 1
        except Exception:  # noqa: BLE001
            skipped += 1
    # Leave _import EMPTY (bar .gitkeep) so the next batch starts clean — remove now-empty subdirs.
    for d in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()                                 # only removes if empty
        except OSError:
            pass
    reindex_vault_task.delay()
    vaultsync.commit_push("bulk import")
    # Don't leave the import as an orphaned dump: rebuild the structural map now (free) and
    # start digesting in cheap batches (understand + tag + connect each note over time).
    digest_batch_task.delay()
    notify(f"📚 bulk import: {ing} extracted, {moved} notes filed, {skipped} preserved as-is. "
           f"_import/ is clear for the next batch. Now digesting + connecting…")
    return {"ingested": ing, "moved": moved, "skipped": skipped}


@app.task(name="kioku.worker.tasks.digest_batch_task")
def digest_batch_task(limit: int = 12, chain: bool = True):
    """Make imports understandable + connected, WITHOUT bursting a subscription window.

    Free structural pass every time (rebuild zone indexes + root MAP → kills orphans), then a
    small model-driven batch (summary/type/tags/[[links]] per note). Budget-gated: if the guard
    has paused non-essential work, we still do the free indexing and defer the model batch.
    Re-enqueues itself (spread over time) until every note is digested."""
    if switch.is_paused():
        return {"paused": True}
    from ...agent import digest
    idx = digest.rebuild_indexes()                       # deterministic, free — always safe

    snap = budget.check_sync("triage", essential=False)
    if not snap["allowed"]:
        notify(f"🧩 indexed {idx['notes']} notes (orphans linked). Digestion paused — "
               f"budget mode {snap['mode']}; will resume next cycle.")
        return {"indexed": idx, "digested": 0, "deferred": True}

    pending = digest.find_undigested(limit)
    if not pending:                                      # nothing to digest → free index only, no run row
        return {"indexed": idx, "digested": 0, "remaining": 0}
    total_left = len(digest.find_undigested(9999))
    done, links, claims_n, people_n = 0, 0, 0, 0
    run_id = db.create_run_sync("digest", f"digest {len(pending)} of {total_left} notes", "triage")
    chars_in = 0
    for rel in pending:
        try:
            res = run_sync(digest.digest_note(rel))
            if res.get("type"):
                done += 1
                links += res.get("links", 0)
                claims_n += res.get("claims", 0)
                people_n += res.get("people", 0)
                chars_in += 3000                          # prompt bound per note (see digest.py)
        except Exception:  # noqa: BLE001  (one bad note never stops the batch)
            continue
    # approximate accounting so month-to-date spend stays honest (Haiku, tiny)
    t_in, t_out = chars_in // 4, done * 150
    db.finish_run_sync(run_id, status="done", tokens_in=t_in, tokens_out=t_out,
                       cost_usd=budget.cost_usd(settings.model_triage, t_in, t_out),
                       result_text=f"digested {done} notes, added {links} links")

    from ...memory import vaultsync
    reindex_vault_task.delay()
    vaultsync.commit_push("digest batch")

    # Record fresh vault health so the dashboard reflects the drop in orphans right after
    # organize (rebuild_indexes just linked them), not only on the nightly self-heal.
    inv = vault.audit_inventory()
    db.record_signal_sync("self", "vault.health",
                          {"files": inv["file_count"], "orphans": inv["orphan_count"],
                           "dead_links": inv["dead_link_count"], "by_dir": inv["by_dir"]})

    remaining = len(digest.find_undigested(9999))
    # If a whole batch digested NOTHING (classify failing, model erroring) the notes never get
    # marked, so the old code re-queued the SAME notes every 90s forever — burning tokens and
    # spamming identical "digest" rows. Only continue while we're actually making progress.
    if done == 0:
        notify(f"🧩 indexed the vault, but couldn't digest this batch ({len(pending)} notes) — "
               f"stopping the loop. {remaining} still undigested; I'll retry on the nightly pass.")
        return {"indexed": idx, "digested": 0, "remaining": remaining, "stalled": True}
    notify(f"🧩 digested {done} notes (+{links} links, +{claims_n} claims, +{people_n} people). "
           f"{remaining} left to digest.")
    if chain and remaining:                               # keep going — churn through the backlog
        digest_batch_task.apply_async(kwargs={"limit": limit}, countdown=45)
    return {"indexed": idx, "digested": done, "remaining": remaining}


@app.task(name="kioku.worker.tasks.claim_sweep_task")
def claim_sweep_task(stale_days: int = 120):
    """Nightly: flag stale claims + (with embeddings on) find contradictions/near-duplicates.
    Writes a human-readable review report and pings you only if something needs resolving.
    Deterministic + free without embeddings; smarter once they're on."""
    if switch.is_paused():
        return {"paused": True}
    from ...memory import claims, vaultsync
    res = claims.sweep_sync(stale_days)
    path = vault.write(f"_reports/claim-review-{date.today().isoformat()}.md", res["report"])
    reindex_vault_task.delay([path])
    vaultsync.commit_push("claim sweep")
    db.record_signal_sync("self", "vault.claims",
                          {"total": res["total"], "stale_new": res["stale_new"],
                           "contradictions": res["contradictions"]})
    if res["contradictions"] or res["stale_new"]:
        notify(f"🧾 claim sweep: {res['total']} claims · {res['stale_new']} newly stale · "
               f"{res['contradictions']} contradiction(s) → {path}")
    return res
