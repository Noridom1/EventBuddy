import contextlib
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent.transcript import Transcript
from eventbuddy.domain.models import ConversationMessage


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    ConversationMessage.__table__.create(engine)
    Local = sessionmaker(bind=engine, expire_on_commit=False)

    @contextlib.contextmanager
    def factory():
        s = Local()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return factory


def test_flush_persists_only_user_and_assistant_turns(session_factory):
    t = Transcript(session_factory=session_factory)
    messages = [
        HumanMessage("hi"),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]),
        ToolMessage(content="tool result", tool_call_id="c1"),
        AIMessage("hello there"),
        HumanMessage("bye"),
    ]
    n = t.flush_window("dm:u1", messages)
    assert n == 3
    with session_factory() as s:
        rows = s.query(ConversationMessage).order_by(ConversationMessage.created_at).all()
    assert [r.role for r in rows] == ["user", "assistant", "user"]
    assert [r.content for r in rows] == ["hi", "hello there", "bye"]


def test_flush_is_idempotent(session_factory):
    t = Transcript(session_factory=session_factory)
    messages = [HumanMessage("hi"), AIMessage("hello")]
    assert t.flush_window("dm:u1", messages) == 2
    assert t.flush_window("dm:u1", messages) == 0  # high-water mark, no double-write
    with session_factory() as s:
        assert s.query(ConversationMessage).count() == 2


def test_flush_appends_only_new_turns(session_factory):
    t = Transcript(session_factory=session_factory)
    t.flush_window("dm:u1", [HumanMessage("q1"), AIMessage("a1")])
    n = t.flush_window(
        "dm:u1",
        [HumanMessage("q1"), AIMessage("a1"), HumanMessage("q2"), AIMessage("a2")],
    )
    assert n == 2
    with session_factory() as s:
        assert s.query(ConversationMessage).count() == 4


def test_rehydrate_returns_recent_within_budget_oldest_first(session_factory):
    base = datetime(2026, 6, 12, tzinfo=UTC)
    with session_factory() as s:
        for i, content in enumerate(["one two three", "four five six", "seven eight", "nine"]):
            s.add(
                ConversationMessage(
                    thread_id="dm:u1",
                    role="user",
                    content=content,
                    created_at=base + timedelta(minutes=i),
                )
            )
    t = Transcript(session_factory=session_factory)  # default word-count token counter
    out = t.rehydrate("dm:u1", budget=4)
    assert [m.content for m in out] == ["seven eight", "nine"]


def test_rehydrate_unknown_thread_is_empty(session_factory):
    t = Transcript(session_factory=session_factory)
    assert t.rehydrate("dm:nobody") == []


def test_rehydrate_tags_speaker_for_user_turns(session_factory):
    t = Transcript(session_factory=session_factory)
    t.flush_window(
        "event:ch1", [HumanMessage(content="hello", name="Alice"), AIMessage("hi Alice")]
    )
    out = t.rehydrate("event:ch1")
    assert isinstance(out[0], HumanMessage) and out[0].name == "Alice"
    assert isinstance(out[1], AIMessage)
