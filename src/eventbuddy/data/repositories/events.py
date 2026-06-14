from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import Event


class EventRepository:
    def __init__(self, session: Session):
        self.s = session

    def create(self, **kwargs) -> Event:
        ev = Event(**kwargs)
        self.s.add(ev)
        # Flush so the `new_id` primary-key default fires now: callers (e.g. ProvisioningService)
        # use `ev.event_id` immediately — for set_channel / add_many — within the same session,
        # before the outer session_scope commit.
        self.s.flush()
        return ev

    def get(self, event_id: str) -> Event | None:
        return self.s.get(Event, event_id)

    def by_channel(self, channel_id: str) -> Event | None:
        return self.s.scalar(select(Event).where(Event.teams_channel_id == channel_id))

    def set_channel(self, event_id: str, channel_id: str) -> None:
        self.s.get(Event, event_id).teams_channel_id = channel_id

    def set_status(self, event_id: str, status: str) -> None:
        self.s.get(Event, event_id).status = status

    def set_feedback_sources(self, event_id: str, *, form_url: str | None = None,
                             workbook_url: str | None = None) -> None:
        """Set the per-event feedback Form / responses-workbook links (Impl 2). Only the
        provided fields are updated, so callers can set one without clobbering the other."""
        ev = self.s.get(Event, event_id)
        if ev is None:
            return
        if form_url is not None:
            ev.feedback_form_url = form_url
        if workbook_url is not None:
            ev.feedback_workbook_url = workbook_url
