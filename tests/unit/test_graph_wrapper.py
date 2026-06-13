from eventbuddy.agent.graph import build_agent_graph


class _Orch:
    def __init__(self):
        self.seen = {}

    def handle(self, *, user_id, channel_id, text, sent_at=None):
        self.seen["sent_at"] = sent_at
        return f"handled:{text}"


def test_graph_runs_orchestrator_node():
    graph = build_agent_graph(_Orch())
    out = graph.invoke({"user_id": "u1", "channel_id": None, "text": "hello"})
    assert out["reply"] == "handled:hello"


def test_graph_forwards_sent_at():
    from datetime import UTC, datetime
    orch = _Orch()
    graph = build_agent_graph(orch)
    ts = datetime(2026, 6, 11, 14, 30, tzinfo=UTC)
    graph.invoke({"user_id": "u1", "channel_id": None, "text": "hi", "sent_at": ts})
    assert orch.seen["sent_at"] == ts
