from eventbuddy.capabilities.reminders import ReminderService


class _Graph:
    def __init__(self):
        self.chat_msgs = []
        self.mails = []
    def send_chat_message(self, chat_id, text, content_type="text"):
        self.chat_msgs.append((chat_id, text))
    def send_mail(self, subject, body_html, to): self.mails.append(to)


def test_remind_via_teams_sends_personalized_chat():
    graph = _Graph()
    svc = ReminderService(graph)
    svc.remind_teams(chat_id="c1", display_name="Huy", task_name="slides",
                     event_name="AI Workshop")
    chat_id, text = graph.chat_msgs[0]
    assert chat_id == "c1" and "Huy" in text and "slides" in text


def test_remind_via_outlook_sends_formal_mail():
    graph = _Graph()
    svc = ReminderService(graph)
    svc.remind_outlook(email="speaker@ext.com", task_name="slides", event_name="AI Workshop")
    assert graph.mails[0] == ["speaker@ext.com"]
