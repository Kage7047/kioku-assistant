"""Poller registry — the proactive loop's inputs. connector name -> a function that fetches
and records signals. `self` is real (no external API). `sentry`/`vercel` are real adapters that
need per-service tokens (headless — not interactive OAuth). Anything unwired raises, so we NEVER
invent fake data.

Add a new poller: write a `poll_<name>()` that calls `db.record_signal_sync(source, key, value)`,
register it below, and add `{name: <name>, kind: poller, enabled: true}` to connectors.yaml.
"""
from ..config import settings
from .._compat import run_sync
from ..memory import budget, db, vault


def poll_self() -> dict:
    snap = budget.check_sync("triage", essential=True)
    db.record_signal_sync("self", "agent.spend_mtd",
                          {"spend": snap["spend"], "remaining": snap["remaining"],
                           "mode": snap["mode"], "fraction": snap["fraction"]})
    # Enforcement check: the binding system files must be present in the live vault, or Kioku's
    # character silently degrades. Record presence; warn only when it CHANGES to bad (no hourly spam).
    present = {}
    for f in ("system/persona.md", "system/playbook.md", "system/profile.md", "system/boot.md"):
        try:
            present[f.split("/")[-1]] = bool(vault.read(f).strip())
        except Exception:  # noqa: BLE001
            present[f.split("/")[-1]] = False
    try:
        prev = (run_sync(db.latest_signal("system.files")) or {}).get("value") or {}
        was_ok = bool(prev) and all(prev.values())
    except Exception:  # noqa: BLE001
        was_ok = True
    db.record_signal_sync("self", "system.files", present)
    # Diagnostic: can THIS process (the worker) actually push to Telegram? If not, every proactive
    # brief/alert is generated but silently undelivered — the classic "briefs don't arrive" bug.
    tg_ok = bool(settings.telegram_bot_token and settings.telegram_allowed_user_id)
    db.record_signal_sync("self", "telegram.deliverable", {"ok": tg_ok})
    # Surface self-scheduled tasks on the dashboard (hourly snapshot; the vault file is truth).
    try:
        from ..memory import scheduler
        db.record_signal_sync("self", "system.schedules", {"items": scheduler.load()})
    except Exception:  # noqa: BLE001
        pass
    if not all(present.values()) and was_ok:            # only on transition healthy → degraded
        from ..frontdoor.notify import notify
        notify("⚠️ A binding system file failed to load (persona/playbook/profile). Kioku's "
               f"character may be degraded until the vault syncs: {present}")
    return snap


def poll_vercel() -> dict:
    if not settings.vercel_token:
        raise NotImplementedError("set VERCEL_TOKEN")
    import httpx
    r = httpx.get("https://api.vercel.com/v6/deployments?limit=8",
                  headers={"Authorization": f"Bearer {settings.vercel_token}"}, timeout=20)
    r.raise_for_status()
    deps = r.json().get("deployments", [])
    latest = deps[0] if deps else {}
    db.record_signal_sync("vercel", "vercel.deploys", {
        "latest_state": latest.get("state"), "latest_name": latest.get("name"),
        "latest_url": latest.get("url"),
        "recent": len(deps), "errors": sum(1 for d in deps if d.get("state") == "ERROR"),
    })
    return {"recent": len(deps)}


def poll_sentry() -> dict:
    if not (settings.sentry_auth_token and settings.sentry_org and settings.sentry_project):
        raise NotImplementedError("set SENTRY_AUTH_TOKEN, SENTRY_ORG, SENTRY_PROJECT")
    import httpx
    url = (f"https://sentry.io/api/0/projects/{settings.sentry_org}/"
           f"{settings.sentry_project}/issues/?statsPeriod=24h&query=is:unresolved")
    r = httpx.get(url, headers={"Authorization": f"Bearer {settings.sentry_auth_token}"}, timeout=20)
    r.raise_for_status()
    issues = r.json()
    db.record_signal_sync("sentry", "sentry.errors", {
        "unresolved_issues": len(issues),
        "events_24h": sum(int(i.get("count", 0)) for i in issues),
        "top": [i.get("title") for i in issues[:3]],
    })
    return {"issues": len(issues)}


