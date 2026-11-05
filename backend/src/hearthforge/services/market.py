"""The NPC market (BALANCE §8.1): worker price recalc, the market view, and selling.

Lock order for a sale (PLAN §2.2): wallet → village (+ resources, running jobs) → containers →
the player's daily row → the shared sales bucket (last, so the hot row is held for the shortest time).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError
from hearthforge.db.models import (
    EconomySample,
    LedgerAsset,
    MarketPlayerDaily,
    MarketPrice,
    MarketPriceHistory,
    MarketSalesBucket,
    Transaction,
    User,
    Wallet,
)
from hearthforge.domain import market as dom
from hearthforge.domain.resources import MILLI
from hearthforge.services import events, idempotency, inventory, ledger
from hearthforge.services import village as village_svc

RECALC = "market.recalc"


def to_ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


# ── recalc (worker) ──────────────────────────────────────────────────────────


async def active_players(session: AsyncSession, cfg: GameConfig, now: datetime) -> int:
    since = now - timedelta(seconds=cfg.market.active_window)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.last_seen_at >= since, User.banned_at.is_(None))
            )
        ).scalar_one()
    )


async def units_24h(session: AsyncSession, cfg: GameConfig, now: datetime) -> dict[str, int]:
    """Rolling window = the current bucket plus the ones before it, `window` long in total."""
    at = dom.bucket_start(now, cfg.market.recalc_interval)
    since = at - timedelta(seconds=cfg.market.window - cfg.market.recalc_interval)
    rows = await session.execute(
        select(MarketSalesBucket.item_key, func.sum(MarketSalesBucket.units))
        .where(MarketSalesBucket.bucket_start >= since, MarketSalesBucket.bucket_start <= at)
        .group_by(MarketSalesBucket.item_key)
    )
    return {k: int(v) for k, v in rows.all()}


async def recalc(session: AsyncSession, cfg: GameConfig, now: datetime) -> dict[str, float]:
    """Reprice every item from the last 24 h of sales. Idempotent per bucket (upserts keyed by time)."""
    m = cfg.market
    at = dom.bucket_start(now, m.recalc_interval)
    active = await active_players(session, cfg, now)
    sold = await units_24h(session, cfg, now)
    out: dict[str, float] = {}
    for key in m.items:
        p, bl = dom.price(m, key, sold.get(key, 0), active)
        out[key] = p
        stmt = insert(MarketPrice).values(
            item_key=key, price=p, units_sold_24h=sold.get(key, 0), baseline_used=bl, updated_at=now
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[MarketPrice.item_key],
                set_={
                    "price": stmt.excluded.price,
                    "units_sold_24h": stmt.excluded.units_sold_24h,
                    "baseline_used": stmt.excluded.baseline_used,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )
        hist = insert(MarketPriceHistory).values(item_key=key, at=at, price=p, units_24h=sold.get(key, 0))
        await session.execute(
            hist.on_conflict_do_update(
                index_elements=[MarketPriceHistory.item_key, MarketPriceHistory.at],
                set_={"price": hist.excluded.price, "units_24h": hist.excluded.units_24h},
            )
        )
    await sample_economy(session, at, active)
    await prune(session, cfg, now)
    return out


async def sample_economy(session: AsyncSession, at: datetime, active: int) -> EconomySample:
    """Coin supply now, plus coins created/destroyed since the previous sample (counted by ledger id)."""
    prev = (
        await session.execute(
            select(EconomySample).where(EconomySample.at < at).order_by(EconomySample.at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    after = prev.last_tx_id if prev else 0
    supply, players = (
        await session.execute(
            select(func.coalesce(func.sum(Wallet.coins), 0), func.count()).select_from(Wallet)
        )
    ).one()
    faucet, sink, last = (
        await session.execute(
            select(
                func.coalesce(func.sum(Transaction.delta).filter(Transaction.delta > 0), 0),
                func.coalesce(-func.sum(Transaction.delta).filter(Transaction.delta < 0), 0),
                func.coalesce(func.max(Transaction.id), after),
            ).where(Transaction.asset == LedgerAsset.coin, Transaction.id > after)
        )
    ).one()
    stmt = insert(EconomySample).values(
        at=at,
        coin_supply=int(supply),
        players=int(players),
        active_24h=active,
        faucet=int(faucet),
        sink=int(sink),
        last_tx_id=int(last),
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[EconomySample.at],
            set_={
                "coin_supply": stmt.excluded.coin_supply,
                "players": stmt.excluded.players,
                "active_24h": stmt.excluded.active_24h,
                # a re-run of the same bucket adds any newer flow on top of what it counted before
                "faucet": EconomySample.faucet + stmt.excluded.faucet,
                "sink": EconomySample.sink + stmt.excluded.sink,
                "last_tx_id": stmt.excluded.last_tx_id,
            },
        )
    )
    return (await session.execute(select(EconomySample).where(EconomySample.at == at))).scalar_one()


async def prune(session: AsyncSession, cfg: GameConfig, now: datetime) -> None:
    from sqlalchemy import delete

    m = cfg.market
    await session.execute(
        delete(MarketSalesBucket).where(
            MarketSalesBucket.bucket_start < now - timedelta(seconds=m.window + m.recalc_interval)
        )
    )
    await session.execute(
        delete(MarketPriceHistory).where(MarketPriceHistory.at < now - timedelta(seconds=m.history_retention))
    )
    await session.execute(
        delete(MarketPlayerDaily).where(MarketPlayerDaily.day < now.date() - timedelta(days=2))
    )
    await idempotency.prune(session, now)


def next_recalc_at(cfg: GameConfig, now: datetime) -> datetime:
    return dom.bucket_start(now, cfg.market.recalc_interval) + timedelta(seconds=cfg.market.recalc_interval)


async def schedule_next(session: AsyncSession, cfg: GameConfig, now: datetime) -> None:
    due = next_recalc_at(cfg, now)
    await events.schedule(session, RECALC, due, {}, f"{RECALC}:{int(due.timestamp())}")


async def ensure_started(session: AsyncSession, cfg: GameConfig, now: datetime) -> None:
    """At boot: price everything once if the table is empty, and make sure a recalc is scheduled."""
    have = (await session.execute(select(func.count()).select_from(MarketPrice))).scalar_one()
    if not have:
        await recalc(session, cfg, now)
    await schedule_next(session, cfg, now)


# ── view ─────────────────────────────────────────────────────────────────────


def market_level(cfg: GameConfig, ld: village_svc.Loaded) -> tuple[int, float]:
    """(Market level, sell bonus). Level 0 = no Market built yet (an upgrading one still trades)."""
    levels = [b.level for b in ld.buildings if b.building_key == "market" and b.level >= 1]
    if not levels:
        return 0, 0.0
    lv = max(levels)
    bonus = cfg.buildings_cfg.buildings["market"].sell_bonus or [0.0] * 5
    return lv, float(bonus[lv - 1])


async def _prices(session: AsyncSession, cfg: GameConfig, now: datetime) -> dict[str, MarketPrice]:
    rows = {r.item_key: r for r in (await session.execute(select(MarketPrice))).scalars()}
    missing = [k for k in cfg.market.items if k not in rows]
    if missing:  # before the first recalc (fresh database): price as if nothing has sold
        active = await active_players(session, cfg, now)
        for k in missing:
            p, bl = dom.price(cfg.market, k, 0, active)
            rows[k] = MarketPrice(item_key=k, price=p, units_sold_24h=0, baseline_used=bl, updated_at=now)
    return rows


async def _sold_today(session: AsyncSession, user_id: uuid.UUID, day: date) -> dict[str, int]:
    rows = await session.execute(
        select(MarketPlayerDaily.item_key, MarketPlayerDaily.units).where(
            MarketPlayerDaily.user_id == user_id, MarketPlayerDaily.day == day
        )
    )
    return {k: int(v) for k, v in rows.all()}


def _bag_counts(bs: dict[str, inventory.Bag]) -> dict[str, int]:
    have: dict[str, int] = {}
    for b in bs.values():
        for s in b.slots.values():
            if s.instance_id is None:
                have[s.item_key] = have.get(s.item_key, 0) + s.quantity
    return have


async def view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    m = cfg.market
    async with session.begin():
        ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
        village_svc.settle_village(session, cfg, ld, now)
        level, bonus = market_level(cfg, ld)
        bag = _bag_counts(await inventory.bags(session, user_id, ("inventory", "bank"), lock=False))
        prices = await _prices(session, cfg, now)
        look = max(m.sparkline.span, m.trend.lookback) + m.recalc_interval
        hist: dict[str, list[tuple[datetime, float]]] = {k: [] for k in m.items}
        for row in (
            await session.execute(
                select(MarketPriceHistory)
                .where(MarketPriceHistory.at >= now - timedelta(seconds=look))
                .order_by(MarketPriceHistory.at)
            )
        ).scalars():
            if row.item_key in hist:
                hist[row.item_key].append((row.at, float(row.price)))
        today = await _sold_today(session, user_id, now.date())
        population = await active_players(session, cfg, now)
        coins = ld.wallet.coins if ld.wallet else 0
    items = []
    for key, it in m.items.items():
        info = cfg.items[key]
        is_res = key in ld.resources
        have = int(ld.resources[key].amount_milli // MILLI) if is_res else bag.get(key, 0)
        raw = float(prices[key].price)
        direction, change = dom.trend(hist[key], raw, now, m.trend.lookback, m.trend.threshold)
        items.append(
            {
                "key": key,
                "name": info.name,
                "icon": info.icon,
                "source": "storage" if is_res else "bag",
                "have": have,
                "base": it.base,
                "raw_price": raw,
                "price": round(raw * (1 + bonus), 3),
                "over_price": round(raw * (1 + bonus) * m.over_cap_mult(key), 3),
                "trend": direction,
                "change": round(change, 4),
                "spark": dom.sparkline(hist[key], raw, now, m.sparkline.span, m.sparkline.points),
                "units_24h": int(prices[key].units_sold_24h),
                "baseline": float(prices[key].baseline_used),
                "sold_today": today.get(key, 0),
                "soft_cap": it.soft_cap,
            }
        )
    return {
        "has_market": level > 0,
        "market_level": level,
        "bonus": bonus,
        "coins": coins,
        "population": max(population, m.defaults.min_population),
        "active_players": population,
        "next_recalc_ms": to_ms(next_recalc_at(cfg, now)),
        "max_sell": m.max_sell,
        "items": items,
    }


# ── sell ─────────────────────────────────────────────────────────────────────


async def sell(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, now: datetime, key: str, qty: int
) -> tuple[village_svc.Loaded, dict[str, Any], bool]:
    """Sell `qty` of `key`. Returns (village, result, whether the bag changed)."""
    m = cfg.market
    it = m.items.get(key)
    if it is None:
        raise GameError("not_sellable", "The market doesn't buy that.")
    if not 1 <= qty <= m.max_sell:
        raise GameError("bad_quantity", f"You can sell 1 to {m.max_sell} at a time.")
    ld = await village_svc.load_locked(session, user_id=user_id, with_wallet=True)
    village_svc.settle_village(session, cfg, ld, now)
    assert ld.wallet is not None
    level, bonus = market_level(cfg, ld)
    if level == 0:
        raise GameError("needs_market", "Build a Market to sell your goods.")

    prices = await _prices(session, cfg, now)
    unit = float(prices[key].price)
    day = now.date()
    await session.execute(
        insert(MarketPlayerDaily)
        .values(user_id=user_id, item_key=key, day=day, units=0)
        .on_conflict_do_nothing(index_elements=["user_id", "item_key", "day"])
    )
    pay = None
    bag_changed = False
    # take the goods
    if key in ld.resources:
        r = ld.resources[key]
        have = r.amount_milli // MILLI
        if have < qty:
            raise GameError("insufficient_resources", f"You only have {have}.", missing={key: qty - have})
        r.amount_milli -= qty * MILLI
        ledger.log_resource(
            session,
            user_id,
            ld.village.realm_id,
            key,
            -qty * MILLI,
            ledger.MARKET_SELL,
            ref_type="market",
            ref_id=key,
        )
    else:
        bs = await inventory.bags(session, user_id, ("inventory", "bank"))
        have = _bag_counts(bs).get(key, 0)
        if have < qty:
            raise GameError("insufficient_items", f"You only have {have}.", missing={key: qty - have})
        left = qty
        for kind in ("inventory", "bank"):  # empty the bag first, it's the one with limited room
            if left <= 0 or kind not in bs:
                continue
            n = await inventory.take_stack(session, bs[kind], key, left)
            if n:
                ledger.log_item(session, user_id, key, -n, ledger.MARKET_SELL, container_id=bs[kind].c.id)
                left -= n
                bag_changed = bag_changed or kind == "inventory"
    daily = (
        await session.execute(
            select(MarketPlayerDaily)
            .where(
                MarketPlayerDaily.user_id == user_id,
                MarketPlayerDaily.item_key == key,
                MarketPlayerDaily.day == day,
            )
            .with_for_update()
        )
    ).scalar_one()
    pay = dom.payout(unit, bonus, qty, int(daily.units), it.soft_cap, m.over_cap_mult(key))
    if pay.coins < 1:
        raise GameError("too_cheap", "That's worth less than a coin. Sell a few more at once.")
    daily.units += qty
    await ledger.change_coins(
        session, ld.wallet, pay.coins, ledger.MARKET_SELL, ref_type="market", ref_id=key
    )
    from hearthforge.services import stats

    await stats.bump(session, user_id, {f"sell.{key}": qty, "sell.any": qty, "sell.coins": pay.coins})
    bucket = dom.bucket_start(now, m.recalc_interval)
    stmt = insert(MarketSalesBucket).values(item_key=key, bucket_start=bucket, units=qty)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[MarketSalesBucket.item_key, MarketSalesBucket.bucket_start],
            set_={"units": MarketSalesBucket.units + stmt.excluded.units},
        )
    )
    village_svc.touch(ld, now)
    await session.flush()
    result = {
        "item": key,
        "sold": qty,
        "coins": pay.coins,
        "unit_price": round(unit * (1 + bonus), 3),
        "over_cap_units": pay.over_units,
        "sold_today": int(daily.units),
        "soft_cap": it.soft_cap,
        "balance": ld.wallet.coins,
    }
    return ld, result, bag_changed
