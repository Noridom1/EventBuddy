"""Initial schema – all eight EventBuddy tables.

Revision ID: 0001
Revises: None
Create Date: 2026-06-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # events  (no FK dependencies – created first)
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("teams_channel_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("registration_link", sa.String(length=500), nullable=True),
        sa.Column("host_user_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("teams_channel_id"),
    )

    # ------------------------------------------------------------------
    # event_members  (FK → events.event_id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        "event_members",
        sa.Column("mapping_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("teams_user_id", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("registration_status", sa.String(length=20), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint("event_id", "teams_user_id"),
    )

    # ------------------------------------------------------------------
    # tasks  (FK → events.event_id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("assignee_id", sa.String(length=100), nullable=True),
        sa.Column("assignee_email", sa.String(length=255), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_document", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )

    # ------------------------------------------------------------------
    # documents  (FK → events.event_id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("drive_item_id", sa.String(length=200), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("parse_status", sa.String(length=20), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("doc_id"),
    )

    # ------------------------------------------------------------------
    # scheduled_jobs  (FK → events.event_id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        "scheduled_jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )

    # ------------------------------------------------------------------
    # feedback_responses  (FK → events.event_id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        "feedback_responses",
        sa.Column("response_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("respondent_id", sa.String(length=100), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column("themes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("response_id"),
    )

    # ------------------------------------------------------------------
    # reports  (FK → events.event_id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column("suggestions_md", sa.Text(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id"),
    )

    # ------------------------------------------------------------------
    # audit_log  (FK → events.event_id SET NULL – event_id is nullable)
    # ------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("log_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.event_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("log_id"),
    )


def downgrade() -> None:
    # Drop in reverse FK-dependency order (most-dependent first)
    op.drop_table("audit_log")
    op.drop_table("reports")
    op.drop_table("feedback_responses")
    op.drop_table("scheduled_jobs")
    op.drop_table("documents")
    op.drop_table("tasks")
    op.drop_table("event_members")
    op.drop_table("events")
