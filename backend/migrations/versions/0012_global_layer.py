"""the global layer: the player market (listings in escrow, trades) and world boss weekends (Phase 17)

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

U = "users.id"


def _ts(name: str, nullable: bool = False, now: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=nullable, server_default=sa.func.now() if now else None
    )


def upgrade() -> None:
    op.create_table(
        "pmarket_listings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("seller_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), nullable=False),
        sa.Column("seller_name", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),  # still for sale (in escrow)
        sa.Column("listed", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        _ts("created_at", now=True),
        _ts("expires_at"),
        _ts("closed_at", nullable=True),
        sa.CheckConstraint("quantity >= 0 AND quantity <= listed", name="qty_in_range"),
        sa.CheckConstraint("unit_price >= 1", name="price_positive"),
    )
    op.create_index(
        "ix_pmarket_active_item",
        "pmarket_listings",
        ["item_key", "unit_price"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_pmarket_seller", "pmarket_listings", ["seller_id", "status"])
    op.create_index(
        "ix_pmarket_expiry", "pmarket_listings", ["expires_at"], postgresql_where=sa.text("status = 'active'")
    )
    op.create_table(
        "pmarket_trades",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "listing_id", sa.Uuid(), sa.ForeignKey("pmarket_listings.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("fee", sa.Integer(), nullable=False),
        _ts("created_at", now=True),
    )
    op.create_index("ix_pmarket_trades_item", "pmarket_trades", ["item_key", sa.text("created_at DESC")])
    op.create_table(
        "world_boss_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("boss_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _ts("starts_at"),
        _ts("ends_at"),
        sa.Column("hp_max", sa.BigInteger(), nullable=False),
        sa.Column("hp_remaining", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="active"
        ),  # active | defeated | expired
        _ts("finished_at", nullable=True),
        sa.Column("rewarded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("hp_remaining >= 0", name="hp_non_negative"),
    )
    op.create_index("ix_world_boss_window", "world_boss_events", ["starts_at"], unique=True)
    op.create_table(
        "world_boss_damage",
        sa.Column(
            "event_id", sa.Uuid(), sa.ForeignKey("world_boss_events.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("realm_id", sa.Uuid(), nullable=False),
        sa.Column("damage", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_index("ix_world_boss_damage_realm", "world_boss_damage", ["event_id", "realm_id"])


def downgrade() -> None:
    op.drop_table("world_boss_damage")
    op.drop_table("world_boss_events")
    op.drop_table("pmarket_trades")
    op.drop_table("pmarket_listings")
