"""Participant-roster reading (Impl 4).

Turns a parsed file (`ParsedDoc`) into a list of **participant** email addresses plus light,
*advisory* metadata: a name column if one is obvious, and the file's own registration-status
column if it carries one. This is the organizer's data — it is **never** EventBuddy state and
the addresses are **never** EventMembers (members are organizers; participants are attendees;
they're different things — see __plans__/11). Email extraction scans every cell so it works
regardless of how the file is laid out ("any format").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from eventbuddy.ingestion.parsers import ParsedDoc

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# A header that names the file's own status column. Full tokens (not bare "regist") so a
# "Registrant Name" column isn't mistaken for a status column.
_STATUS_HEADER_RE = re.compile(
    r"(registration|registered|status|rsvp|attendance|attending|confirmed|declined)", re.I
)
# Values that read as a registration status, used to detect a status column by its contents
# when the header doesn't give it away.
_STATUS_VALUES = {
    "registered", "yes", "no", "pending", "confirmed", "declined", "attending",
    "not attending", "true", "false", "y", "n", "invited", "accepted",
}
_NAME_HEADER_RE = re.compile(r"name", re.I)


@dataclass
class RosterReading:
    """The result of reading a participant file. `emails` is the deduped (lowercased) address
    list; `rows` is per-participant `{email, name?, status?}` for single-email rows. `status_*`
    reflect the **file's own** status column (advisory) — not any EventBuddy registration."""

    emails: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    total_rows: int = 0
    status_column: str | None = None
    status_breakdown: dict[str, int] = field(default_factory=dict)
    name_column: str | None = None

    def to_dict(self) -> dict:
        """JSON-serializable form for the transient RosterStore."""
        return {
            "emails": self.emails, "rows": self.rows, "headers": self.headers,
            "total_rows": self.total_rows, "status_column": self.status_column,
            "status_breakdown": self.status_breakdown, "name_column": self.name_column,
        }


def _find_emails(value) -> list[str]:
    if value is None:
        return []
    return EMAIL_RE.findall(str(value))


def _detect_status_column(headers: list[str], rows: list[dict]) -> str | None:
    for h in headers:
        if h and _STATUS_HEADER_RE.search(str(h)):
            return h
    # Value-based fallback: a column whose non-empty values are mostly status words.
    for h in headers:
        vals = [str(r.get(h)).strip().lower() for r in rows if str(r.get(h, "")).strip()]
        if not vals:
            continue
        hits = sum(1 for v in vals if v in _STATUS_VALUES)
        if hits and hits / len(vals) >= 0.6:
            return h
    return None


def _detect_name_column(headers: list[str]) -> str | None:
    for h in headers:
        if h and _NAME_HEADER_RE.search(str(h)):
            return h
    return None


def extract_roster(parsed: ParsedDoc) -> RosterReading:
    """Extract participant emails (+ advisory name/status) from a parsed file."""
    rows = parsed.rows or []
    headers = list(rows[0].keys()) if rows else []
    status_col = _detect_status_column(headers, rows)
    name_col = _detect_name_column(headers)

    seen: set[str] = set()
    emails: list[str] = []
    per_row: list[dict] = []
    breakdown: dict[str, int] = {}

    for r in rows:
        row_email = None
        for v in r.values():
            for e in _find_emails(v):
                el = e.lower()
                if el not in seen:
                    seen.add(el)
                    emails.append(el)
                if row_email is None:
                    row_email = el
        if not row_email:
            continue
        entry: dict = {"email": row_email}
        if name_col and str(r.get(name_col, "")).strip():
            entry["name"] = str(r[name_col]).strip()
        if status_col and str(r.get(status_col, "")).strip():
            sval = str(r[status_col]).strip()
            entry["status"] = sval
            breakdown[sval.lower()] = breakdown.get(sval.lower(), 0) + 1
        per_row.append(entry)

    # Non-tabular kinds (docx/pdf, or a single-column blob) — scan the flat text too.
    if not rows and parsed.text:
        for e in _find_emails(parsed.text):
            el = e.lower()
            if el not in seen:
                seen.add(el)
                emails.append(el)
                per_row.append({"email": el})

    return RosterReading(
        emails=emails, rows=per_row, headers=headers,
        total_rows=len(rows) if rows else len(emails),
        status_column=status_col, status_breakdown=breakdown, name_column=name_col,
    )
