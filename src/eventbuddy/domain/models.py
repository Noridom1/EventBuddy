from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eventbuddy.common.ids import new_id
from eventbuddy.data.db import Base


class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_name: Mapped[str] = mapped_column(String(255))
    teams_channel_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ideation")
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registration_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    email: Mapped[str] = mapped_column(String(255))
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
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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
