from eventbuddy.agent.graph import build_agent_graph


class _Orch:
    def handle(self, *, user_id, channel_id, text):
        return f"handled:{text}"


def test_graph_runs_orchestrator_node():
    graph = build_agent_graph(_Orch())
    out = graph.invoke({"user_id": "u1", "channel_id": None, "text": "hello"})
    assert out["reply"] == "handled:hello"
