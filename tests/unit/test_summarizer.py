import contextlib

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eventbuddy.agent.summarizer import Summarizer
from eventbuddy.agent.transcript import Transcript
from eventbuddy.domain.models import ConversationMessage, SessionSummary


class _FakeLLM:
    def __init__(self):
        self.calls = []

    def summarize(self, text, instruction):
        self.calls.append((text, instruction))
        return f"SUMMARY({len(self.calls)})"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    ConversationMessage.__table__.create(engine)
    SessionSummary.__table__.create(engine)
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


def test_summarize_session_folds_turns_and_sets_watermark(session_factory):
    Transcript(session_factory=session_factory).flush_window(
        "dm:u1", [HumanMessage("hi"), AIMessage("hello")]
    )
    llm = _FakeLLM()
    summ = Summarizer(llm, session_factory=session_factory)

    assert summ.summarize_session("dm:u1") is True
    assert len(llm.calls) == 1
    with session_factory() as s:
        row = s.get(SessionSummary, "dm:u1")
    assert row.summary == "SUMMARY(1)"
    assert row.covered_through is not None
    assert summ.get_summary("dm:u1") == "SUMMARY(1)"


def test_no_new_turns_is_noop_no_llm_call(session_factory):
    Transcript(session_factory=session_factory).flush_window(
        "dm:u1", [HumanMessage("hi"), AIMessage("hello")]
    )
    llm = _FakeLLM()
    summ = Summarizer(llm, session_factory=session_factory)
    summ.summarize_session("dm:u1")
    assert summ.summarize_session("dm:u1") is False  # nothing newer than watermark
    assert len(llm.calls) == 1  # no second LLM call


def test_summarize_session_folds_prior_summary(session_factory):
    t = Transcript(session_factory=session_factory)
    llm = _FakeLLM()
    summ = Summarizer(llm, session_factory=session_factory)

    t.flush_window("dm:u1", [HumanMessage("q1"), AIMessage("a1")])
    summ.summarize_session("dm:u1")
    t.flush_window(
        "dm:u1",
        [HumanMessage("q1"), AIMessage("a1"), HumanMessage("q2"), AIMessage("a2")],
    )
    assert summ.summarize_session("dm:u1") is True

    second_text = llm.calls[1][0]
    assert "Previous summary:\nSUMMARY(1)" in second_text
    assert "q2" in second_text and "q1" not in second_text  # only new turns folded in


def test_summarize_all_processes_pending_threads(session_factory):
    t = Transcript(session_factory=session_factory)
    t.flush_window("dm:a", [HumanMessage("x"), AIMessage("y")])
    t.flush_window("event:b", [HumanMessage("p"), AIMessage("q")])
    summ = Summarizer(_FakeLLM(), session_factory=session_factory)
    assert summ.summarize_all() == 2
    assert summ.summarize_all() == 0  # all caught up


def test_unknown_thread_summary_empty(session_factory):
    summ = Summarizer(_FakeLLM(), session_factory=session_factory)
    assert summ.get_summary("dm:nobody") == ""
