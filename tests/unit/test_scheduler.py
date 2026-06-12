from datetime import UTC, datetime

from eventbuddy.scheduler.triggers import build_scheduler, schedule_event_jobs


def test_schedule_event_jobs_registers_five_jobs():
    sched = build_scheduler()
    start = datetime(2027, 6, 18, 9, 0, tzinfo=UTC)
    end = datetime(2027, 6, 18, 12, 0, tzinfo=UTC)
    schedule_event_jobs(sched, event_id="ev1", start_at=start, end_at=end)
    job_ids = {j.id for j in sched.get_jobs()}
    assert {"ev1:reminder_d3", "ev1:reminder_d1", "ev1:reminder_h1",
            "ev1:feedback_send", "ev1:feedback_followup"} <= job_ids
