from collections.abc import Callable

from sqlalchemy.orm import Session

from eventbuddy.common.errors import NotAuthorizedError

ROLE_RANK = {"member": 1, "moderator": 2, "host": 3}


class Gatekeeper:
    """Authorizes a user for an event action by membership + role rank."""

    def __init__(self, member_repo_factory: Callable[[Session], object]):
        self._repo_factory = member_repo_factory

    def authorize(self, *, session: Session, user_id: str, event_id: str, min_role: str) -> None:
        repo = self._repo_factory(session)
        member = repo.get_by_user(event_id, user_id)
        if member is None:
            raise NotAuthorizedError(f"{user_id} is not a member of event {event_id}")
        if ROLE_RANK.get(member.role, 0) < ROLE_RANK[min_role]:
            raise NotAuthorizedError(f"{user_id} role '{member.role}' < required '{min_role}'")
