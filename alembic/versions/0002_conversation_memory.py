"""Phase 1.7 conversation memory — durable transcript + rolling summary.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("speaker_name", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_thread_created",
        "conversation_messages",
        ["thread_id", "created_at"],
    )
    op.create_table(
        "session_summaries",
        sa.Column("thread_id", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("covered_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("thread_id"),
    )


def downgrade() -> None:
    op.drop_table("session_summaries")
    op.drop_index("ix_conversation_thread_created", table_name="conversation_messages")
    op.drop_table("conversation_messages")
