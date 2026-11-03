"""Self-scheduled recurring tasks — Kioku can set up its own cron jobs.

Stored as JSON in the git-backed vault (`system/schedules.json`) so they are truth, visible, and
editable by hand. A per-minute beat tick runs the due ones. Minimal 5-field cron matcher (no
external dependency): fields are `minute hour day-of-month month day-of-week`, each supporting
`*`, `N`, `a,b,c`, `a-b`, `*/n`. day-of-week is 0-6 (Sun=0), 7 also = Sun.
"""
import json
import uuid
from datetime import datetime

from ..config import settings
from . import vault as V

REL = "system/schedules.json"


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
    vals: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", ""):
            rng = range(lo, hi + 1)
        elif "-" in part:
            a, b = part.split("-", 1)
            rng = range(int(a), int(b) + 1)
        else:
            v = int(part)
            rng = range(v, v + 1)
        base = rng.start
        for v in rng:
            if (step == 1 or (v - base) % step == 0) and lo <= v <= hi:
                vals.add(v)
    return vals


def matches(expr: str, dt: datetime) -> bool:
    fields = expr.split()
    if len(fields) != 5:
        return False
    mi, ho, dom, mo, dow = fields
    m, h = _parse_field(mi, 0, 59), _parse_field(ho, 0, 23)
    dm, mon = _parse_field(dom, 1, 31), _parse_field(mo, 1, 12)
    dw = _parse_field(dow, 0, 7)
    if 7 in dw:
        dw.add(0)
    cron_dow = (dt.weekday() + 1) % 7          # python Mon=0..Sun=6 → cron Sun=0..Sat=6
    dom_star, dow_star = dom.strip() == "*", dow.strip() == "*"
    if dom_star and dow_star:
        day_ok = True
    elif dom_star:
        day_ok = cron_dow in dw
    elif dow_star:
        day_ok = dt.day in dm
    else:                                       # both restricted → cron ORs them
        day_ok = dt.day in dm or cron_dow in dw
    return dt.minute in m and dt.hour in h and dt.month in mon and day_ok


def valid_cron(expr: str) -> bool:
    try:
        return len(expr.split()) == 5 and (matches(expr, datetime.now()) or True)
    except Exception:  # noqa: BLE001
        return False


def now_local() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(settings.timezone))
    except Exception:  # noqa: BLE001
        return datetime.now()


def load() -> list[dict]:
    try:
        data = json.loads(V.read(REL))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save(items: list[dict]) -> None:
    V.write(REL, json.dumps(items, indent=2, ensure_ascii=False) + "\n", approved=True)


def add(cron: str, task: str, note: str = "") -> str:
    if not valid_cron(cron):
        raise ValueError("cron must be 5 fields, e.g. '0 9 * * 5' = Fri 09:00")
    if len(_parse_field(cron.split()[0], 0, 59)) > 12:   # >12 firings/hour = more than every 5 min
        raise ValueError("too frequent — schedule at most every 5 minutes (e.g. '*/5', or a fixed minute)")
    items = load()
    sid = uuid.uuid4().hex[:8]
    items.append({"id": sid, "cron": cron.strip(), "task": task.strip(), "note": note.strip(),
                  "created": now_local().isoformat(timespec="seconds"), "enabled": True})
    _save(items)
    return sid


def remove(sid: str) -> int:
    items = load()
    kept = [i for i in items if i.get("id") != sid]
    _save(kept)
    return len(items) - len(kept)


def due(dt: datetime | None = None) -> list[dict]:
    dt = dt or now_local()
    return [i for i in load() if i.get("enabled", True) and matches(i.get("cron", ""), dt)]
