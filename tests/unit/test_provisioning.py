from eventbuddy.capabilities.provisioning import ProvisioningService


class _EventRepo:
    def __init__(self): self.created = None
    def create(self, **kw):
        self.created = type("E", (), {"event_id": "ev1", **kw})()
        return self.created
    def set_channel(self, event_id, channel_id): self.created.teams_channel_id = channel_id
    def set_team_id(self, event_id, team_id): self.created.teams_team_id = team_id


class _MemberRepo:
    def __init__(self): self.added = None
    def add_many(self, event_id, members): self.added = members


class _Graph:
    def create_channel(self, team_id, display_name, description=""):
        return {"id": "ch-1"}


def test_create_event_provisions_channel_and_members():
    erepo, mrepo, graph = _EventRepo(), _MemberRepo(), _Graph()
    svc = ProvisioningService(erepo, mrepo, graph, team_id="team-1")
    result = svc.create_event(name="AI Workshop", host_user_id="u1",
                              member_emails=["a@x.com", "b@x.com"], objective="learn")
    assert result.event_id == "ev1"
    assert erepo.created.teams_channel_id == "ch-1"
    # Impl 3: the real team id is stored on the event so later channel calls use it, not tenant.
    assert erepo.created.teams_team_id == "team-1"
    assert len(mrepo.added) == 3  # host + 2 members
    assert any(m["role"] == "host" for m in mrepo.added)
