from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from ..config import settings

app = Celery("kioku", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_track_started=True,
    task_time_limit=settings.run_timeout_seconds + 30,   # hard kill safety net
    task_soft_time_limit=settings.run_timeout_seconds,
    worker_prefetch_multiplier=1,
    # Beat honours the user's local timezone, so crontab(hour=7) fires at 07:00 local time,
    # not 07:00 UTC (which was 09:00 local and part of why the brief felt off).
    timezone=settings.timezone,
    enable_utc=False,
)
app.autodiscover_tasks(["kioku.worker"])

# Phase 1: awareness pollers + nightly vault lint.
app.conf.beat_schedule = {
    "poll-all-hourly":    {"task": "kioku.worker.tasks.poll_all_task",       "schedule": 3600},
    "alerts-morning":     {"task": "kioku.worker.tasks.check_alerts_task",    "schedule": crontab(hour=7, minute=30)},
    "watch-signals-15m":  {"task": "kioku.worker.tasks.watch_signals_task",  "schedule": 900},
    "tick-schedules-1m":  {"task": "kioku.worker.tasks.tick_schedules_task", "schedule": 60},
    "check-watches-4h":   {"task": "kioku.worker.tasks.check_watches_task",  "schedule": 14400},

    "weekly-review-sun":  {"task": "kioku.worker.tasks.weekly_review_task",   "schedule": crontab(hour=9, minute=0, day_of_week=0), "args": ("weekly",)},
    "learn-weekly-sun":   {"task": "kioku.worker.tasks.learn_task",          "schedule": crontab(hour=18, minute=0, day_of_week=0)},
    "self-review-sun":    {"task": "kioku.worker.tasks.self_review_task",     "schedule": crontab(hour=20, minute=0, day_of_week=0)},
    "reindex-nightly":    {"task": "kioku.worker.tasks.reindex_vault_task",  "schedule": crontab(hour=3, minute=30)},
    "self-heal-nightly":  {"task": "kioku.worker.tasks.self_heal_task",      "schedule": crontab(hour=4, minute=0)},
    "project-checkins":   {"task": "kioku.worker.tasks.project_checkins_task", "schedule": crontab(hour=9, minute=30)},
    "claim-sweep-nightly":{"task": "kioku.worker.tasks.claim_sweep_task",    "schedule": crontab(hour=4, minute=20)},
    "sync-vault-10min":   {"task": "kioku.worker.tasks.sync_vault_task",     "schedule": 600},
    "reap-stale-runs":    {"task": "kioku.worker.tasks.reap_stale_runs_task", "schedule": 600},
    "brief-daily":        {"task": "kioku.worker.tasks.morning_brief_task",   "schedule": crontab(hour=7, minute=0), "args": ("brief",)},
    "evening-digest":     {"task": "kioku.worker.tasks.evening_digest_task",  "schedule": crontab(hour=21, minute=0)},
    # Job scout twice a week (Mon + Thu, 08:00 local). Non-essential → skips itself if budget is tight.
    "opportunity-radar":  {"task": "kioku.worker.tasks.opportunity_radar_task", "schedule": crontab(hour=8, minute=0, day_of_week="1,4")},
    "propose-ideas-wed":  {"task": "kioku.worker.tasks.propose_ideas_task",     "schedule": crontab(hour=10, minute=0, day_of_week=3)},
}

@worker_ready.connect
def _clone_vault_on_boot(**_):
    """Clone/pull the git-backed vault into the worker's volume before any task writes to it
    (prevents 'writes landed before first clone' and configures commit identity). No-op when
    VAULT_GIT_REMOTE is unset."""
    try:
        from ..memory import vaultsync
        vaultsync.ensure_repo()
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..memory import db
        db.reap_stale_runs_sync(0)   # a fresh worker means any 'running' row is a zombie
    except Exception:  # noqa: BLE001
        pass


from . import tasks  # noqa: E402,F401  (register tasks)
