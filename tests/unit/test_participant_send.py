"""Impl 4 — the module-level participant-roster helpers in wiring: status filtering, the
bounded summary, and attachment selection."""
from eventbuddy.agent.wiring import (
    _filter_emails_by_status,
    _pick_roster_attachment,
    _summarize_roster,
)
from eventbuddy.ingestion.parsers import parse
from eventbuddy.ingestion.roster import extract_roster

_ROWS = [
    {"email": "a@x.com", "status": "Yes"},
    {"email": "b@x.com", "status": "No"},
    {"email": "c@x.com", "status": "Pending"},
    {"email": "d@x.com"},  # no status
]


def test_filter_empty_status_returns_everyone():
    assert _filter_emails_by_status(_ROWS, "") == ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]


def test_filter_by_status_value_case_insensitive():
    assert _filter_emails_by_status(_ROWS, "no") == ["b@x.com"]
    assert _filter_emails_by_status(_ROWS, "Pending") == ["c@x.com"]


def test_filter_skips_rows_without_status_when_filtering():
    # "d@x.com" has no status, so a status filter never includes it.
    assert "d@x.com" not in _filter_emails_by_status(_ROWS, "yes")


def test_pick_roster_attachment_prefers_spreadsheet():
    atts = [{"name": "notes.pdf"}, {"name": "list.csv"}]
    assert _pick_roster_attachment(atts)["name"] == "list.csv"


def test_pick_roster_attachment_falls_back_to_other_parseable():
    atts = [{"name": "image.png"}, {"name": "people.pdf"}]
    assert _pick_roster_attachment(atts)["name"] == "people.pdf"


def test_pick_roster_attachment_none_when_no_parseable_file():
    assert _pick_roster_attachment([{"name": "image.png"}]) is None


def test_summary_reports_counts_status_and_token():
    reading = extract_roster(
        parse("r.csv", b"Email,Registered\na@x.com,Yes\nb@x.com,No\n")
    )
    out = _summarize_roster("r.csv", reading, "tok-9")
    assert "2 unique participant email" in out
    assert "Registered" in out and "file_token: tok-9" in out
    # bounded: counts + sample, never the entire address list dumped raw
    assert "send_participant_reminders" in out
