from datetime import UTC, datetime, timedelta

from eventbuddy.domain.reminders import compute_reminder_schedule, should_escalate


def test_compute_reminder_schedule_d3_d1_h1_and_feedback():
    start = datetime(2026, 6, 18, 9, 0, tzinfo=UTC)
    end = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    sched = compute_reminder_schedule(start, end)
    assert sched["reminder_d3"] == start - timedelta(days=3)
    assert sched["reminder_d1"] == start - timedelta(days=1)
    assert sched["reminder_h1"] == start - timedelta(hours=1)
    assert sched["feedback_send"] == end
    assert sched["feedback_followup"] == end + timedelta(hours=24)


def test_should_escalate_low_rate_after_two_days():
    assert should_escalate(rate=0.4, days_elapsed=2) is True
    assert should_escalate(rate=0.8, days_elapsed=2) is False
    assert should_escalate(rate=0.4, days_elapsed=1) is False
