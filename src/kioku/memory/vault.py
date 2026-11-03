"""Markdown vault access. Source of truth. Deterministic ops live here (cheap, no tokens)."""
import re
from datetime import datetime
from pathlib import Path

from rank_bm25 import BM25Okapi

from ..config import settings

VAULT = Path(settings.vault_path)
WRITE_ALLOWLIST = ("_reports", "inbox", "journal", "sources")   # dirs writable without approval
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def _md_files() -> list[Path]:
    return [p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts]


# Kioku owns its vault outright — it may create, edit, delete and move freely (this is its memory).
# Two zones are protected, and the check runs on the RESOLVED path, so `foo/../system/x`,
# `./system/x` and symlinks cannot sidestep it:
#   .git/    — never writable by anyone through this module. Writing .git/config could set
#              core.fsmonitor / core.hooksPath and run commands the next time the worker commits.
#   system/  — Kioku's config spine (persona, playbook, profile). A prompt injection that rewrote
#              it would persist across every future run, so model-driven writes are refused here;
#              changes go through approvals.stage_config_edit and land with approved=True.
_GIT = ".git"
_SYSTEM = "system"


def _resolve(rel: str) -> Path:
    """Resolve a vault-relative path and refuse anything outside the vault (raises ValueError)."""
    root = VAULT.resolve()
    p = (root / rel).resolve()
    p.relative_to(root)
    return p


def _zone(p: Path) -> str:
    parts = p.relative_to(VAULT.resolve()).parts
    return parts[0] if parts else ""


def _guard_write(p: Path, approved: bool) -> None:
    zone = _zone(p)
    if zone == _GIT:
        raise PermissionError("refusing to touch .git — git internals are never writable")
    if zone == _SYSTEM and not approved:
        raise PermissionError("system/ is Kioku's config spine; propose the change for approval instead")
    if p == VAULT.resolve():
        raise PermissionError("refusing to operate on the vault root")


def list_dir(rel: str = "") -> list[str]:
    base = _resolve(rel)
    return sorted(str(p.relative_to(VAULT.resolve())) for p in base.iterdir())


def read(rel: str) -> str:
    return _resolve(rel).read_text(encoding="utf-8")


def write(rel: str, content: str, approved: bool = False) -> str:
    """Create or overwrite a note. `approved=True` is for trusted internal writers (scheduler,
    patterns, an approved config edit) — never for a path chosen by the model."""
    p = _resolve(rel)
    _guard_write(p, approved)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p.relative_to(VAULT.resolve()))


def delete(rel: str) -> str:
    """Delete a vault file or directory. Protected: system/ and .git."""
    import shutil
    p = _resolve(rel)
    _guard_write(p, approved=False)
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    return rel


def move(src: str, dst: str) -> str:
    """Move/rename a vault path. Neither side may be inside system/ or .git."""
    s, d = _resolve(src), _resolve(dst)
    _guard_write(s, approved=False)
    _guard_write(d, approved=False)
    d.parent.mkdir(parents=True, exist_ok=True)
    s.replace(d)
    return dst


def apply_writes(items: list[dict], approved: bool = False) -> list[str]:
    """Apply many writes as one recoverable transaction (back up, write, roll back on error).

    Used by the orchestrator to commit sub-agent drafts. items: [{path, content}].
    """
    backups: list[tuple[Path, str | None]] = []
    applied: list[str] = []
    try:
        for it in items:
            p = _resolve(it["path"])
            _guard_write(p, approved)
            backups.append((p, p.read_text(encoding="utf-8") if p.exists() else None))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(it["content"], encoding="utf-8")
            applied.append(str(p.relative_to(VAULT.resolve())))
        return applied
    except Exception:
        for p, prev in reversed(backups):          # roll back
            if prev is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(prev, encoding="utf-8")
        raise


# --- retrieval (BM25 now; add pgvector hybrid in Phase 1) ---
def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


# Cache the BM25 index so we don't re-read + re-tokenize the whole vault on every query
# (a real cost/latency driver as the vault grows). Rebuild only when files actually change,
# detected by a cheap signature (count + newest mtime).
_bm25_cache: dict = {"sig": None, "bm25": None, "files": None, "corpus": None}


def _vault_signature(files: list[Path]) -> tuple[int, int]:
    return (len(files), max((f.stat().st_mtime_ns for f in files), default=0))


def _get_bm25(files: list[Path]):
    sig = _vault_signature(files)
    if _bm25_cache["sig"] != sig:
        corpus = [f.read_text(encoding="utf-8", errors="ignore") for f in files]
        _bm25_cache.update(sig=sig, files=files, corpus=corpus,
                           bm25=BM25Okapi([_tok(c) for c in corpus]))
    return _bm25_cache["bm25"], _bm25_cache["files"], _bm25_cache["corpus"]


def search(query: str, k: int = 6) -> list[dict]:
    files = _md_files()
    if not files:
        return []
    bm25, files, corpus = _get_bm25(files)
    scores = bm25.get_scores(_tok(query))
    ranked = sorted(zip(files, corpus, scores, strict=True), key=lambda x: x[2], reverse=True)[:k]
    return [{"path": str(f.relative_to(VAULT)), "score": round(float(s), 3),
             "excerpt": c[:400]} for f, c, s in ranked if s > 0]


def note_titles() -> dict:
    """{lowercased stem -> vault-relative path} for every note — used to validate/resolve
    [[wikilinks]] so the digest step only links to notes that actually exist."""
    return {f.stem.lower(): str(f.relative_to(VAULT)) for f in _md_files()}


# --- audit inventory (the P0 first job; deterministic → free) ---
def audit_inventory() -> dict:
    files = _md_files()
    total_bytes = sum(f.stat().st_size for f in files)
    names = {f.stem.lower(): f for f in files}
    linked: set[str] = set()
    dead: list[str] = []
    for f in files:
        for target in WIKILINK.findall(f.read_text(encoding="utf-8", errors="ignore")):
            t = target.strip().lower()
            if t in names:
                linked.add(t)
            else:
                dead.append(f"{f.relative_to(VAULT)} -> [[{target}]]")
    orphans = [str(f.relative_to(VAULT)) for f in files if f.stem.lower() not in linked]
    by_dir: dict[str, int] = {}
    for f in files:
        d = str(f.relative_to(VAULT).parent)
        by_dir[d] = by_dir.get(d, 0) + 1
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_kb": round(total_bytes / 1024, 1),
        "by_dir": dict(sorted(by_dir.items(), key=lambda x: -x[1])),
        "orphans": orphans[:200],
        "orphan_count": len(orphans),
        "dead_links": dead[:200],
        "dead_link_count": len(dead),
    }
