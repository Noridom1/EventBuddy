from eventbuddy.capabilities.broadcast import BroadcastService


class _Graph:
    def __init__(self):
        self.channel_msgs = []
        self.mails = []
    def send_channel_message(self, team_id, channel_id, text): self.channel_msgs.append(text)
    def send_mail(self, subject, body_html, to): self.mails.append((subject, to))


class _LLM:
    def chat(self, messages, model=None): return "Join us for AI Workshop!"


def test_broadcast_posts_to_channel_and_emails_members():
    graph, llm = _Graph(), _LLM()
    svc = BroadcastService(graph, llm, team_id="team-1")
    svc.broadcast(channel_id="ch-1", event_name="AI Workshop",
                  when="18/06 09:00", registration_link="http://r",
                  member_emails=["a@x.com", "b@x.com"])
    assert graph.channel_msgs and "AI Workshop" in graph.channel_msgs[0]
    assert graph.mails[0][1] == ["a@x.com", "b@x.com"]
