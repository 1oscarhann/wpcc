"""The admin economy view (PLAN risk 5): coin supply over time, and coins in vs out by reason code."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.db.models import EconomySample, LedgerAsset, Transaction, Wallet


async def flows(session: AsyncSession, hours: int) -> dict[str, dict[str, int]]:
    """Coins created (faucets) and destroyed (sinks) by reason over the last `hours` (database time)."""
    rows = await session.execute(
        select(
            Transaction.reason,
            func.coalesce(func.sum(Transaction.delta).filter(Transaction.delta > 0), 0),
            func.coalesce(-func.sum(Transaction.delta).filter(Transaction.delta < 0), 0),
        )
        .where(
            Transaction.asset == LedgerAsset.coin,
            Transaction.created_at >= func.now() - text(f"interval '{int(hours)} hours'"),
        )
        .group_by(Transaction.reason)
    )
    faucets: dict[str, int] = {}
    sinks: dict[str, int] = {}
    for reason, inflow, outflow in rows.all():
        if inflow:
            faucets[reason] = int(inflow)
        if outflow:
            sinks[reason] = int(outflow)
    return {"faucets": faucets, "sinks": sinks}


async def report(session: AsyncSession, now: datetime) -> dict[str, Any]:
    supply, wallets = (
        await session.execute(
            select(func.coalesce(func.sum(Wallet.coins), 0), func.count()).select_from(Wallet)
        )
    ).one()
    samples = list(
        (
            await session.execute(
                select(EconomySample)
                .where(EconomySample.at >= now - timedelta(days=7))
                .order_by(EconomySample.at)
            )
        ).scalars()
    )
    out: dict[str, Any] = {
        "coin_supply": int(supply),
        "wallets": int(wallets),
        "mean_coins": round(int(supply) / wallets, 1) if wallets else 0,
        "series": [
            {
                "at_ms": int(s.at.timestamp() * 1000),
                "supply": s.coin_supply,
                "faucet": s.faucet,
                "sink": s.sink,
                "active": s.active_24h,
            }
            for s in samples
        ],
    }
    for label, hours in (("day", 24), ("week", 168)):
        f = await flows(session, hours)
        f["net"] = sum(f["faucets"].values()) - sum(f["sinks"].values())  # type: ignore[assignment]
        out[label] = f
    return out
