"""world expansion: realms move to mapgen v4 (all six biome rings) (Phase 10)

Revision ID: 0007
Revises: 0006
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # v4 only changes terrain past the forest's inner edge; villages and the inner world are untouched,
    # so pre-launch realms move up in place (D-070)
    op.execute("UPDATE realms SET mapgen_version = 4 WHERE mapgen_version = 3")


def downgrade() -> None:
    op.execute("UPDATE realms SET mapgen_version = 3 WHERE mapgen_version = 4")
