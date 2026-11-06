"""dungeons: cleared delve runs and the daily leaderboard (Phase 12)

Revision ID: 0008
Revises: 0007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dungeon_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("realm_id", sa.Uuid(), sa.ForeignKey("realms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("biome", sa.Text(), nullable=False),
        sa.Column("names", postgresql.JSONB(), nullable=False),
        sa.Column("user_ids", postgresql.JSONB(), nullable=False),
        sa.Column("clear_ms", sa.Integer(), nullable=False),
        sa.Column("deaths", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_dungeon_runs_board", "dungeon_runs", ["kind", "day", "clear_ms"])


def downgrade() -> None:
    op.drop_index("ix_dungeon_runs_board", table_name="dungeon_runs")
    op.drop_table("dungeon_runs")
