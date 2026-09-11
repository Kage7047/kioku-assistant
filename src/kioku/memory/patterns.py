"""Model-of-you: your PATTERNS, not just facts (Phase 4.2).

Deterministic-first. The active-hours rhythm is derived from the `runs` table (when you actually
interact), the rest (what you avoid, decision style, energy) is narrative that `learn_task` and YOU
maintain. Persisted to `system/patterns.json` — machine-readable so code can use it (brief timing,
interrupt scoring, scheduling), and transparent/editable so you can correct it. A refresh recomputes
ONLY the derived fields and preserves everything you or learn_task wrote.
"""
import json
from datetime import datetime

from ..config import settings
from . import db, vault as V

PATTERNS_PATH = "system/patterns.json"
# Fields the deterministic refresh owns; everything else in the file is preserved as-is.
_DERIVED = {"active_hours", "best_nudge_hours", "hour_histogram", "samples", "updated", "timezone"}


def load() -> dict:
    try:
        return json.loads(V.read(PATTERNS_PATH))
    except Exception:  # noqa: BLE001
        return {}


def refresh_sync(days: int = 30) -> dict:
    """Recompute the active-hours rhythm and persist, preserving narrative/manual fields. Free (no model)."""
    tz = settings.timezone or "UTC"
    hours = db.active_hours_sync(days, tz)                      # {local_hour: count}
    prev = load()
    peak = max(hours.values()) if hours else 0
    active = sorted(h for h, n in hours.items() if peak and n >= 0.6 * peak)
    nudge = [h for h in active if 7 <= h <= 22] or ([9] if not active else active[:1])
    d = dict(prev)                                             # keep avoids / decision_style / energy / etc.
    d.update(active_hours=active, best_nudge_hours=nudge, hour_histogram=hours,
             samples=sum(hours.values()), timezone=tz,
             updated=datetime.now().isoformat(timespec="seconds"))
    V.write(PATTERNS_PATH, json.dumps(d, indent=2, ensure_ascii=False) + "\n", approved=True)
    return d


def best_nudge_hours() -> list[int]:
    """Local hours to prefer for proactive nudges (used by 4.3 / scheduling). Empty = no data yet."""
    return load().get("best_nudge_hours") or []


def summary() -> str:
    """Compact one-liner appended to the boot context (loaded every session — keep it tiny)."""
    d = load()
    if not d:
        return ""
    parts = []
    nudge = d.get("best_nudge_hours") or []
    if nudge:
        parts.append("most active around " + ", ".join(f"{h:02d}:00" for h in nudge[:4])
                     + f" {d.get('timezone', 'local')}")
    if d.get("energy"):
        parts.append(f"energy: {str(d['energy'])[:60]}")
    if d.get("avoids"):
        av = d["avoids"] if isinstance(d["avoids"], list) else [str(d["avoids"])]
        parts.append("tends to avoid " + ", ".join(str(x) for x in av[:4]))
    if d.get("decision_style"):
        parts.append(f"decision style: {str(d['decision_style'])[:80]}")
    return " · ".join(parts)
