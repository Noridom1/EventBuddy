from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from eventbuddy.common.logging import get_logger
from eventbuddy.domain.reminders import compute_reminder_schedule
from eventbuddy.scheduler.jobs import (
    run_feedback_followup,
    run_feedback_send,
    run_reminder,
    run_summarize_sessions,
)

log = get_logger("scheduler.triggers")


def build_scheduler(persistent: bool = False) -> BackgroundScheduler:
    """In-memory by default (offline/test-friendly). `persistent=True` adds a Postgres
    SQLAlchemy jobstore so scheduled timers survive a restart — guarded so a DB hiccup
    degrades to in-memory rather than blocking startup (degradation principle)."""
    if persistent:
        try:
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

            from eventbuddy.config import settings
            jobstores = {"default": SQLAlchemyJobStore(url=settings.database_url)}
            return BackgroundScheduler(timezone="UTC", jobstores=jobstores)
        except Exception as e:  # noqa: BLE001
            log.warning(f"persistent jobstore unavailable ({type(e).__name__}: {e}); in-memory")
    return BackgroundScheduler(timezone="UTC")


def _record_scheduled_jobs(event_id: str, sched_times: dict) -> None:
    """Best-effort durable rows for observability (architecture §12 `scheduled_jobs`). The
    APScheduler jobstore owns the timers; these make the schedule queryable. Guarded so the
    offline path (no DB) still registers the in-memory jobs."""
    try:
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.scheduled_jobs import ScheduledJobRepository
        with session_scope() as s:
            repo = ScheduledJobRepository(s)
            for job_type, when in sched_times.items():
                repo.upsert(event_id=event_id, job_type=job_type, scheduled_at=when)
    except Exception as e:  # noqa: BLE001
        log.warning(f"scheduled_jobs rows not written ({type(e).__name__}: {e})")


def schedule_event_jobs(scheduler, *, event_id: str, start_at: datetime, end_at: datetime) -> None:
    sched_times = compute_reminder_schedule(start_at, end_at)
    for kind in ("reminder_d3", "reminder_d1", "reminder_h1"):
        scheduler.add_job(run_reminder, "date", run_date=sched_times[kind],
                          args=[event_id, kind], id=f"{event_id}:{kind}", replace_existing=True)
    scheduler.add_job(run_feedback_send, "date", run_date=sched_times["feedback_send"],
                      args=[event_id], id=f"{event_id}:feedback_send", replace_existing=True)
    scheduler.add_job(run_feedback_followup, "date", run_date=sched_times["feedback_followup"],
                      args=[event_id], id=f"{event_id}:feedback_followup", replace_existing=True)
    _record_scheduled_jobs(event_id, sched_times)


def schedule_summarizer(scheduler, summarizer, *, minutes: int = 5) -> None:
    """Register the periodic rolling-summary consolidation job (Phase 1.7)."""
    scheduler.add_job(
        run_summarize_sessions, "interval", minutes=minutes, args=[summarizer],
        id="summarize_sessions", replace_existing=True,
    )


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    _scheduler = build_scheduler(persistent=True)
    _scheduler.start()
    return _scheduler


def shutdown_scheduler(scheduler) -> None:
    if scheduler:
        scheduler.shutdown(wait=False)
