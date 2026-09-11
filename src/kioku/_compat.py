"""Run an async coroutine from sync code (Celery tasks) on a persistent event loop.

Celery workers are synchronous and have no running loop, so we keep ONE long-lived
event loop per process and reuse it for every call. This is REQUIRED, not cosmetic:
memory/db.py caches its asyncpg pool in a module global, and an asyncpg pool binds to
the loop that created it. Spinning up a fresh `asyncio.run()` per call — which closes
its loop when it returns — would leave the cached pool bound to a dead loop, so every
DB call after the first would raise "got Future attached to a different loop".
"""
import asyncio
import threading

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _persistent_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        with _lock:
            if _loop is None or _loop.is_closed():
                _loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_loop)
    return _loop


def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Normal Celery path: no loop running -> use the process's persistent loop.
        return _persistent_loop().run_until_complete(coro)
    # Rare: called from within a running loop. Run on a private loop in a worker thread
    # so we don't try to re-enter the active loop.
    box: dict = {}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            box["value"] = loop.run_until_complete(coro)
        except BaseException as e:  # noqa: BLE001
            box["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=_runner)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]
