class FeedbackDispatchService:
    """Capability ⑤ (send side) — dispatch the feedback form. Analysis lives in Phase 1.5."""

    def __init__(self, graph_client):
        self.graph = graph_client

    def send_form(self, *, event_name: str, form_link: str, member_emails: list[str]) -> None:
        self.graph.send_mail(
            subject=f"[Feedback] {event_name}",
            body_html=f"<p>Thanks for joining {event_name}! Please share feedback: "
                      f"<a href='{form_link}'>{form_link}</a></p>",
            to=member_emails,
        )
