"""Impl 9 — per-chat file catalog (`chat_files`).

Adds the `chat_files` table: the intelligence-plane catalog for files shared in a group chat
or 1-1 DM (the analogue of `documents`, which is event/channel-scoped). Keyed on the
conversation's `chat_id` with no FK to events (a chat usually has no bound event). A row is
created when a file is shared (`reference` status, `share_url` + `filename`, no download) and
its `drive_item_id`/`summary`/`doc_type` are backfilled lazily on first read — so the agent can
resolve a file by name/description on a later turn even though the share link rides only the
activity that bore the file.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-16

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_files",
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("share_url", sa.String(length=1000), nullable=True),
        sa.Column("drive_item_id", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("doc_type", sa.String(length=40), nullable=True),
        sa.Column("parse_status", sa.String(length=20), nullable=False,
                  server_default="reference"),
        sa.Column("synced_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("file_id"),
        sa.UniqueConstraint("chat_id", "drive_item_id", name="uq_chat_files_chat_item"),
    )
    op.create_index("ix_chat_files_chat_id", "chat_files", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_files_chat_id", table_name="chat_files")
    op.drop_table("chat_files")
