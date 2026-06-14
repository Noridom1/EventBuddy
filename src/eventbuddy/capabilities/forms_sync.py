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
        """Ingest new rows from the responses workbook at `workbook_url`. Returns the count
        newly stored. Resolves the SharePoint share link to a drive item, then delegates."""
        if not workbook_url:
            return 0
        try:
            drive_id, item_id = self.graph.resolve_share_url(workbook_url)
        except Exception as e:  # noqa: BLE001
            log.warning(f"forms workbook link resolve failed ({type(e).__name__}: {e})")
            return 0
        return self.sync_drive_item(event_id=event_id, drive_id=drive_id, item_id=item_id)

    def sync_drive_item(self, *, event_id: str, drive_id: str, item_id: str) -> int:
        """Ingest new rows from a workbook already resolved to (drive_id, item_id) — used by
        the share-link path and by channel auto-discovery (Option 2)."""
        try:
            content, filename, _mime = self.graph.get_drive_item_content(drive_id, item_id)
            parse = self._parse or _default_parse
            rows = parse(filename, content).rows or []
        except Exception as e:  # noqa: BLE001 — fetch/parse failure degrades to "no new rows"
            log.warning(f"forms workbook read failed ({type(e).__name__}: {e})")
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


# Filenames Microsoft Forms gives a responses workbook usually contain one of these.
_WORKBOOK_NAME_HINTS = ("response", "responses", "feedback", "form", "survey")


def discover_workbook(graph, team_id: str, channel_id: str) -> tuple[str, str] | None:
    """Option 2 (best-effort): when no per-event / global workbook link is set, scan the
    event channel's SharePoint folder for an `.xlsx` whose name looks like a Forms responses
    workbook. Conservative — returns the first plausible match or None (never raises). Note:
    Forms often stores response workbooks in a site `Apps/Microsoft Forms` area rather than
    the channel folder, so a per-event link (Option 1) remains the reliable path."""
    try:
        drive_id, folder_id = graph.get_channel_files_folder(team_id, channel_id)
        for child in graph.list_children(drive_id, folder_id):
            if child.get("folder") is not None:
                continue
            name = str(child.get("name", "")).lower()
            if name.endswith(".xlsx") and any(h in name for h in _WORKBOOK_NAME_HINTS):
                return drive_id, child["id"]
    except Exception as e:  # noqa: BLE001
        log.warning(f"workbook auto-discovery failed ({type(e).__name__}: {e})")
    return None
