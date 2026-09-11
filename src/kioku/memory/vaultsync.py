"""Optional git-backed vault. When VAULT_GIT_REMOTE is set, the markdown truth lives in a
private git repo so it survives ephemeral hosts (Railway redeploys) AND syncs to your
Obsidian devices. The WORKER owns the checkout; all mutations happen there, then push.

No-op (and never raises) when disabled or when git is unavailable — the vault just stays
a plain local directory, exactly as on a VPS.
"""
import logging
import pathlib
import subprocess

from ..config import settings

VAULT = pathlib.Path(settings.vault_path)
log = logging.getLogger("kioku.vaultsync")


def enabled() -> bool:
    return bool(settings.vault_git_remote)


def _git(*args) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(VAULT), *args],
                           capture_output=True, text=True, timeout=120)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def _configure_identity() -> None:
    """Fresh containers (Railway) have no global git identity, so `git commit` would fail
    with 'Author identity unknown' and silently never push. Set it per-repo."""
    _git("config", "user.email", settings.git_author_email)
    _git("config", "user.name", settings.git_author_name)


def ensure_repo() -> None:
    """Make VAULT a checkout of the remote whose WORKING TREE actually holds the files.
    Safe to call on every worker boot. Never raises: git problems degrade to a plain local dir.

    - **No .git** (fresh, or a Railway volume that only has `lost+found`): init, attach the
      remote, fetch, and FORCE-CHECK-OUT the remote tip so the files land on disk. Untracked
      local files (lost+found, an already-written report) are kept.
    - **.git present**: configure identity, fetch, force the working tree back onto the branch
      tip (repopulates a previously-empty checkout — the old `reset --mixed` moved history but
      never wrote files), then fast-forward to the remote. Local *commits* are preserved; only
      uncommitted edits to tracked files are overwritten (Kioku commits+pushes after each write).
    """
    if not enabled():
        return
    branch = settings.vault_git_branch
    remote = settings.vault_git_remote
    try:
        VAULT.mkdir(parents=True, exist_ok=True)
        if not (VAULT / ".git").exists():
            _git("init")
            _git("remote", "add", "origin", remote)
            _configure_identity()
            if _git("fetch", "origin", branch)[0] == 0:
                _git("checkout", "-f", "-B", branch, "FETCH_HEAD")  # write files to disk
            return
        _configure_identity()
        _git("remote", "set-url", "origin", remote)   # keep the (PAT-bearing) URL current
        if _git("fetch", "origin", branch)[0] == 0:
            _git("checkout", "-f", branch)                    # restore working tree to local tip
            _git("merge", "--ff-only", f"origin/{branch}")    # advance to remote if fast-forward
    except Exception:  # noqa: BLE001  (git is best-effort; the local dir still works)
        pass


def _record_sync(ok: bool, detail: str) -> None:
    """Persist the last push outcome (+ dedup a Telegram warning on the healthy→failing edge) so a
    broken vault sync can never again go unnoticed. Never fatal."""
    try:
        from . import db
        db.record_signal_sync("self", "vault.sync", {"ok": ok, "detail": detail[:200]})
    except Exception:  # noqa: BLE001
        pass
    try:
        import redis
        r = redis.Redis.from_url(settings.redis_url)
        was_failing = bool(r.get("vault:sync_failing"))
        if ok:
            if was_failing:
                r.delete("vault:sync_failing")
        elif not was_failing:
            r.set("vault:sync_failing", "1", ex=86400)
            from ..frontdoor.notify import notify
            notify(f"⚠️ Vault sync to GitHub is failing — {detail[:180]}. "
                   "Your memory is safe on the worker, but it isn't reaching the remote.")
    except Exception:  # noqa: BLE001
        pass


def commit_push(msg: str = "kioku update") -> None:
    """Commit any changes and push. Push failures used to be SWALLOWED — so a non-fast-forward
    rejection (a device/manual push landed first) left the worker volume diverging from GitHub
    silently and permanently. Now: on rejection we fetch + rebase onto the remote tip and retry
    once; any remaining failure is logged, recorded (vault.sync signal) and flagged to Telegram."""
    if not enabled():
        return
    branch = settings.vault_git_branch
    _git("add", "-A")
    _git("commit", "-m", msg)          # no-op if nothing staged
    code, out = _git("push", "origin", branch)
    if code == 0:
        _record_sync(True, "pushed")
        return
    # Rejected (non-fast-forward: origin and this checkout diverged). This worker's checkout is the
    # LIVE source of truth, so reconcile by MERGING origin in and keeping OUR side on any genuine
    # conflict (-X ours) — that still pulls in files that exist only on the remote (e.g. system/
    # updates, re-filed zones) while never letting a stale remote copy clobber live memory. A plain
    # rebase got permanently stuck on a rename/rename conflict; a single merge resolves it in one shot.
    log.warning("vault push failed (%s) — fetch + merge -X ours + retry", out[:200])
    _git("fetch", "origin", branch)
    _git("rebase", "--abort")   # clear any half-finished rebase from a prior attempt (no-op if none)
    _git("merge", "--abort")    # ditto for a stuck merge
    rc, ro = _git("merge", "-X", "ours", "--no-edit", f"origin/{branch}")
    if rc != 0:
        # -X ours resolves CONTENT conflicts, but a TREE conflict (rename/rename, add/add — exactly
        # a rename/rename case) it cannot auto-close, leaving both files staged/present. Rather
        # than stay stuck forever, force-complete the merge keeping BOTH sides on disk (a harmless
        # duplicate we tidy up in the cleanup) — no data is lost and the vault un-sticks itself.
        _git("add", "-A")
        rc2, ro2 = _git("commit", "--no-edit")
        if rc2 != 0:
            _git("merge", "--abort")
            log.error("vault merge could not auto-complete: %s / %s", ro[:150], ro2[:150])
            _record_sync(False, f"merge conflict: {ro[:150]}")
            return
        log.warning("vault merge auto-completed, keeping both sides of a tree conflict")
    code2, out2 = _git("push", "origin", branch)
    if code2 == 0:
        _record_sync(True, "pushed after merge")
    else:
        log.error("vault push still failing after merge: %s", out2[:200])
        _record_sync(False, f"push failed: {out2[:150]}")
