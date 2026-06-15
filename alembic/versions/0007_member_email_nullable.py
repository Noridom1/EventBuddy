"""Group-chat onboarding — make event_members.email nullable.

A member enrolled from a Teams group post (setup_event / auto-enroll) is keyed by
`teams_user_id` + display name; we don't have their email until a roster file / Graph lookup
backfills it. Reminder/mail recipient builders already skip empty emails, so this is safe.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-15

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "event_members", "email",
        existing_type=sa.String(length=255), nullable=True,
    )


def downgrade() -> None:
    # Backfill any NULLs before re-imposing NOT NULL, so the downgrade can't fail on data
    # created under the nullable schema.
    op.execute("UPDATE event_members SET email = '' WHERE email IS NULL")
    op.alter_column(
        "event_members", "email",
        existing_type=sa.String(length=255), nullable=False,
    )
