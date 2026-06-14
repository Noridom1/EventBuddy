"""Fetch MS Forms feedback from the Form's **responses Excel workbook** (the chosen path).

There is NO supported Microsoft Graph API to read Forms responses directly — the
`formapi.office.com` endpoints are internal and unstable. Group/Teams Forms instead sync
their responses to an `.xlsx` workbook in the site ("Open in Excel"); the organizer shares
that workbook's link once (`FEEDBACK_WORKBOOK_URL`). We resolve the share link → driveItem,
download + parse the workbook rows (reusing the ingestion `.xlsx` parser), map columns to a
`FeedbackResponse`, analyze sentiment/themes, and store — idempotently (re-sync skips rows
already stored). Everything degrades: no link / no creds / unreadable → 0 ingested, no raise.
"""
from eventbuddy.common.logging import get_logger

log = get_logger("capabilities.forms_sync")

# Header-substring heuristics — Forms response columns are locale/title-dependent, so match
# loosely and fall back gracefully (architecture risk note: workbook column drift).
_RATING_HINTS = ("rating", "score", "satisfaction", "rate")
_COMMENT_HINTS = ("comment", "feedback", "suggestion", "thought", "improve")
_EMAIL_HINTS = ("email", "address")
_ID_HINTS = ("id", "completion time", "start time", "submitted")


def _pick(row: dict, hints: tuple[str, ...]) -> str | None:
    for key, val in row.items():
        kl = str(key).strip().lower()
        if any(h in kl for h in hints):
            if val not in (None, ""):
                return val
    return None


def _to_rating(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def _row_key(row: dict) -> str:
    """A stable per-response key for dedup: prefer email, else a submission id/timestamp,
    else the row's stringified values."""
    return str(
        _pick(row, _EMAIL_HINTS) or _pick(row, _ID_HINTS) or sorted(row.items())
    ).strip().lower()


class FormsResponseSync:
    def __init__(self, graph, feedback_repo, analyzer, *, parse=None):
        self.graph = graph
        self.feedback = feedback_repo
        self.analyzer = analyzer
        self._parse = parse  # injectable; defaults to the ingestion .xlsx parser

    def sync(self, *, event_id: str, workbook_url: str | None) -> int:
        """Ingest any new rows from the responses workbook. Returns the count newly stored."""
        if not workbook_url:
            return 0
        try:
            drive_id, item_id = self.graph.resolve_share_url(workbook_url)
            content, filename, _mime = self.graph.get_drive_item_content(drive_id, item_id)
            parse = self._parse or _default_parse
            rows = parse(filename, content).rows or []
        except Exception as e:  # noqa: BLE001 — fetch/parse failure degrades to "no new rows"
            log.warning(f"forms workbook sync failed ({type(e).__name__}: {e})")
            return 0

        existing = self.feedback.respondent_ids(event_id)
        added = 0
        for row in rows:
            key = _row_key(row)
            if not key or key in existing:
                continue
            comment = _pick(row, _COMMENT_HINTS) or ""
            rating = _to_rating(_pick(row, _RATING_HINTS))
            email = _pick(row, _EMAIL_HINTS)
            sentiment, themes = self.analyzer.analyze(str(comment))
            self.feedback.add(
                event_id, respondent_id=email or key,
                raw_payload={"rating": rating, "comment": str(comment),
                             "email": str(email) if email else None},
                sentiment=sentiment, themes={"tags": themes},
            )
            existing.add(key)
            added += 1
        if added:
            log.info(f"forms sync ingested {added} new response(s) for event={event_id}")
        return added


def _default_parse(filename: str, content: bytes):
    from eventbuddy.ingestion.parsers import parse
    return parse(filename, content)
