"""vertical slice + realms: user_stats, away snapshot, realm activity, fog of war (Phases 8, 9)

Revision ID: 0006
Revises: 0005
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE discovery_kind ADD VALUE IF NOT EXISTS 'waystone'")
    # mapgen v3 only adds waystones and their clearings; pre-launch, existing realms move up in place
    op.execute("UPDATE realms SET mapgen_version = 3 WHERE mapgen_version = 2")
    op.add_column("users", sa.Column("away_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "user_stats",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("stat_key", sa.Text(), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_stats_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "stat_key", name=op.f("pk_user_stats")),
    )
    op.create_table(
        "realm_activity",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("realm_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["realm_id"], ["realms.id"], name=op.f("fk_realm_activity_realm_id_realms"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_realm_activity_actor_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_realm_activity")),
    )
    op.create_index("ix_realm_activity_realm_created", "realm_activity", ["realm_id", "created_at"])
    op.create_table(
        "fog_reveals",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("realm_id", sa.Uuid(), nullable=False),
        sa.Column("bits", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_fog_reveals_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["realm_id"], ["realms.id"], name=op.f("fk_fog_reveals_realm_id_realms"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "realm_id", name=op.f("pk_fog_reveals")),
    )


def downgrade() -> None:
    op.drop_table("fog_reveals")
    op.drop_index("ix_realm_activity_realm_created", table_name="realm_activity")
    op.drop_table("realm_activity")
    op.drop_table("user_stats")
    op.drop_column("users", "away_snapshot")
