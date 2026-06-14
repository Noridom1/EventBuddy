from datetime import UTC, datetime

from eventbuddy.agent.context import RequestContext
from eventbuddy.agent.prompts import system_prompt


def test_prompt_has_guardrail_phrases():
    p = system_prompt(RequestContext(user_id="u1")).lower()
    assert "eventbuddy" in p
    assert "tool" in p
    assert "never invent" in p
    assert "clarifying question" in p
    assert "server" in p


def test_prompt_interpolates_focused_event():
    p = system_prompt(RequestContext(user_id="u1", current_event_id="ev-42"))
    assert "ev-42" in p


def test_prompt_notes_no_focus_when_unset():
    p = system_prompt(RequestContext(user_id="u1"))
    assert "No event is focused" in p


def test_system_prompt_includes_now():
    p = system_prompt(RequestContext(user_id="u1"), now=datetime(2026, 6, 13, 9, 30, tzinfo=UTC))
    assert "2026-06-13 09:30 UTC" in p
    assert "current date and time" in p.lower()
