"""economy: NPC market, merchant purchases, idempotency keys, economy samples (Phase 7)

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A new enum value can be added inside a transaction as long as nothing uses it in the same one.
    op.execute("ALTER TYPE discovery_kind ADD VALUE IF NOT EXISTS 'hint'")
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_idempotency_keys_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_idempotency_keys")),
    )
    op.create_index("ix_idempotency_keys_created", "idempotency_keys", ["created_at"])
    op.create_table(
        "market_prices",
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(12, 3), nullable=False),
        sa.Column("units_sold_24h", sa.BigInteger(), nullable=False),
        sa.Column("baseline_used", sa.Numeric(14, 3), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_key"], ["item_defs.key"], name=op.f("fk_market_prices_item_key_item_defs")
        ),
        sa.PrimaryKeyConstraint("item_key", name=op.f("pk_market_prices")),
    )
    op.create_table(
        "market_price_history",
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(12, 3), nullable=False),
        sa.Column("units_24h", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_key"], ["item_defs.key"], name=op.f("fk_market_price_history_item_key_item_defs")
        ),
        sa.PrimaryKeyConstraint("item_key", "at", name=op.f("pk_market_price_history")),
    )
    op.create_table(
        "market_sales_buckets",
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_key"], ["item_defs.key"], name=op.f("fk_market_sales_buckets_item_key_item_defs")
        ),
        sa.PrimaryKeyConstraint("item_key", "bucket_start", name=op.f("pk_market_sales_buckets")),
    )
    op.create_table(
        "market_player_daily",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_market_player_daily_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "item_key", "day", name=op.f("pk_market_player_daily")),
    )
    op.create_table(
        "merchant_purchases",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Text(), nullable=False),
        sa.Column("rotation", sa.Integer(), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_merchant_purchases_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "merchant_id", "rotation", "slot", name=op.f("pk_merchant_purchases")
        ),
    )
    op.create_table(
        "economy_samples",
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coin_supply", sa.BigInteger(), nullable=False),
        sa.Column("players", sa.Integer(), nullable=False),
        sa.Column("active_24h", sa.Integer(), nullable=False),
        sa.Column("faucet", sa.BigInteger(), nullable=False),
        sa.Column("sink", sa.BigInteger(), nullable=False),
        sa.Column("last_tx_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("at", name=op.f("pk_economy_samples")),
    )
    # the economy view sums coin flow by reason over time windows
    op.create_index(
        "ix_transactions_coin_created",
        "transactions",
        ["created_at"],
        postgresql_where=sa.text("asset = 'coin'"),
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_coin_created", table_name="transactions")
    op.drop_table("economy_samples")
    op.drop_table("merchant_purchases")
    op.drop_table("market_player_daily")
    op.drop_table("market_sales_buckets")
    op.drop_table("market_price_history")
    op.drop_table("market_prices")
    op.drop_index("ix_idempotency_keys_created", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    # Postgres can't drop an enum value; 'hint' stays (harmless).
