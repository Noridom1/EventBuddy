class RegistrationService:
    """Capability ② — distribute the registration link (+ calendar invite later)."""

    def __init__(self, graph_client):
        self.graph = graph_client

    def distribute(self, *, event_name: str, registration_link: str,
                   member_emails: list[str]) -> None:
        self.graph.send_mail(
            subject=f"[Register] {event_name}",
            body_html=f"<p>Please register for {event_name}: "
                      f"<a href='{registration_link}'>{registration_link}</a></p>",
            to=member_emails,
        )
