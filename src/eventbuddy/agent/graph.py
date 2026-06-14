from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, StateGraph


class AgentState(TypedDict, total=False):
    user_id: str
    channel_id: str | None
    text: str
    sent_at: datetime | None
    reply: str


def build_agent_graph(orchestrator):
    def run_node(state: AgentState) -> AgentState:
        reply = orchestrator.handle(
            user_id=state["user_id"],
            channel_id=state.get("channel_id"),
            text=state["text"],
            sent_at=state.get("sent_at"),
        )
        return {"reply": reply}

    g = StateGraph(AgentState)
    g.add_node("orchestrate", run_node)
    g.set_entry_point("orchestrate")
    g.add_edge("orchestrate", END)
    return g.compile()
