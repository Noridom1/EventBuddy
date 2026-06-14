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
        channel = self.graph.create_channel(self.team_id, display_name=name,
                                             description=objective)
        self.events.set_channel(event.event_id, channel["id"])
        roster = [{"email": e, "role": "member"} for e in member_emails]
        roster.append({"email": host_user_id, "role": "host", "teams_user_id": host_user_id})
        self.members.add_many(event.event_id, roster)
        return event
