"""Caller identity as a *set* of equivalent keys (Impl 18).

A single human shows up under different identifiers depending on the conversation and what
we've resolved so far:

- ``teams_user_id`` — the Bot Framework ``29:…`` channel-account id (``from_property.id``). This
  is what every activity carries as the caller id, but it is *per-conversation* and does NOT
  line up with what Microsoft Graph returns for chat/channel members.
- ``aad_object_id`` — the tenant-wide AAD directory GUID. Rides on every activity as
  ``from_property.aad_object_id`` AND is exactly the ``userId`` Graph returns for a chat member,
  so it is the reliable cross-context bridge (group chat ↔ channel ↔ 1-1 DM), available without
  the member ever signing in.
- ``email`` — the corporate address (``alias@corp``); the domain identity, captured from the
  Graph roster, used for display and as a second join key (also how roster/task files line up).

A stored member matches the caller when **any** stored column equals **any** known identity
value. This object normalizes the email and exposes the value sets the repositories match on;
it deliberately keeps no behaviour beyond that so it can live in the domain layer and be shared
by the data layer (``repositories``) and the agent layer (``RequestContext.identity``)."""
from __future__ import annotations

from dataclasses import dataclass


def normalize_email(email: str | None) -> str | None:
    """Lowercase + trim an email for case-insensitive matching, or None when empty."""
    e = (email or "").strip().lower()
    return e or None


@dataclass(frozen=True)
class CallerIdentity:
    teams_user_id: str | None = None
    aad_object_id: str | None = None
    email: str | None = None

    @classmethod
    def of(
        cls,
        *,
        teams_user_id: str | None = None,
        aad_object_id: str | None = None,
        email: str | None = None,
    ) -> CallerIdentity:
        """Build a normalized identity — empty strings collapse to None, email is lowercased."""
        return cls(
            teams_user_id=teams_user_id or None,
            aad_object_id=aad_object_id or None,
            email=normalize_email(email),
        )

    @property
    def id_values(self) -> set[str]:
        """The opaque id values that may appear in `EventMember.teams_user_id` /
        `EventMember.aad_object_id` / `Event.host_user_id` / `Task.assignee_id`. Both the BF id
        and the AAD id are included because, across the id-space transition, either could have
        been written into any of those columns."""
        return {v for v in (self.teams_user_id, self.aad_object_id) if v}

    def is_empty(self) -> bool:
        return not (self.teams_user_id or self.aad_object_id or self.email)

    def matches_id(self, value: str | None) -> bool:
        """True when `value` (a stored id-like column) equals one of this identity's id values."""
        return bool(value) and value in self.id_values

    def matches_email(self, value: str | None) -> bool:
        """True when `value` (a stored email column) equals this identity's normalized email."""
        return bool(self.email) and normalize_email(value) == self.email
