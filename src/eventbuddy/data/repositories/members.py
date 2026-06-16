from __future__ import annotations

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from eventbuddy.domain.identity import CallerIdentity, normalize_email
from eventbuddy.domain.models import EventMember

# Fields an upsert may write/backfill onto a member row (Impl 18).
_UPSERT_FIELDS = ("teams_user_id", "aad_object_id", "email", "display_name")


def member_identity_clause(identity: CallerIdentity):
    """A SQLAlchemy predicate matching an `EventMember` against a `CallerIdentity` (Impl 18):
    the row matches when its `teams_user_id` OR `aad_object_id` is one of the caller's id values,
    OR its (lowercased) `email` equals the caller's email. An empty identity matches nothing.
    Shared by `MemberRepository.get_by_identity` and `EventRepository.list_for_identity`."""
    conds = []
    if identity.id_values:
        conds.append(EventMember.teams_user_id.in_(identity.id_values))
        conds.append(EventMember.aad_object_id.in_(identity.id_values))
    if identity.email:
        conds.append(func.lower(EventMember.email) == identity.email)
    return or_(*conds) if conds else false()


class MemberRepository:
    def __init__(self, session: Session):
        self.s = session

    def add_many(self, event_id: str, members: list[dict]) -> None:
        self.s.add_all([EventMember(event_id=event_id, **m) for m in members])

    def list(self, event_id: str) -> list[EventMember]:
        return list(self.s.scalars(select(EventMember).where(EventMember.event_id == event_id)))

    def get_by_user(self, event_id: str, teams_user_id: str) -> EventMember | None:
        """Back-compat lookup by Bot Framework id only. Prefer `get_by_identity` for callers that
        have the richer identity (AAD id / email) — this stays for the channel/file paths that
        only carry `teams_user_id`."""
        return self.get_by_identity(
            event_id, CallerIdentity.of(teams_user_id=teams_user_id)
        )

    def get_by_identity(
        self, event_id: str, identity: CallerIdentity
    ) -> EventMember | None:
        """Find this event's member matching the caller by ANY identity field (Impl 18)."""
        if identity.is_empty():
            return None
        return self.s.scalar(
            select(EventMember).where(
                EventMember.event_id == event_id,
                member_identity_clause(identity),
            )
        )

    def upsert_member(self, event_id: str, fields: dict) -> EventMember:
        """Idempotently enroll/merge a member (Impl 18). Matches an existing row by identity
        (teams_user_id / aad_object_id / email) and **backfills** any missing id/email/display
        fields onto it — so a member first seen by AAD id + email (group-chat Graph roster) and
        later by Bot Framework id (their own post/DM) collapses to ONE row, never a duplicate.
        Role is never downgraded: it's set only when the row has none yet or the incoming role
        outranks the stored one. Returns the persisted row (flushed)."""
        from eventbuddy.bot.auth import ROLE_RANK

        norm = dict(fields)
        if "email" in norm:
            norm["email"] = normalize_email(norm.get("email"))
        identity = CallerIdentity.of(
            teams_user_id=norm.get("teams_user_id"),
            aad_object_id=norm.get("aad_object_id"),
            email=norm.get("email"),
        )
        existing = None if identity.is_empty() else self.get_by_identity(event_id, identity)
        if existing is None:
            row = EventMember(event_id=event_id, **norm)
            self.s.add(row)
            self.s.flush()
            return row
        for key in _UPSERT_FIELDS:
            value = norm.get(key)
            if value and not getattr(existing, key):
                setattr(existing, key, value)
        incoming_role = norm.get("role")
        if incoming_role and ROLE_RANK.get(incoming_role, 0) > ROLE_RANK.get(existing.role, 0):
            existing.role = incoming_role
        self.s.flush()
        return existing

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
