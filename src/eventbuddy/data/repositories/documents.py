from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import Document


class DocumentRepository:
    """Ingested documents (architecture §6.3 `documents`). Keyed for idempotency by
    `drive_item_id` so a re-delivered webhook / re-run channel sync doesn't double-ingest."""

    def __init__(self, session: Session):
        self.s = session

    def get_by_drive_item(self, drive_item_id: str) -> Document | None:
        if not drive_item_id:
            return None
        return self.s.scalar(
            select(Document).where(Document.drive_item_id == drive_item_id))

    def upsert(self, event_id: str, *, filename: str, drive_item_id: str | None = None,
               mime_type: str | None = None, parse_status: str = "parsed") -> tuple[Document, bool]:
        """Return (document, created). `created=False` means this drive item was already
        ingested — the caller can skip re-structuring/re-proposing."""
        existing = self.get_by_drive_item(drive_item_id) if drive_item_id else None
        if existing is not None:
            existing.parse_status = parse_status
            return existing, False
        doc = Document(event_id=event_id, filename=filename, drive_item_id=drive_item_id,
                       mime_type=mime_type, parse_status=parse_status)
        self.s.add(doc)
        return doc, True

    def set_parse_status(self, doc_id: str, status: str) -> None:
        doc = self.s.get(Document, doc_id)
        if doc is not None:
            doc.parse_status = status
