class ReminderService:
    """Capability ③/④ — omnichannel reminders (architecture §7.3). HITL-gated upstream."""

    def __init__(self, graph_client):
        self.graph = graph_client

    def remind_teams(self, *, chat_id: str, display_name: str, task_name: str,
                     event_name: str) -> None:
        text = (f"Hi {display_name} 👋, your task '{task_name}' for {event_name} "
                f"is due soon — please update the team!")
        self.graph.send_chat_message(chat_id, text)

    def remind_outlook(self, *, email: str, task_name: str, event_name: str) -> None:
        subject = f"Reminder: {task_name} for {event_name}"
        body = (f"<p>Dear colleague,</p><p>This is a friendly reminder that "
                f"'{task_name}' for <b>{event_name}</b> is due soon.</p><p>Thank you.</p>")
        self.graph.send_mail(subject=subject, body_html=body, to=[email])
