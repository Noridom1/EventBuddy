"""Impl 18 — domain-identity member enrollment (`event_members.aad_object_id`).

Adds the stable AAD directory object id to `event_members`. This is the cross-context bridge
that lets a member enrolled from a group chat's Graph roster be recognized in their own 1-1 DM:
`from_property.aad_object_id` (on every activity) == the `userId` Graph returns for chat/channel
members, whereas the legacy `teams_user_id` is the per-conversation Bot Framework `29:…` id.

Nullable + indexed. Legacy rows keep `aad_object_id = NULL` and continue to match by
`teams_user_id` / `email`; the AAD id is backfilled onto a row the next time that member posts
or signs in (auto-enroll upsert).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-16

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_members",
        sa.Column("aad_object_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_event_members_aad_object_id", "event_members", ["aad_object_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_event_members_aad_object_id", table_name="event_members")
    op.drop_column("event_members", "aad_object_id")
