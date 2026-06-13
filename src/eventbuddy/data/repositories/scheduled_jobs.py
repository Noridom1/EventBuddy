from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import ScheduledJob


class ScheduledJobRepository:
    """Durable, queryable record of scheduled work (architecture §12). The APScheduler
    jobstore owns the *timers*; these rows make the schedule observable and carry the
    `queued → sent/failed` status the architecture's `scheduled_jobs` table specifies.
    Keyed by (event_id, job_type) — one row per kind per event."""

    def __init__(self, session: Session):
        self.s = session

    def _get(self, event_id: str, job_type: str) -> ScheduledJob | None:
        return self.s.scalar(
            select(ScheduledJob).where(
                ScheduledJob.event_id == event_id, ScheduledJob.job_type == job_type
            )
        )

    def upsert(self, *, event_id: str, job_type: str, scheduled_at: datetime,
               channel: str | None = None, status: str = "queued") -> None:
        row = self._get(event_id, job_type)
        if row is None:
            self.s.add(ScheduledJob(
                event_id=event_id, job_type=job_type, scheduled_at=scheduled_at,
                channel=channel, status=status,
            ))
        else:
            row.scheduled_at = scheduled_at
            row.channel = channel
            row.status = status

    def set_status(self, *, event_id: str, job_type: str, status: str) -> None:
        row = self._get(event_id, job_type)
        if row is not None:
            row.status = status
