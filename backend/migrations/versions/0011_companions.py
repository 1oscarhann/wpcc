"""companions: pets and mounts you own, and which ones are out (Phase 16b)

Revision ID: 0011
Revises: 0010
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

U = "users.id"


def upgrade() -> None:
    op.create_table(
        "pets",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("pet_key", sa.Text(), primary_key=True),
        sa.Column("nickname", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "mounts",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("mount_key", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("avatars", sa.Column("pet", sa.Text()))
    op.add_column("avatars", sa.Column("mount", sa.Text()))


def downgrade() -> None:
    op.drop_column("avatars", "mount")
    op.drop_column("avatars", "pet")
    op.drop_table("mounts")
    op.drop_table("pets")
