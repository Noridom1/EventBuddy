"""Document ingestion pipeline (architecture §5.5, §7.2).

download → parse → LLM-structure → upsert `documents` + extracted members/tasks → propose a
proactive HITL bulk-invite (a `mail` pending action + a confirm card posted to the channel via
Graph). Idempotent by `drive_item_id`. Everything degrades: no parser → unsupported; no LLM →
no structure; no pending-store/post-card → upsert only, propose nothing. Never raises into the
webhook/agent path — failures are logged and returned as a `skipped` reason."""
from __future__ import annotations

from dataclasses import dataclass

from eventbuddy.bot.cards.builders import confirm_card
from eventbuddy.common.logging import get_logger
from eventbuddy.ingestion.parsers import parse as _parse

log = get_logger("ingestion.pipeline")


@dataclass
class IngestResult:
    documents: int = 0
    members_added: int = 0
    tasks_added: int = 0
    invited_proposed: int = 0
    skipped: str | None = None


class IngestionPipeline:
    def __init__(self, graph, extractor, *, pending_store=None, post_card=None, parse=None):
        self.graph = graph
        self.extractor = extractor
        self.pending_store = pending_store
        self.post_card = post_card        # (channel_id, card_dict) -> None
        self._parse = parse or _parse

    def ingest(self, *, drive_id: str, item_id: str, event_id: str) -> IngestResult:
        from eventbuddy.data.db import session_scope
        from eventbuddy.data.repositories.documents import DocumentRepository
        from eventbuddy.data.repositories.events import EventRepository
        from eventbuddy.data.repositories.members import MemberRepository
        from eventbuddy.data.repositories.tasks import TaskRepository

        # Skip a drive item we've already ingested (idempotent re-delivery / re-sync).
        try:
            with session_scope() as s:
                if DocumentRepository(s).get_by_drive_item(item_id) is not None:
                    return IngestResult(skipped="already_ingested")
        except Exception as e:  # noqa: BLE001
            log.warning(f"ingest dedup check failed ({type(e).__name__}: {e})")

        try:
            content, filename, mime = self.graph.get_drive_item_content(drive_id, item_id)
        except Exception as e:  # noqa: BLE001
            log.warning(f"drive item fetch failed ({type(e).__name__}: {e})")
            return IngestResult(skipped="download_failed")

        parsed = self._parse(filename, content)
        try:
            structured = self.extractor.structure(parsed)
        except Exception as e:  # noqa: BLE001
            log.warning(f"structuring failed for {filename} ({type(e).__name__}: {e})")
            structured = {"members": [], "tasks": []}

        status = "parsed" if parsed.kind != "unsupported" else "failed"
        result = IngestResult()
        invite_payload = None
        channel_id = None
        try:
            with session_scope() as s:
                doc_repo = DocumentRepository(s)
                _doc, created = doc_repo.upsert(
                    event_id, filename=filename, drive_item_id=item_id,
                    mime_type=mime, parse_status=status,
                )
                if not created:
                    return IngestResult(skipped="already_ingested")
                result.documents = 1

                ev = EventRepository(s).get(event_id)
                channel_id = ev.teams_channel_id if ev else None
                event_name = ev.event_name if ev else "the event"
                host_user_id = ev.host_user_id if ev else None
                reg_link = ev.registration_link if ev else None

                m_repo = MemberRepository(s)
                existing_emails = {m.email.lower() for m in m_repo.list(event_id) if m.email}
                new_members = [
                    {"email": m["email"], "display_name": m.get("display_name"),
                     "role": m.get("role", "member")}
                    for m in structured["members"]
                    if m["email"].lower() not in existing_emails
                ]
                if new_members:
                    m_repo.add_many(event_id, new_members)
                    result.members_added = len(new_members)

                t_repo = TaskRepository(s)
                existing_tasks = {t.task_name.lower() for t in t_repo.list(event_id)}
                for t in structured["tasks"]:
                    if t["task_name"].lower() in existing_tasks:
                        continue
                    t_repo.create(
                        event_id, t["task_name"], assignee_email=t.get("assignee_email"),
                        source_document=filename,
                    )
                    existing_tasks.add(t["task_name"].lower())
                    result.tasks_added += 1
                s.flush()

                # Proactive opportunity: members still pending registration → propose invites.
                pending = [m.email for m in m_repo.pending(event_id) if m.email]
                if pending and self.pending_store is not None and self.post_card is not None:
                    invite_payload = {
                        "type": "mail", "event_id": event_id, "event_name": event_name,
                        "channel_id": channel_id, "requested_by": host_user_id,
                        "subject": f"[Invitation] {event_name}",
                        "body_html": (f"<p>You're invited to <b>{event_name}</b>.</p>"
                                      + (f"<p>Register: {reg_link}</p>" if reg_link else "")),
                        "recipient_emails": pending,
                    }
        except Exception as e:  # noqa: BLE001
            log.warning(f"ingest upsert failed for {filename} ({type(e).__name__}: {e})")
            return IngestResult(skipped="upsert_failed")

        # Post the proactive confirm card to the channel (outside the DB session).
        if invite_payload is not None and channel_id:
            try:
                pending_id = self.pending_store.put(invite_payload)
                n = len(invite_payload["recipient_emails"])
                card = confirm_card(
                    title=f"{n} member(s) not yet invited — send invites?",
                    summary=f"Send the invitation email for '{invite_payload['event_name']}'.",
                    pending_id=pending_id, action="mail",
                )
                self.post_card(channel_id, card)
                result.invited_proposed = n
            except Exception as e:  # noqa: BLE001
                log.warning(f"invite proposal not posted ({type(e).__name__}: {e})")
        return result
