from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from eventbuddy.domain.models import ChatFile


class ChatFileRepository:
    """The per-chat file catalog (Impl 9). Idempotent by `(chat_id, drive_item_id)` once a file
    is resolved; before resolution a `reference` row dedupes by `(chat_id, share_url)` then
    `(chat_id, filename)`. Mirrors `DocumentRepository`'s shape, keyed on the conversation id."""

    def __init__(self, session: Session):
        self.s = session

    def list(self, chat_id: str) -> list[ChatFile]:
        if not chat_id:
            return []
        return list(self.s.scalars(
            select(ChatFile).where(ChatFile.chat_id == chat_id)
            .order_by(ChatFile.synced_at.desc())
        ))

    def known_item_ids(self, chat_id: str) -> set[str]:
        """Drive-item ids already cataloged for this chat — the idempotency skip-set for sync."""
        rows = self.s.scalars(
            select(ChatFile.drive_item_id).where(
                ChatFile.chat_id == chat_id, ChatFile.drive_item_id.is_not(None))
        )
        return {r for r in rows if r}

    def _find(self, chat_id: str, *, drive_item_id: str | None,
              share_url: str | None, filename: str | None) -> ChatFile | None:
        """Locate an existing row by the strongest key available: item id → url → filename."""
        if drive_item_id:
            row = self.s.scalar(select(ChatFile).where(
                ChatFile.chat_id == chat_id, ChatFile.drive_item_id == drive_item_id))
            if row is not None:
                return row
        if share_url:
            row = self.s.scalar(select(ChatFile).where(
                ChatFile.chat_id == chat_id, ChatFile.share_url == share_url))
            if row is not None:
                return row
        if filename:
            return self.s.scalar(select(ChatFile).where(
                ChatFile.chat_id == chat_id, ChatFile.filename == filename))
        return None

    def upsert(self, chat_id: str, *, filename: str, share_url: str | None = None,
               drive_item_id: str | None = None, summary: str | None = None,
               doc_type: str | None = None,
               parse_status: str | None = None) -> tuple[ChatFile, bool]:
        """Create or update a catalog row, filling only the non-null fields supplied. Returns
        `(row, created)`. Use with just `filename`/`share_url` to capture a reference on receive;
        call again with `drive_item_id`/`summary`/`doc_type` to backfill after a read."""
        existing = self._find(chat_id, drive_item_id=drive_item_id,
                              share_url=share_url, filename=filename)
        if existing is not None:
            if share_url and not existing.share_url:
                existing.share_url = share_url
            if drive_item_id and not existing.drive_item_id:
                existing.drive_item_id = drive_item_id
            if summary is not None:
                existing.summary = summary
            if doc_type is not None:
                existing.doc_type = doc_type
            if parse_status is not None:
                existing.parse_status = parse_status
            return existing, False
        row = ChatFile(
            chat_id=chat_id, filename=filename, share_url=share_url,
            drive_item_id=drive_item_id, summary=summary, doc_type=doc_type,
            parse_status=parse_status or "reference",
        )
        self.s.add(row)
        return row, True
