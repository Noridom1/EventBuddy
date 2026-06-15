class ProvisioningService:
    """Creates an event, its Teams channel, and the member roster (architecture §7.1)."""

    def __init__(self, event_repo, member_repo, graph_client, team_id: str):
        self.events = event_repo
        self.members = member_repo
        self.graph = graph_client
        self.team_id = team_id

    def create_event(self, *, name: str, host_user_id: str, member_emails: list[str],
                     objective: str = "") -> object:
        event = self.events.create(event_name=name, host_user_id=host_user_id,
                                   objective=objective, status="ideation")
        # No Graph client (delegated auth: host not signed in yet, or no creds) → persist the
        # event locally only and skip channel creation, per the graceful-degradation invariant
        # (CLAUDE.md). With a client, the channel is created as the signed-in host (Plan 13).
        channel = (
            self.graph.create_channel(self.team_id, display_name=name, description=objective)
            if self.graph is not None
            else None
        )
        if channel:
            self.events.set_channel(event.event_id, channel["id"])
            # Persist the real team id now (Impl 3) so later channel sends/reads use it instead
            # of the tenant id. `self.team_id` is the team the channel was created under.
            if self.team_id:
                self.events.set_team_id(event.event_id, self.team_id)
        roster = [{"email": e, "role": "member"} for e in member_emails]
        roster.append({"email": host_user_id, "role": "host", "teams_user_id": host_user_id})
        self.members.add_many(event.event_id, roster)
        return event
