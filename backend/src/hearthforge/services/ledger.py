"""The only code allowed to change coins, items or stored resources (PLAN §2.2).

Every function here expects the caller to hold the relevant row locks inside an open transaction,
and writes an append-only `transactions` row with a reason code.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.core.errors import GameError
from hearthforge.db.models import LedgerAsset, Transaction, Wallet

# Reason codes (keep this list as the single source of truth).
STARTER_GRANT = "starter.grant"
BUILD_PLACE = "build.place"
BUILD_UPGRADE = "build.upgrade"
BUILD_CANCEL_REFUND = "build.cancel_refund"
BUILD_DEMOLISH_REFUND = "build.demolish_refund"
BUILD_UNDO_REFUND = "build.undo_refund"
BUILD_UNDO_REPAY = "build.undo_repay"
ADMIN_GRANT = "admin.grant"
DEBRIS_CLEAR = "debris.clear"
AVATAR_GATHER = "avatar.gather"
AVATAR_DEPOSIT = "avatar.deposit"
LOOT_DROP = "loot.drop"
LOOT_COINS = "loot.coins"
ITEM_CONSUME = "item.consume"
ITEM_MOVE = "item.move"
KO_LOSS = "ko.loss"
KO_RECOVER = "ko.recover"


async def lock_wallet(session: AsyncSession, user_id: uuid.UUID) -> Wallet:
    wallet = (
        await session.execute(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
    ).scalar_one()
    return wallet


async def change_coins(
    session: AsyncSession,
    wallet: Wallet,
    delta: int,
    reason: str,
    *,
    ref_type: str | None = None,
    ref_id: str | None = None,
    actor: str = "user",
) -> int:
    if delta == 0:
        return wallet.coins
    if wallet.coins + delta < 0:
        raise GameError("insufficient_coins", "Not enough coins.", need=-delta, have=wallet.coins)
    wallet.coins += delta
    session.add(
        Transaction(
            user_id=wallet.user_id,
            asset=LedgerAsset.coin,
            delta=delta,
            balance_after=wallet.coins,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            actor=actor,
        )
    )
    return wallet.coins


def log_resource(
    session: AsyncSession,
    user_id: uuid.UUID,
    realm_id: uuid.UUID | None,
    key: str,
    delta_milli: int,
    reason: str,
    *,
    ref_type: str | None = None,
    ref_id: str | None = None,
    actor: str = "user",
) -> None:
    if delta_milli == 0:
        return
    session.add(
        Transaction(
            user_id=user_id,
            realm_id=realm_id,
            asset=LedgerAsset.resource,
            item_key=key,
            delta=delta_milli,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            actor=actor,
        )
    )


def log_item(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    item_key: str,
    delta: int,
    reason: str,
    *,
    container_id: uuid.UUID | None = None,
    instance_id: uuid.UUID | None = None,
    actor: str = "user",
) -> None:
    session.add(
        Transaction(
            user_id=user_id,
            asset=LedgerAsset.item,
            item_key=item_key,
            delta=delta,
            reason=reason,
            container_id=container_id,
            instance_id=instance_id,
            actor=actor,
        )
    )
