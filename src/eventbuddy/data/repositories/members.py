from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import EventMember


class MemberRepository:
    def __init__(self, session: Session):
        self.s = session

    def add_many(self, event_id: str, members: list[dict]) -> None:
        self.s.add_all([EventMember(event_id=event_id, **m) for m in members])

    def list(self, event_id: str) -> list[EventMember]:
        return list(self.s.scalars(select(EventMember).where(EventMember.event_id == event_id)))

    def get_by_user(self, event_id: str, teams_user_id: str) -> EventMember | None:
        return self.s.scalar(
            select(EventMember).where(
                EventMember.event_id == event_id,
                EventMember.teams_user_id == teams_user_id,
            )
        )

    def set_registration(self, event_id: str, teams_user_id: str, status: str) -> None:
        m = self.get_by_user(event_id, teams_user_id)
        if m:
            m.registration_status = status

    def pending(self, event_id: str) -> list[EventMember]:
        return [m for m in self.list(event_id) if m.registration_status == "pending"]

    def registration_rate(self, event_id: str) -> float:
        members = self.list(event_id)
        if not members:
            return 0.0
        registered = sum(1 for m in members if m.registration_status == "registered")
        return registered / len(members)
