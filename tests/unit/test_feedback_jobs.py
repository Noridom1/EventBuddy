from eventbuddy.config import settings
from eventbuddy.scheduler.jobs import (
    _feedback_form_link,
    _non_responders,
    run_feedback_followup,
    run_feedback_send,
)


def test_run_feedback_send_invokes_injected_sender():
    calls = []
    run_feedback_send("ev1", sender=lambda e: calls.append(e) or 3)
    assert calls == ["ev1"]


def test_run_feedback_followup_invokes_injected_sender():
    calls = []
    run_feedback_followup("ev1", sender=lambda e: calls.append(e) or 0)
    assert calls == ["ev1"]


def test_feedback_jobs_swallow_sender_errors():
    def boom(event_id):
        raise RuntimeError("graph down")

    run_feedback_send("ev1", sender=boom)        # best-effort: must not raise
    run_feedback_followup("ev1", sender=boom)


def test_non_responders_is_case_insensitive():
    members = ["A@x.com", "b@x.com", "c@x.com"]
    responded = {"a@x.com", "c@x.com"}
    assert _non_responders(members, responded) == ["b@x.com"]


def test_feedback_form_link_interpolates_event_id(monkeypatch):
    monkeypatch.setattr(settings, "feedback_form_url", "https://forms/r?ev={event_id}")
    assert _feedback_form_link("ev1") == "https://forms/r?ev=ev1"


def test_feedback_form_link_empty_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "feedback_form_url", "")
    assert _feedback_form_link("ev1") == ""
