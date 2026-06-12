import pytest

from eventbuddy.bot.auth import ROLE_RANK, Gatekeeper
from eventbuddy.common.errors import NotAuthorizedError


class _Member:
    def __init__(self, role):
        self.role = role


class _Repo:
    def __init__(self, member):
        self._m = member

    def get_by_user(self, event_id, user_id):
        return self._m


def test_authorize_allows_member_for_member_action():
    gk = Gatekeeper(lambda s: _Repo(_Member("member")))
    gk.authorize(session=None, user_id="u", event_id="e", min_role="member")  # no raise


def test_authorize_rejects_insufficient_role():
    gk = Gatekeeper(lambda s: _Repo(_Member("member")))
    with pytest.raises(NotAuthorizedError):
        gk.authorize(session=None, user_id="u", event_id="e", min_role="moderator")


def test_authorize_rejects_non_member():
    gk = Gatekeeper(lambda s: _Repo(None))
    with pytest.raises(NotAuthorizedError):
        gk.authorize(session=None, user_id="u", event_id="e", min_role="member")


def test_role_rank_ordering():
    assert ROLE_RANK["host"] > ROLE_RANK["moderator"] > ROLE_RANK["member"]
