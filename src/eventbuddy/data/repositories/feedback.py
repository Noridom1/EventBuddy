from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import FeedbackResponse


class FeedbackRepository:
    """Feedback-response intake + read (architecture §6.3 `feedback_responses`). Raw Forms
    answers land here (via the Excel-workbook sync or the webhook fallback) with the LLM
    sentiment/theme analysis attached."""

    def __init__(self, session: Session):
        self.s = session

    def add(self, event_id: str, *, respondent_id: str | None, raw_payload: dict,
            sentiment: str | None = None, themes: dict | None = None) -> FeedbackResponse:
        fr = FeedbackResponse(event_id=event_id, respondent_id=respondent_id,
                              raw_payload=raw_payload, sentiment=sentiment, themes=themes)
        self.s.add(fr)
        return fr

    def list(self, event_id: str) -> list[FeedbackResponse]:
        return list(self.s.scalars(
            select(FeedbackResponse).where(FeedbackResponse.event_id == event_id)))

    def set_analysis(self, response_id: str, sentiment: str, themes: dict) -> None:
        fr = self.s.get(FeedbackResponse, response_id)
        if fr is not None:
            fr.sentiment, fr.themes = sentiment, themes

    def respondent_ids(self, event_id: str) -> set[str]:
        """Stable per-response keys already stored — the workbook sync dedups against these
        so re-syncing an unchanged Form doesn't create duplicate rows."""
        return {r.respondent_id for r in self.list(event_id) if r.respondent_id}

    def respondent_emails(self, event_id: str) -> set[str]:
        """Lower-cased emails of everyone who responded (from the response email column or an
        email-shaped respondent_id). `feedback_followup` mails only members NOT in this set."""
        emails: set[str] = set()
        for r in self.list(event_id):
            rp = r.raw_payload or {}
            email = rp.get("email") or rp.get("respondent_email")
            if email:
                emails.add(str(email).strip().lower())
            elif r.respondent_id and "@" in r.respondent_id:
                emails.add(r.respondent_id.strip().lower())
        return emails
