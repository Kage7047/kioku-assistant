"""Phase 4.3 — intelligent proactivity: a governor over proactive interrupts.

The alert rules (alerts.py) already DETECT deltas. This decides WHETHER to interrupt: a daily
interrupt budget so a flurry can't spam you, per-class weights that fall when you say a class isn't
useful (feedback → false interrupts drop over time), and per-class dedup. Quiet by default; earns
interruptions. Deterministic + free. A few high-signal classes bypass the budget so an urgent thing
(a failed deploy, a deadline) is never silently dropped.
"""
import json
from datetime import date

import redis

from ..config import settings
from ..frontdoor.notify import notify
from ..memory import vault as V

_r = redis.Redis.from_url(settings.redis_url)
WEIGHTS_PATH = "system/interrupt-weights.json"
DAILY_BUDGET = 6                       # max non-critical proactive interrupts per day (tunable)
_CRITICAL = {"vercel-error", "deadline", "budget"}   # always get through


def _weights() -> dict:
    try:
        return json.loads(V.read(WEIGHTS_PATH))
    except Exception:  # noqa: BLE001
        return {}


def _today_key() -> str:
    return f"interrupt:count:{date.today().isoformat()}"


def allow(cls: str) -> bool:
    """Governor decision: should a proactive interrupt of this class fire right now?"""
    try:
        if cls in _CRITICAL:
            return True
        if _weights().get(cls, 1.0) <= 0.15:            # effectively muted by feedback
            return False
        return int(_r.get(_today_key()) or 0) < DAILY_BUDGET
    except Exception:  # noqa: BLE001
        return True                                     # never let the governor itself block an alert


def _record(cls: str) -> None:
    try:
        _r.incr(_today_key())
        _r.expire(_today_key(), 172800)
    except Exception:  # noqa: BLE001
        pass


def notify_proactive(cls: str, msg: str) -> bool:
    """Fire a proactive interrupt THROUGH the governor. Returns whether it actually fired."""
    if not allow(cls):
        return False
    ok = notify(f"{msg}\n— (not useful? reply: mute {cls})")
    if ok:
        _record(cls)
    return ok


def mute(cls: str) -> float:
    """Feedback: this class isn't useful — halve its weight (floor 0.1). Returns the new weight."""
    d = _weights()
    w = max(0.1, float(d.get(cls, 1.0)) * 0.5)
    d[cls] = w
    try:
        V.write(WEIGHTS_PATH, json.dumps(d, indent=2), approved=True)
    except Exception:  # noqa: BLE001
        pass
    return w


def unmute(cls: str) -> float:
    d = _weights()
    d[cls] = 1.0
    try:
        V.write(WEIGHTS_PATH, json.dumps(d, indent=2), approved=True)
    except Exception:  # noqa: BLE001
        pass
    return 1.0
