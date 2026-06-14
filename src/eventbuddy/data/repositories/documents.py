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

    def list(self, event_id: str) -> list[Document]:
        """All catalogued documents for an event (Impl 5 — enriches the file browse list)."""
        return list(self.s.scalars(
            select(Document).where(Document.event_id == event_id)
            .order_by(Document.ingested_at.desc())
        ))

    def upsert(self, event_id: str, *, filename: str, drive_item_id: str | None = None,
               mime_type: str | None = None, parse_status: str = "parsed",
               summary: str | None = None,
               doc_type: str | None = None) -> tuple[Document, bool]:
        """Return (document, created). `created=False` means this drive item was already
        ingested — the caller can skip re-structuring/re-proposing. `summary`/`doc_type` are
        the generic catalog fields (Impl 5)."""
        existing = self.get_by_drive_item(drive_item_id) if drive_item_id else None
        if existing is not None:
            existing.parse_status = parse_status
            return existing, False
        doc = Document(event_id=event_id, filename=filename, drive_item_id=drive_item_id,
                       mime_type=mime_type, parse_status=parse_status,
                       summary=summary, doc_type=doc_type)
        self.s.add(doc)
        return doc, True

    def set_parse_status(self, doc_id: str, status: str) -> None:
        doc = self.s.get(Document, doc_id)
        if doc is not None:
            doc.parse_status = status

    def set_understanding(self, drive_item_id: str, *, summary: str | None,
                          doc_type: str | None) -> None:
        """Lazily backfill the catalog summary/type for an already-known file (Impl 5 —
        read_event_file fills it on first read when ingestion didn't)."""
        doc = self.get_by_drive_item(drive_item_id)
        if doc is not None:
            if summary is not None:
                doc.summary = summary
            if doc_type is not None:
                doc.doc_type = doc_type
