"""avatar mode: per-player node depletion, KO death drops, mapgen v2 (forest)

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "node_harvests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("realm_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("respawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_node_harvests_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["realm_id"], ["realms.id"], name=op.f("fk_node_harvests_realm_id_realms"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "realm_id", "node_id", name=op.f("pk_node_harvests")),
    )
    op.create_index("ix_node_harvests_respawn_at", "node_harvests", ["respawn_at"])
    op.create_table(
        "death_drops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("realm_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("x", sa.REAL(), nullable=False),
        sa.Column("y", sa.REAL(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovered_by", sa.Uuid(), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["realm_id"], ["realms.id"], name=op.f("fk_death_drops_realm_id_realms"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_death_drops_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recovered_by"], ["users.id"], name=op.f("fk_death_drops_recovered_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_death_drops")),
    )
    op.create_index(
        "ix_death_drops_realm_open", "death_drops", ["realm_id"], postgresql_where=sa.text("recovered_at IS NULL")
    )
    # Pre-launch only (D-045): existing dev realms move to the current generator instead of keeping v1.
    op.execute("UPDATE realms SET mapgen_version = 2 WHERE mapgen_version < 2")


def downgrade() -> None:
    op.drop_index("ix_death_drops_realm_open", table_name="death_drops")
    op.drop_table("death_drops")
    op.drop_index("ix_node_harvests_respawn_at", table_name="node_harvests")
    op.drop_table("node_harvests")
