"""Alert rules — the proactive loop's outputs. Fire notify() when something needs you.

`scan_deadlines` is fully real today with no external deps: it reads `due:`/`deadline:` dates
from your vault notes (exam dates, residence-card renewal, follow-ups) and warns when near.
More rules (error spikes, recruiter replies) plug in once their signals flow.
"""
import datetime
import re

import redis

from ..config import settings
from .._compat import run_sync
from .interrupt import notify_proactive       # Phase 4.3 — gate proactive alerts through the governor
from ..memory import db, vault as V

DUE = re.compile(r"(?:due|deadline)\s*:\s*(\d{4}-\d{2}-\d{2})", re.I)

_r = redis.Redis.from_url(settings.redis_url)


def scan_deadlines(within_days: int = 3) -> list[str]:
    today = datetime.date.today()
    hits: list[str] = []
    for f in V._md_files():
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for m in DUE.finditer(txt):
            try:
                d = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            delta = (d - today).days
            if 0 <= delta <= within_days:
                hits.append(f"{f.relative_to(V.VAULT)} — due in {delta}d ({m.group(1)})")
    return hits


def run_all() -> list[str]:
    fired: list[str] = []
    for h in scan_deadlines():
        if notify_proactive("deadline", f"⏰ {h}"):
            fired.append(h)
    return fired


# ---- Phase 3.1: event-driven alerts (deterministic — no model tokens) -------------------
# Compare the latest poll snapshot to the last state we alerted on, and notify ONLY on a
# meaningful change, deduped in Redis so the same condition never repeats.
def _latest(key: str) -> dict:
    try:
        sig = run_sync(db.latest_signal(key))
        val = (sig or {}).get("value")
        return val if isinstance(val, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _get(k: str) -> str:
    try:
        v = _r.get(k)
        return v.decode() if v else ""
    except Exception:  # noqa: BLE001
        return ""


def _set(k: str, v: str) -> None:
    try:
        _r.set(k, v)
    except Exception:  # noqa: BLE001
        pass


def watch_signals() -> list[str]:
    """Fire notifications on state CHANGES in the signal store (deploy down/recovered, error
    spike, new PRs). Deterministic + free; runs every ~15 min. Budget escalation and opportunity
    hits are already notified where they happen, so they're intentionally not repeated here."""
    fired: list[str] = []

    # Vercel — alert on entering ERROR, and on ERROR→READY recovery.
    v = _latest("vercel.deploys")
    if v:
        state = str(v.get("latest_state") or "")
        name = str(v.get("latest_name") or "vercel")
        prev = _get("alert:vercel_state")
        if state and state != prev:
            if state == "ERROR":
                notify_proactive("vercel-error",
                                 f"🔴 Deploy failed — {name} is in ERROR. {v.get('latest_url', '')}".strip())
                fired.append("vercel-error")
            elif prev == "ERROR" and state == "READY":
                notify_proactive("vercel-recovered", f"🟢 Deploy recovered — {name} is READY.")
                fired.append("vercel-recovered")
            _set("alert:vercel_state", state)

    # Sentry — baseline on first sight, then alert when unresolved issues grow.
    s = _latest("sentry.errors")
    if s:
        issues = int(s.get("unresolved_issues") or 0)
        prev = _get("alert:sentry_count")
        if prev and issues > int(prev):
            top = "; ".join(s.get("top") or [])[:200]
            notify_proactive("sentry", f"⚠️ Sentry: {issues} unresolved issue(s), up from {prev}. {top}".strip())
            fired.append("sentry")
        _set("alert:sentry_count", str(issues))

    # GitHub — baseline per repo, then alert on new open PRs to review.
    g = _latest("github.repos")
    if isinstance(g, dict):
        for repo, meta in g.items():
            if not isinstance(meta, dict) or meta.get("open_prs") is None:
                continue
            prs = int(meta["open_prs"])
            prev = _get(f"alert:gh_prs:{repo}")
            if prev and prs > int(prev):
                notify_proactive("github-pr", f"🔧 {repo}: {prs} open PR(s) (+{prs - int(prev)} new) to review.")
                fired.append(f"gh-{repo}")
            _set(f"alert:gh_prs:{repo}", str(prs))

    return fired
