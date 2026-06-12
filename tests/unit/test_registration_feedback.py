from eventbuddy.capabilities.feedback import FeedbackDispatchService
from eventbuddy.capabilities.registration import RegistrationService


class _Graph:
    def __init__(self): self.mails = []
    def send_mail(self, subject, body_html, to): self.mails.append((subject, body_html, to))


def test_registration_emails_link_to_all_members():
    graph = _Graph()
    RegistrationService(graph).distribute(
        event_name="AI Workshop", registration_link="http://r", member_emails=["a@x.com"])
    assert graph.mails[0][2] == ["a@x.com"]
    assert "http://r" in graph.mails[0][1]  # link in body


def test_feedback_dispatch_sends_form_link():
    graph = _Graph()
    FeedbackDispatchService(graph).send_form(
        event_name="AI Workshop", form_link="http://f", member_emails=["a@x.com"])
    assert graph.mails[0][2] == ["a@x.com"]
    assert "http://f" in graph.mails[0][1]
