"""social and progression: friends, blocks, mail, gifts, likes, visits, helps, quests, achievements,
cosmetics, the login calendar, avatar skills and titles (Phases 15/16)

Revision ID: 0010
Revises: 0009
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

U = "users.id"


def _now() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "friendships",
        sa.Column("user_low", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("user_high", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        _now(),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("user_low < user_high", name="ordered_pair"),
    )
    op.create_index("ix_friendships_high", "friendships", ["user_high"])
    op.create_table(
        "blocks",
        sa.Column("blocker_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("blocked_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        _now(),
    )
    op.create_table(
        "mail",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.Uuid(), sa.ForeignKey(U, ondelete="SET NULL")),
        sa.Column("sender_name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("coins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        _now(),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mail_user", "mail", ["user_id", "created_at"])
    op.create_table(
        "gifts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("from_user", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), nullable=False),
        sa.Column("to_user", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("contents", postgresql.JSONB(), nullable=False),
        _now(),
    )
    op.create_index("ix_gifts_from_day", "gifts", ["from_user", "day"])
    op.create_table(
        "village_likes",
        sa.Column("liker_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("counted", sa.Boolean(), nullable=False),
        _now(),
    )
    op.create_table(
        "village_visits",
        sa.Column("visitor_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Text(), primary_key=True),
    )
    op.create_table(
        "neighbour_helps",
        sa.Column("helper_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "building_id", sa.Uuid(), sa.ForeignKey("village_buildings.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("day", sa.Text(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), nullable=False),
        sa.Column("seconds_saved", sa.Integer(), nullable=False),
        _now(),
    )
    op.create_index("ix_neighbour_helps_building_day", "neighbour_helps", ["building_id", "day"])
    op.create_table(
        "quest_progress",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("quest_key", sa.Text(), primary_key=True),
        sa.Column("period_start", sa.Text(), primary_key=True),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("stat", sa.Text(), nullable=False),
        sa.Column("base", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "user_achievements",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("achievement_key", sa.Text(), primary_key=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "user_cosmetics",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("cosmetic_key", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "login_rewards",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey(U, ondelete="CASCADE"), primary_key=True),
        sa.Column("calendar_day", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("last_claim_day", sa.Text()),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("avatars", sa.Column("skills", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("avatars", sa.Column("respecs", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("avatars", sa.Column("title", sa.Text()))


def downgrade() -> None:
    op.drop_column("avatars", "title")
    op.drop_column("avatars", "respecs")
    op.drop_column("avatars", "skills")
    for t in ("login_rewards", "user_cosmetics", "user_achievements", "quest_progress"):
        op.drop_table(t)
    op.drop_index("ix_neighbour_helps_building_day", table_name="neighbour_helps")
    op.drop_table("neighbour_helps")
    op.drop_table("village_visits")
    op.drop_table("village_likes")
    op.drop_index("ix_gifts_from_day", table_name="gifts")
    op.drop_table("gifts")
    op.drop_index("ix_mail_user", table_name="mail")
    op.drop_table("mail")
    op.drop_table("blocks")
    op.drop_index("ix_friendships_high", table_name="friendships")
    op.drop_table("friendships")
