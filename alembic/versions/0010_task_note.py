"""Task creation plane — `tasks.note`.

Adds a free-form, agent-maintained note column to `tasks`, so the agent can attach context to
a task at creation (`create_task`) and append/replace it later (`update_task`) — e.g. a
rescheduled deadline, a blocker, or any context the organizer dictates. Nullable; existing rows
keep `note = NULL`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-16

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "note")
