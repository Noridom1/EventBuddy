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
