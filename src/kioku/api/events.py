"""Relay per-run events from Redis pub/sub to the browser/Telegram as SSE.

Robust to the two ways a naive pub/sub relay hangs: (1) the run finished before the client
subscribed (message lost — no subscriber), and (2) a code path that finishes the run WITHOUT
publishing a 'done' (command/capture inputs that don't run the agent). Both are handled by
also reading the run's terminal state from Postgres — on connect and as a periodic fallback."""
import asyncio
import json

import redis.asyncio as aioredis

from ..config import settings
from ..memory import db


async def _terminal_from_db(run_id: str) -> dict | None:
    try:
        row = await db.run_result(run_id)
    except Exception:  # noqa: BLE001
        return None
    if row and row["status"] in ("done", "error"):
        return {"type": "done", "text": row.get("result_text") or row.get("error") or ""}
    return None


async def run_event_stream(run_id: str):
    """Yield SSE events for a run: live via pub/sub, with a Postgres fallback so the stream
    always closes (and shows the result) even if no 'done' was published."""
    r = aioredis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"run:{run_id}")
    try:
        term = await _terminal_from_db(run_id)          # catch-up: already finished?
        if term:
            yield {"event": "run", "data": json.dumps(term)}
            return
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield {"event": "run", "data": data}
                try:
                    if json.loads(data).get("type") == "done":
                        break
                except json.JSONDecodeError:
                    pass
            else:                                        # 1s tick with no live event → poll DB
                term = await _terminal_from_db(run_id)
                if term:
                    yield {"event": "run", "data": json.dumps(term)}
                    break
    finally:
        await pubsub.unsubscribe(f"run:{run_id}")
        await r.aclose()


async def heartbeat():
    while True:
        await asyncio.sleep(15)
        yield {"event": "ping", "data": "{}"}
