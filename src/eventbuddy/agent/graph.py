from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, StateGraph


class AgentState(TypedDict, total=False):
    user_id: str
    channel_id: str | None
    text: str
    sent_at: datetime | None
    # Conversation scope ("personal" | "channel") and the real Teams team id, derived from the
    # inbound activity (Impl 3). Both default-safe: a missing scope is treated as "personal".
    scope: str
    team_id: str | None
    # Impl 4 — descriptors for files attached to this turn; forwarded to the orchestrator so a
    # tool can read them. Default-safe: a turn with no files carries an empty list.
    attachments: list[dict]
    # Plan 13 — delegated Graph bearer token for this caller, acquired at ingress (Teams SSO).
    # Default-safe: None when delegated auth isn't configured / the user isn't signed in.
    graph_token: str | None
    reply: str


def build_agent_graph(orchestrator):
    def run_node(state: AgentState) -> AgentState:
        reply = orchestrator.handle(
            user_id=state["user_id"],
            channel_id=state.get("channel_id"),
            text=state["text"],
            scope=state.get("scope", "personal"),
            sent_at=state.get("sent_at"),
            team_id=state.get("team_id"),
            attachments=state.get("attachments"),
            graph_token=state.get("graph_token"),
        )
        return {"reply": reply}

    g = StateGraph(AgentState)
    g.add_node("orchestrate", run_node)
    g.set_entry_point("orchestrate")
    g.add_edge("orchestrate", END)
    return g.compile()
