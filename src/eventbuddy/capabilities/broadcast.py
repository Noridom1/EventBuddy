from eventbuddy.agent.formatting import render_markdown


class BroadcastService:
    """Capability ① — announce an event on Teams + Outlook (architecture §5 capabilities)."""

    def __init__(self, graph_client, llm_gateway, team_id: str):
        self.graph = graph_client
        self.llm = llm_gateway
        self.team_id = team_id

    def _compose(self, event_name: str, when: str, link: str) -> str:
        prompt = [
            {"role": "system", "content": "Write a short, friendly internal event announcement."},
            {"role": "user", "content": f"Event: {event_name}\nWhen: {when}\nRegister: {link}"},
        ]
        return self.llm.chat(prompt)

    def broadcast(self, *, channel_id: str, event_name: str, when: str,
                  registration_link: str, member_emails: list[str]) -> None:
        body = self._compose(event_name, when, registration_link)
        text = f"📢 {event_name}\n{body}\nRegister: {registration_link}"
        self.graph.send_channel_message(self.team_id, channel_id, text)
        self.graph.send_mail(subject=f"[Event] {event_name}",
                             body_html=render_markdown(body)
                             + f'<p>Register: <a href="{registration_link}">'
                               f"{registration_link}</a></p>",
                             to=member_emails)
