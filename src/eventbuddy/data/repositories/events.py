from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import Event, EventMember


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

    def set_team_id(self, event_id: str, team_id: str) -> None:
        """Store the event channel's real Teams team/group id (Impl 3). Idempotent — callers
        only set it when currently null (backfill on first channel message / at provision)."""
        ev = self.s.get(Event, event_id)
        if ev is not None:
            ev.teams_team_id = team_id

    def list_for_user(self, teams_user_id: str) -> list[tuple[Event, str]]:
        """Events the caller participates in (Impl 3) — as a member or as the host — newest
        first, paired with the caller's role for that event. Used by `list_my_events` so a
        user can see and focus their events from a DM."""
        rows = self.s.execute(
            select(Event, EventMember.role)
            .join(EventMember, EventMember.event_id == Event.event_id)
            .where(EventMember.teams_user_id == teams_user_id)
            .order_by(Event.created_at.desc())
        ).all()
        seen = {ev.event_id for ev, _ in rows}
        result: list[tuple[Event, str]] = [(ev, role) for ev, role in rows]
        # Events the user hosts but isn't a roster member of (host_user_id set at create time
        # before a teams_user_id-backed membership row exists).
        hosted = self.s.scalars(
            select(Event)
            .where(Event.host_user_id == teams_user_id)
            .order_by(Event.created_at.desc())
        )
        for ev in hosted:
            if ev.event_id not in seen:
                seen.add(ev.event_id)
                result.append((ev, "host"))
        return result

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
