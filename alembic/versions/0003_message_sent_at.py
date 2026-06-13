"""Phase 1.9 time-awareness — real send-time on transcript turns.

Adds `conversation_messages.sent_at` (nullable): the real message send-time, distinct from
`created_at` (synthetic flush-ordering). Nullable so existing rows and assistant turns
without a captured time degrade gracefully.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-13

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_messages", "sent_at")
