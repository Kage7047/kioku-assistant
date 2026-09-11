"""Watch mode — things Kioku keeps an eye on and alerts you when they change.

A watch is "monitor <something> and tell me when it materially changes" — a job posting, a
competitor's Google profile, a metric, an email thread. Stored as JSON in the git-backed vault
(`system/watches.json`, truth + editable). A scheduled task re-checks each watch on a cadence,
compares to the last observed state, and pings Telegram on a real change.
"""
import json
import uuid
from datetime import datetime

from . import vault as V

REL = "system/watches.json"


def load() -> list[dict]:
    try:
        data = json.loads(V.read(REL))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def save(items: list[dict]) -> None:
    V.write(REL, json.dumps(items, indent=2, ensure_ascii=False) + "\n", approved=True)


def add(what: str, note: str = "") -> str:
    items = load()
    wid = uuid.uuid4().hex[:8]
    items.append({"id": wid, "what": what.strip(), "note": note.strip(),
                  "last_state": "", "created": datetime.now().isoformat(timespec="seconds")})
    save(items)
    return wid


def remove(wid: str) -> int:
    items = load()
    kept = [i for i in items if i.get("id") != wid]
    save(kept)
    return len(items) - len(kept)


def update_state(wid: str, state: str) -> None:
    items = load()
    for i in items:
        if i.get("id") == wid:
            i["last_state"] = state[:1000]
            i["checked"] = datetime.now().isoformat(timespec="seconds")
    save(items)
