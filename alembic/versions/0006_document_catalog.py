"""Impl 5 — generic file catalog on documents.

Adds `documents.summary` (Text) and `documents.doc_type` (String(40)), both nullable. These
hold a short "what is this file / what's it for" summary and a coarse type classification so
the agent can browse channel files (list_event_files) and decide which to read on demand
(read_event_file). Filled at ingestion or lazily on first read; nullable so files ingested
before this migration list by name/mime only.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-14

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("doc_type", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "doc_type")
    op.drop_column("documents", "summary")
