"""village debris (wild growth to clear, D-040)

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "villages",
        sa.Column("debris", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )
    # the starting plot grew from 24 to 32 tiles (D-040); existing dev villages follow
    op.execute("UPDATE villages SET size = 32 WHERE size < 32")


def downgrade() -> None:
    op.drop_column("villages", "debris")
