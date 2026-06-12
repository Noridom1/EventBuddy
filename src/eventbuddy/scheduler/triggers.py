from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from eventbuddy.domain.reminders import compute_reminder_schedule
from eventbuddy.scheduler.jobs import (
    run_feedback_followup,
    run_feedback_send,
    run_reminder,
    run_summarize_sessions,
)


def build_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(timezone="UTC")


def schedule_event_jobs(scheduler, *, event_id: str, start_at: datetime, end_at: datetime) -> None:
    sched_times = compute_reminder_schedule(start_at, end_at)
    for kind in ("reminder_d3", "reminder_d1", "reminder_h1"):
        scheduler.add_job(run_reminder, "date", run_date=sched_times[kind],
                          args=[event_id, kind], id=f"{event_id}:{kind}", replace_existing=True)
    scheduler.add_job(run_feedback_send, "date", run_date=sched_times["feedback_send"],
                      args=[event_id], id=f"{event_id}:feedback_send", replace_existing=True)
    scheduler.add_job(run_feedback_followup, "date", run_date=sched_times["feedback_followup"],
                      args=[event_id], id=f"{event_id}:feedback_followup", replace_existing=True)


def schedule_summarizer(scheduler, summarizer, *, minutes: int = 5) -> None:
    """Register the periodic rolling-summary consolidation job (Phase 1.7)."""
    scheduler.add_job(
        run_summarize_sessions, "interval", minutes=minutes, args=[summarizer],
        id="summarize_sessions", replace_existing=True,
    )


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    return _scheduler


def shutdown_scheduler(scheduler) -> None:
    if scheduler:
        scheduler.shutdown(wait=False)
