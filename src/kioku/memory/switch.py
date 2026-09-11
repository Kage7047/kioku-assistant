"""Global soft on/off switch for Kioku.

When PAUSED, the service stays up (so /resume still works) but Kioku stops *spending*: agent
runs and every proactive/background job short-circuit. It's the "turn it off when I need to"
control — a single Redis key, checked at each task's entry point. Flip it from Telegram
(/pause · /resume) or the dashboard toggle. A real hard-off is stopping the Railway services.
"""
import redis

from ..config import settings

_r = redis.Redis.from_url(settings.redis_url)
_KEY = "kioku:paused"

PAUSED_MSG = "⏸ Kioku is paused — I've stopped running and spending. Send /resume (or toggle it in the dashboard) to wake me."


def is_paused() -> bool:
    try:
        return _r.get(_KEY) == b"1"
    except Exception:  # noqa: BLE001  (Redis down → treat as running, never wedge)
        return False


def set_paused(paused: bool) -> bool:
    try:
        if paused:
            _r.set(_KEY, "1")
        else:
            _r.delete(_KEY)
        return True
    except Exception:  # noqa: BLE001
        return False
