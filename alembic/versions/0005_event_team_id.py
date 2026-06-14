"""Impl 3 — real Teams team id per event.

Adds `events.teams_team_id` (nullable): the Teams team/group id the event's channel lives
under. Graph channel calls (`/teams/{team_id}/channels/{channel_id}/...`) need this — it is
distinct from the tenant id the code previously (incorrectly) passed. Captured from
`activity.channel_data.team.id` and backfilled on the first channel message; nullable so
existing events keep working until the id is observed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-14

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("teams_team_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "teams_team_id")
