"""The pure Graph dispatch for a confirmed action (`wiring._perform_send`). Verifies channel
routing and the PII rule (§11): mail/reminders go out **individually**, never a shared To/CC."""
from eventbuddy.agent.wiring import _perform_send


class _Graph:
    def __init__(self):
        self.mails = []        # each entry is a `to` list
        self.channel_posts = []

    def send_mail(self, subject, body_html, to):
        self.mails.append(to)

    def send_channel_message(self, team_id, channel_id, text):
        self.channel_posts.append((channel_id, text))


def test_remind_outlook_sends_individually():
    g = _Graph()
    payload = {"type": "remind", "event_name": "Launch", "task_name": "slides",
               "recipient_emails": ["a@x.com", "b@x.com"]}
    ok, summary = _perform_send(graph=g, payload=payload, channel="outlook")
    assert ok and "2" in summary
    assert g.mails == [["a@x.com"], ["b@x.com"]]  # one recipient per send — no shared To/CC


def test_remind_teams_posts_to_channel():
    g = _Graph()
    payload = {"type": "remind", "event_name": "Launch", "task_name": "slides",
               "channel_id": "ch-9", "recipient_emails": ["a@x.com"]}
    ok, summary = _perform_send(graph=g, payload=payload, channel="teams")
    assert ok and "channel" in summary.lower()
    assert g.channel_posts[0][0] == "ch-9" and "slides" in g.channel_posts[0][1]
    assert g.mails == []  # teams path doesn't email


def test_remind_teams_without_channel_fails_cleanly():
    g = _Graph()
    payload = {"type": "remind", "recipient_emails": ["a@x.com"]}  # no channel_id
    ok, summary = _perform_send(graph=g, payload=payload, channel="teams")
    assert ok is False and "channel" in summary.lower()


def test_mail_sends_individually():
    g = _Graph()
    payload = {"type": "mail", "subject": "Hi", "body_html": "<p>x</p>",
               "recipient_emails": ["a@x.com", "b@x.com", "c@x.com"]}
    ok, summary = _perform_send(graph=g, payload=payload, channel=None)
    assert ok and "3" in summary
    assert g.mails == [["a@x.com"], ["b@x.com"], ["c@x.com"]]


def test_mail_teams_channel_posts_notice_not_email():
    # Impl 4 — a participant-reminder mail confirmed via the Teams branch posts ONE channel
    # notice (a broadcast), never per-recipient email.
    g = _Graph()
    payload = {"type": "mail", "subject": "Register now", "notice_text": "Please register",
               "channel_id": "ch-1", "team_id": "team-2", "event_name": "Workshop",
               "recipient_emails": ["a@x.com", "b@x.com"]}
    ok, summary = _perform_send(graph=g, payload=payload, channel="teams")
    assert ok and "channel" in summary.lower()
    assert g.channel_posts and g.channel_posts[0][0] == "ch-1"
    assert "Register now" in g.channel_posts[0][1]
    assert g.mails == []  # the Teams broadcast never emails the file's addresses


def test_mail_teams_without_channel_fails_cleanly():
    g = _Graph()
    payload = {"type": "mail", "subject": "x", "recipient_emails": ["a@x.com"]}
    ok, summary = _perform_send(graph=g, payload=payload, channel="teams")
    assert ok is False and "channel" in summary.lower()


def test_mail_outlook_still_sends_individually_with_channel_set():
    # The Outlook choice on the same card → per-recipient email, unchanged behavior.
    g = _Graph()
    payload = {"type": "mail", "subject": "Hi", "body_html": "<p>x</p>",
               "recipient_emails": ["a@x.com", "b@x.com"]}
    ok, summary = _perform_send(graph=g, payload=payload, channel="outlook")
    assert ok and g.mails == [["a@x.com"], ["b@x.com"]]


def test_unknown_action_fails_without_sending():
    g = _Graph()
    ok, summary = _perform_send(graph=g, payload={"type": "frobnicate"}, channel=None)
    assert ok is False
    assert g.mails == [] and g.channel_posts == []