def _unwired(name: str):
    def _f():
        raise NotImplementedError(f"connector '{name}' has no adapter yet — add one in pollers.py")
    return _f


def poll_github() -> dict:
    if not (settings.github_token and settings.github_repos):
        raise NotImplementedError("set GITHUB_TOKEN, GITHUB_REPOS (comma-separated owner/repo)")
    import httpx
    h = {"Authorization": f"Bearer {settings.github_token}",
         "Accept": "application/vnd.github+json"}
    out = {}
    for repo in [r.strip() for r in settings.github_repos.split(",") if r.strip()]:
        try:
            prs = httpx.get(f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100",
                            headers=h, timeout=20).json()
            iss = httpx.get(f"https://api.github.com/repos/{repo}/issues?state=open&per_page=1",
                            headers=h, timeout=20)
            # open issues count via header link isn't trivial; keep it simple: open PRs + repo meta
            meta = httpx.get(f"https://api.github.com/repos/{repo}", headers=h, timeout=20).json()
            out[repo] = {"open_prs": len(prs) if isinstance(prs, list) else 0,
                         "open_issues": meta.get("open_issues_count")}
        except Exception as e:  # noqa: BLE001
            out[repo] = {"error": str(e)}
    db.record_signal_sync("github", "github.repos", out)
    return out


# ---- READ-ONLY guard for any SQL we run against your app DB ----
_WRITE_SQL = ("insert", "update", "delete", "drop", "alter", "truncate", "create",
              "grant", "revoke", "merge", "replace", "copy")


def _is_readonly(sql: str) -> bool:
    q = sql.strip().lower().lstrip("(").lstrip()
    return q.startswith("select") and not any(f" {w} " in f" {q} " for w in _WRITE_SQL)


def poll_db() -> dict:
    """App metrics via read-only SELECTs. Enforces SELECT-only in code; use a read-only DB role too."""
    if not (settings.app_db_url and settings.app_db_queries):
        raise NotImplementedError("set APP_DB_URL (read-only role) and APP_DB_QUERIES (name:SQL;...)")
    import psycopg2  # optional dep; add if you enable this connector
    results = {}
    conn = psycopg2.connect(settings.app_db_url)
    conn.set_session(readonly=True, autocommit=True)          # belt: DB-enforced read-only
    try:
        cur = conn.cursor()
        for pair in settings.app_db_queries.split(";"):
            if ":" not in pair:
                continue
            name, sql = pair.split(":", 1)
            if not _is_readonly(sql):                          # suspenders: refuse non-SELECT
                results[name.strip()] = "refused: not a SELECT"
                continue
            cur.execute(sql)
            row = cur.fetchone()
            results[name.strip()] = row[0] if row and len(row) == 1 else row
    finally:
        conn.close()
    db.record_signal_sync("db", "app.metrics", results)
    return results


def poll_bank() -> dict:
    """Bank — STRICTLY READ-ONLY. Records balances/recent transactions as signals.
    There is intentionally NO transfer/payment code anywhere; `bank_allow_transfers` is inert."""
    if not (settings.bank_api_base and settings.bank_token):
        raise NotImplementedError("set BANK_API_BASE, BANK_TOKEN (use a READ-ONLY API scope)")
    import httpx
    h = {"Authorization": f"Bearer {settings.bank_token}"}
    # GET only. No POST/PUT/PATCH/DELETE is ever issued to the bank from Kioku.
    acc = httpx.get(f"{settings.bank_api_base}/accounts", headers=h, timeout=20)
    acc.raise_for_status()
    accounts = acc.json()
    db.record_signal_sync("bank", "bank.balances",
                          {"accounts": accounts, "note": "read-only; transfers disabled in code"})
    return {"accounts": len(accounts) if isinstance(accounts, list) else 1}


REGISTRY = {
    "self": poll_self,
    "sentry": poll_sentry,
    "vercel": poll_vercel,
    "github": poll_github,
    "db": poll_db,
    "bank": poll_bank,
}


def poller_for(name: str):
    return REGISTRY.get(name, _unwired(name))
