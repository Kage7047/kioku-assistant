"""Celery tasks, grouped by concern. Task names keep the historical `kioku.worker.tasks.<name>`
form, so queued messages, beat schedules and imports from `kioku.worker.tasks` are unaffected."""
from .vault_ops import vault_audit_task, reindex_vault_task, apply_write_task, sync_vault_task, ingest_task, bulk_ingest_task, digest_batch_task, claim_sweep_task
from .maintenance import reap_stale_runs_task, poll_self_task, self_heal_task
from .actions import execute_approved_task, handoff_result_task
from .agency import project_manager_task, project_checkins_task, propose_skill_task, propose_ideas_task, opportunity_radar_task, self_review_task, learn_task
from .rhythms import morning_brief_task, evening_digest_task, tick_schedules_task, run_scheduled_task, weekly_review_task
from .awareness import poll_all_task, check_alerts_task, watch_signals_task, check_watches_task
from .chat import run_agent_task, handle_input_task

__all__ = [
    "vault_audit_task",
    "reindex_vault_task",
    "apply_write_task",
    "sync_vault_task",
    "ingest_task",
    "bulk_ingest_task",
    "digest_batch_task",
    "claim_sweep_task",
    "reap_stale_runs_task",
    "poll_self_task",
    "self_heal_task",
    "execute_approved_task",
    "handoff_result_task",
    "project_manager_task",
    "project_checkins_task",
    "propose_skill_task",
    "propose_ideas_task",
    "opportunity_radar_task",
    "self_review_task",
    "learn_task",
    "morning_brief_task",
    "evening_digest_task",
    "tick_schedules_task",
    "run_scheduled_task",
    "weekly_review_task",
    "poll_all_task",
    "check_alerts_task",
    "watch_signals_task",
    "check_watches_task",
    "run_agent_task",
    "handle_input_task",
]
