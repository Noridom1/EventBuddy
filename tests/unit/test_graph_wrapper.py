from eventbuddy.agent.graph import build_agent_graph


class _Orch:
    def __init__(self):
        self.seen = {}

    def handle(self, *, user_id, channel_id, text, scope="personal", sent_at=None,
               team_id=None, attachments=None):
        self.seen["sent_at"] = sent_at
        self.seen["scope"] = scope
        self.seen["team_id"] = team_id
        self.seen["attachments"] = attachments
        return f"handled:{text}"


def test_graph_runs_orchestrator_node():
    graph = build_agent_graph(_Orch())
    out = graph.invoke({"user_id": "u1", "channel_id": None, "text": "hello"})
    assert out["reply"] == "handled:hello"


def test_graph_forwards_scope_and_team_id():
    orch = _Orch()
    graph = build_agent_graph(orch)
    graph.invoke({"user_id": "u1", "channel_id": "c1", "text": "hi",
                  "scope": "channel", "team_id": "team-9"})
    assert orch.seen["scope"] == "channel" and orch.seen["team_id"] == "team-9"


def test_graph_forwards_attachments():
    orch = _Orch()
    graph = build_agent_graph(orch)
    atts = [{"name": "roster.csv", "download_url": "https://dl"}]
    graph.invoke({"user_id": "u1", "channel_id": None, "text": "hi", "attachments": atts})
    assert orch.seen["attachments"] == atts


def test_graph_forwards_sent_at():
    from datetime import UTC, datetime
    orch = _Orch()
    graph = build_agent_graph(orch)
    ts = datetime(2026, 6, 11, 14, 30, tzinfo=UTC)
    graph.invoke({"user_id": "u1", "channel_id": None, "text": "hi", "sent_at": ts})
    assert orch.seen["sent_at"] == ts
