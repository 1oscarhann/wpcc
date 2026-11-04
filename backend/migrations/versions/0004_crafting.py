"""crafting: station jobs and discoveries (Phase 6)

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB = postgresql.ENUM("running", "collected", "cancelled", name="job_status", create_type=False)
DISC = postgresql.ENUM(
    "combo", "recipe", "poi", "lore", "biome", "monster", "fish", "rare_material",
    name="discovery_kind", create_type=False,
)


def upgrade() -> None:
    JOB.create(op.get_bind(), checkfirst=True)
    DISC.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "craft_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("station_building_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("recipe_key", sa.Text(), nullable=False),
        sa.Column("combo_key", sa.Text(), nullable=True),
        sa.Column("tier", sa.SmallInteger(), nullable=True),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rare_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("luck", sa.REAL(), nullable=False),
        sa.Column("legendary_eligible", sa.Boolean(), nullable=False),
        sa.Column("roll_seed", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", JOB, nullable=False),
        sa.Column("result_instance_id", sa.Uuid(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_craft_jobs_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["station_building_id"], ["village_buildings.id"],
            name=op.f("fk_craft_jobs_station_building_id_village_buildings"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["result_instance_id"], ["item_instances.id"], name=op.f("fk_craft_jobs_result_instance_id_item_instances")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_craft_jobs")),
    )
    op.create_index("ix_craft_jobs_user_status", "craft_jobs", ["user_id", "status"])
    op.create_table(
        "discoveries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", DISC, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_discoveries_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "kind", "key", name=op.f("pk_discoveries")),
    )


def downgrade() -> None:
    op.drop_table("discoveries")
    op.drop_index("ix_craft_jobs_user_status", table_name="craft_jobs")
    op.drop_table("craft_jobs")
    DISC.drop(op.get_bind(), checkfirst=True)
    JOB.drop(op.get_bind(), checkfirst=True)
