"""Impl 4 — participant-roster extraction (`extract_roster`). Emails are pulled from any
column; a name/status column is detected opportunistically (advisory only — the file's own
data, never EventBuddy state)."""
from eventbuddy.ingestion.parsers import parse
from eventbuddy.ingestion.roster import RosterReading, extract_roster


def _csv(text: str):
    return parse("roster.csv", text.encode())


def test_finds_emails_regardless_of_column_name():
    r = extract_roster(_csv("Person,Contact Address\nAlice,a@x.com\nBob,b@x.com\n"))
    assert r.emails == ["a@x.com", "b@x.com"]
    assert r.total_rows == 2


def test_dedupes_and_lowercases_emails():
    r = extract_roster(_csv("Email\nA@X.com\na@x.com\nB@Y.com\n"))
    assert r.emails == ["a@x.com", "b@y.com"]


def test_detects_status_column_and_breakdown():
    r = extract_roster(
        _csv("Email,Registered\na@x.com,Yes\nb@x.com,No\nc@x.com,No\n")
    )
    assert r.status_column == "Registered"
    assert r.status_breakdown == {"yes": 1, "no": 2}
    # per-row status carried through for filtering
    assert {row["email"]: row["status"] for row in r.rows} == {
        "a@x.com": "Yes", "b@x.com": "No", "c@x.com": "No"
    }


def test_detects_status_column_by_values_when_header_is_plain():
    r = extract_roster(_csv("Email,Flag\na@x.com,registered\nb@x.com,pending\n"))
    assert r.status_column == "Flag"


def test_no_status_column_when_file_only_has_emails():
    r = extract_roster(_csv("Email\na@x.com\nb@x.com\n"))
    assert r.status_column is None
    assert r.status_breakdown == {}


def test_registrant_name_header_not_mistaken_for_status():
    # "Registrant Name" must be a name column, not a status column.
    r = extract_roster(_csv("Registrant Name,Email\nAlice,a@x.com\n"))
    assert r.status_column is None
    assert r.name_column == "Registrant Name"
    assert r.rows[0]["name"] == "Alice"


def test_empty_when_no_emails_present():
    r = extract_roster(_csv("Name,Dept\nAlice,Eng\n"))
    assert r.emails == []


def test_to_dict_round_trips_fields():
    r = RosterReading(emails=["a@x.com"], rows=[{"email": "a@x.com"}], headers=["Email"],
                      total_rows=1, status_column=None, status_breakdown={}, name_column=None)
    d = r.to_dict()
    assert d["emails"] == ["a@x.com"] and d["rows"] == [{"email": "a@x.com"}]
