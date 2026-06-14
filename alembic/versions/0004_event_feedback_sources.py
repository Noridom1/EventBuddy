"""Impl 2 — per-event feedback sources.

Adds `events.feedback_form_url` + `events.feedback_workbook_url` (both nullable): each event
has its own Form and its own responses Excel workbook (a different SharePoint site per
channel), so the workbook/form link must live per-event rather than as a single global env
var. Nullable so existing events and the global-setting fallback still work.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-14

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("feedback_form_url", sa.String(length=1000), nullable=True))
    op.add_column(
        "events", sa.Column("feedback_workbook_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "feedback_workbook_url")
    op.drop_column("events", "feedback_form_url")
