"""defence and villagers: monster waves, realm bosses, boss damage, villagers (Phases 13/14)

Revision ID: 0009
Revises: 0008
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monster_waves",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("realm_id", sa.Uuid(), sa.ForeignKey("realms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("town_hall", sa.SmallInteger(), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_monster_waves_user", "monster_waves", ["user_id", "created_at"])
    op.create_index(
        "ix_monster_waves_live",
        "monster_waves",
        ["status"],
        postgresql_where=sa.text("status IN ('announced', 'running')"),
    )
    op.create_table(
        "realm_bosses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("realm_id", sa.Uuid(), sa.ForeignKey("realms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("boss_key", sa.Text(), nullable=False),
        sa.Column("lair_x", sa.REAL(), nullable=False),
        sa.Column("lair_y", sa.REAL(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("spawns_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hp_fraction", sa.REAL(), nullable=False, server_default="1"),
        sa.Column("defeated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_realm_bosses_realm", "realm_bosses", ["realm_id", "spawns_at"])
    op.create_table(
        "boss_damage",
        sa.Column(
            "boss_id", sa.Uuid(), sa.ForeignKey("realm_bosses.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("damage", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("looted", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("villages", sa.Column("villagers_at", sa.DateTime(timezone=True)))
    op.add_column("villages", sa.Column("unhappy_since", sa.DateTime(timezone=True)))
    op.create_table(
        "villagers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("village_id", sa.Uuid(), sa.ForeignKey("villages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("appearance", postgresql.JSONB(), nullable=False),
        sa.Column("traits", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "job_building_id", sa.Uuid(), sa.ForeignKey("village_buildings.id", ondelete="SET NULL")
        ),
        sa.Column(
            "home_building_id", sa.Uuid(), sa.ForeignKey("village_buildings.id", ondelete="SET NULL")
        ),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_villagers_village_id", "villagers", ["village_id"])


def downgrade() -> None:
    op.drop_index("ix_villagers_village_id", table_name="villagers")
    op.drop_table("villagers")
    op.drop_column("villages", "unhappy_since")
    op.drop_column("villages", "villagers_at")
    op.drop_table("boss_damage")
    op.drop_index("ix_realm_bosses_realm", table_name="realm_bosses")
    op.drop_table("realm_bosses")
    op.drop_index("ix_monster_waves_live", table_name="monster_waves")
    op.drop_index("ix_monster_waves_user", table_name="monster_waves")
    op.drop_table("monster_waves")
