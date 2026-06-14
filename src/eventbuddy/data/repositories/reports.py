from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import Report


class ReportRepository:
    """Persisted AI reports (architecture §6.3 `reports`). One row per generation; the most
    recent is the current report (history kept by `generated_at`)."""

    def __init__(self, session: Session):
        self.s = session

    def create(self, event_id: str, *, metrics_json: dict, summary_md: str,
               suggestions_md: str) -> Report:
        r = Report(event_id=event_id, metrics_json=metrics_json,
                   summary_md=summary_md, suggestions_md=suggestions_md)
        self.s.add(r)
        return r

    def latest(self, event_id: str) -> Report | None:
        return self.s.scalar(
            select(Report).where(Report.event_id == event_id)
            .order_by(desc(Report.generated_at)).limit(1))
