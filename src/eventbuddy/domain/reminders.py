from datetime import datetime, timedelta

ESCALATION_RATE_THRESHOLD = 0.5
ESCALATION_MIN_DAYS = 2


def compute_reminder_schedule(start_at: datetime, end_at: datetime) -> dict[str, datetime]:
    return {
        "reminder_d3": start_at - timedelta(days=3),
        "reminder_d1": start_at - timedelta(days=1),
        "reminder_h1": start_at - timedelta(hours=1),
        "feedback_send": end_at,
        "feedback_followup": end_at + timedelta(hours=24),
    }


def should_escalate(*, rate: float, days_elapsed: int) -> bool:
    return rate < ESCALATION_RATE_THRESHOLD and days_elapsed >= ESCALATION_MIN_DAYS
