from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eventbuddy.common.ids import new_id
from eventbuddy.data.db import Base


class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_name: Mapped[str] = mapped_column(String(255))
    teams_channel_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    # The real Teams team/group id this channel lives under (Impl 3). Distinct from the
    # tenant id — Graph channel calls need `/teams/{team_id}/channels/{channel_id}`. Captured
    # from `activity.channel_data.team.id` and backfilled on first channel message; nullable
    # so events created before it's known still work (channel reads degrade until populated).
    teams_team_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ideation")
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registration_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Per-event feedback sources (Impl 2). Each event has its own Form + responses workbook
    # (different SharePoint site per channel), so these override the global settings defaults.
    feedback_form_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    feedback_workbook_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    host_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    members: Mapped[list["EventMember"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )


class EventMember(Base):
    __tablename__ = "event_members"
    __table_args__ = (UniqueConstraint("event_id", "teams_user_id"),)
    mapping_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    teams_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Nullable since group-chat onboarding (setup_event / auto-enroll): a member enrolled from a
    # Teams post is keyed by `teams_user_id` + display name — we don't have their email until a
    # roster file / Graph lookup backfills it. Reminder/mail recipient builders skip empty emails.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    registration_status: Mapped[str] = mapped_column(String(20), default="pending")
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event: Mapped["Event"] = relationship(back_populates="members")


class Task(Base):
    __tablename__ = "tasks"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    task_name: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assignee_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="todo")
    source_document: Mapped[str | None] = mapped_column(String(500), nullable=True)
    event: Mapped["Event"] = relationship(back_populates="tasks")


class Document(Base):
    __tablename__ = "documents"
    doc_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(500))
    drive_item_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending")
    # Generic file catalog (Impl 5): a short "what is this file / what's it for" summary and a
    # coarse type classification, so the agent can browse files (list_event_files) and decide
    # which to read. Filled at ingestion (text → chat LLM; image → vision model) or lazily on
    # first read. Nullable — a file not yet understood lists by name/mime only.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatFile(Base):
    """Per-chat file catalog (Impl 9) — the intelligence-plane analogue of `documents`, but for
    files shared in a **group chat or 1-1 DM** rather than a Team channel's SharePoint folder.
    Keyed on the conversation's `chat_id` (the inbound Bot Framework `conversation.id`: a
    `19:…@thread.v2` group id or an `a:…` DM id — both are fine string keys), with **no FK to
    events** because a chat usually has no bound event. A row is created the moment a file is
    shared (a cheap `reference` upsert — `share_url` + `filename`, no download), then `summary`/
    `doc_type`/`drive_item_id` are filled lazily on first list/read. This is what lets the agent
    resolve a file by name/description on a later turn — the share link is otherwise delivered
    only on the activity that bore the file and is lost by the next turn."""

    __tablename__ = "chat_files"
    file_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(500))
    # The OneDrive/SharePoint sharing URL the file was shared by (a chat attachment's
    # `contentUrl`). Resolved to a stable `drive_item_id` lazily on first read for idempotency.
    share_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    drive_item_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # "reference" (captured, not yet read) | "parsed" | "failed".
    parse_status: Mapped[str] = mapped_column(String(20), default="reference")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_chat_files_chat_id", "chat_id"),
        # NULL drive_item_ids are distinct in Postgres, so reference rows (pre-resolution)
        # dedupe in the repository by share_url/filename instead.
        UniqueConstraint("chat_id", "drive_item_id", name="uq_chat_files_chat_item"),
    )


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(40))
    target: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="queued")


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"
    response_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    respondent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    themes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Report(Base):
    __tablename__ = "reports"
    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    metrics_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestions_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConversationMessage(Base):
    """Durable transcript layer (Phase 1.7). User/assistant turns only — tool calls/results
    are never persisted here. Overflow target when the Redis working window evicts turns,
    and the rehydration source when the window is empty. `thread_id` is the scope-aware
    session key (`event:{channel_id}` | `dm:{user_id}`)."""

    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_conversation_thread_created", "thread_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(String(200))
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    speaker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    # Write/ordering field — synthetic per-flush time (strictly increasing within a flush).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Real send-time (Phase 1.9): from `activity.timestamp` for user turns, generation-time
    # for assistant turns. Distinct from `created_at` (which is flush-ordering, not send-time).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionSummary(Base):
    """Rolling long-term summary (Phase 1.7) — a compact running gist of everything older
    than the rehydration tail, so a long event keeps early context inside the 4096 budget.
    `covered_through` is the watermark (last covered message's created_at)."""

    __tablename__ = "session_summaries"
    thread_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    covered_through: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("events.event_id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
