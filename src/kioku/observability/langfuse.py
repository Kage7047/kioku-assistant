"""Langfuse tracing. Cloud free tier (Hobby): 50k units/mo. Sample to stay under it.

Verify the Langfuse SDK surface for your version; this wraps a run in a trace and
degrades to a no-op if keys are absent so the skeleton runs without observability.
"""
import random
from contextlib import contextmanager

from ..config import settings

try:
    from langfuse import Langfuse
    _lf = Langfuse(
        public_key=settings.langfuse_public_key or None,
        secret_key=settings.langfuse_secret_key or None,
        host=settings.langfuse_host,
    ) if settings.langfuse_public_key else None
except Exception:  # noqa: BLE001
    _lf = None


@contextmanager
def trace_run(run_id: str, kind: str, model: str):
    if _lf is None or random.random() > settings.langfuse_sample_rate:
        yield None
        return
    trace = None
    try:
        trace = _lf.trace(id=run_id, name=kind, metadata={"model_tier": model})
    except Exception:  # noqa: BLE001  (SDK surface varies, e.g. v3 dropped .trace — never fatal)
        trace = None
    try:
        yield trace
    finally:
        try:
            _lf.flush()
        except Exception:  # noqa: BLE001
            pass
