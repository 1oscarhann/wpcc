"""Admin CLI: `uv run hf --help`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from hearthforge.config.loader import ConfigError, load_config
from hearthforge.settings import get_settings

app = typer.Typer(no_args_is_help=True, help="Hearthforge admin tools")
config_app = typer.Typer(help="Config tools")
app.add_typer(config_app, name="config")


@config_app.command("check")
def config_check(
    path: Path = typer.Option(None, help="Config dir (default: HF_CONFIG_DIR or repo /config)"),
    strict: bool = typer.Option(True, help="Treat warnings as errors"),
) -> None:
    """Validate /config/*.yaml exactly like server startup does."""
    try:
        cfg = load_config(path or get_settings().config_dir, strict=strict)
    except ConfigError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    typer.secho(f"config OK  hash={cfg.hash}  {cfg.summary()}", fg=typer.colors.GREEN)


def run(coro) -> None:  # noqa: ANN001
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        sys.exit(130)


async def _with_db(fn):  # noqa: ANN001, ANN202
    from hearthforge.db.engine import make_engine, make_sessionmaker

    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=2)
    try:
        async with make_sessionmaker(engine)() as session, session.begin():
            return await fn(session)
    finally:
        await engine.dispose()


async def _user(session, username: str):  # noqa: ANN001, ANN202
    from sqlalchemy import select

    from hearthforge.db.models import User

    user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        typer.secho(f"no user '{username}'", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return user


@app.command("test-account")
def test_account(
    username: str, enable: bool = typer.Option(True, help="--no-enable to clear the flag")
) -> None:
    """Mark an account as a test account (allows fast-forward)."""

    async def go(session):  # noqa: ANN001, ANN202
        user = await _user(session, username)
        user.is_test_account = enable

    run(_with_db(go))
    typer.echo(f"{username}: is_test_account={enable}")


@app.command("fast-forward")
def fast_forward(
    username: str,
    duration: str = typer.Argument(..., help="e.g. 30m, 2h"),
    force: bool = typer.Option(False, help="Allow on non-test accounts"),
) -> None:
    """Move a player's timers and production forward in time (D-014)."""
    from hearthforge.config.schemas import parse_duration
    from hearthforge.db.models import AdminAuditLog
    from hearthforge.services.village import fast_forward as ff

    secs = parse_duration(duration)

    async def go(session):  # noqa: ANN001, ANN202
        user = await _user(session, username)
        if not user.is_test_account and not force:
            typer.secho(
                "not a test account (use `hf test-account NAME` or --force)", fg=typer.colors.RED, err=True
            )
            raise typer.Exit(1)
        await ff(session, user.id, secs)
        session.add(AdminAuditLog(action="fast_forward", target=str(user.id), payload={"seconds": secs}))

    run(_with_db(go))
    typer.echo(f"{username}: fast-forwarded {duration}; changes apply on the next read")


@app.command("grant")
def grant(
    username: str,
    coins: int = typer.Option(0),
    res: list[str] = typer.Option([], help="wood=100"),
    item: list[str] = typer.Option([], help="ironbark=2 (into the bag)"),
) -> None:
    """Give coins, village resources and/or bag items (logged in the ledger as admin.grant)."""
    from sqlalchemy import select

    from hearthforge.db.models import AdminAuditLog, Resource, Village
    from hearthforge.services import ledger

    async def go(session):  # noqa: ANN001, ANN202
        user = await _user(session, username)
        if coins:
            wallet = await ledger.lock_wallet(session, user.id)
            await ledger.change_coins(session, wallet, coins, ledger.ADMIN_GRANT, actor="admin")
        village = (await session.execute(select(Village).where(Village.user_id == user.id))).scalar_one()
        for entry in res:
            key, _, qty = entry.partition("=")
            row = (
                await session.execute(
                    select(Resource)
                    .where(Resource.village_id == village.id, Resource.resource_key == key)
                    .with_for_update()
                )
            ).scalar_one()
            row.amount_milli += int(qty) * 1000
            ledger.log_resource(
                session, user.id, village.realm_id, key, int(qty) * 1000, ledger.ADMIN_GRANT, actor="admin"
            )
        if item:
            from hearthforge.config.loader import load_config
            from hearthforge.services import inventory
            from hearthforge.settings import get_settings

            cfg = load_config(get_settings().config_dir)
            want = {k: int(q) for k, _, q in (i.partition("=") for i in item)}
            left = await inventory.grant(session, cfg, user.id, want, ledger.ADMIN_GRANT)
            if left:
                typer.echo(f"bag full, not granted: {left}")
        session.add(
            AdminAuditLog(
                action="grant", target=str(user.id), payload={"coins": coins, "res": res, "item": item}
            )
        )

    run(_with_db(go))
    typer.echo(f"granted to {username}")


@app.command("make-admin")
def make_admin(username: str, enable: bool = typer.Option(True, help="--no-enable to demote")) -> None:
    """Give (or take away) the admin role: unlocks /api/admin/* (the economy view)."""
    from hearthforge.db.models import AdminAuditLog, UserRole

    async def go(session):  # noqa: ANN001, ANN202
        user = await _user(session, username)
        user.role = UserRole.admin if enable else UserRole.player
        session.add(AdminAuditLog(action="make_admin", target=str(user.id), payload={"enable": enable}))

    run(_with_db(go))
    typer.echo(f"{username}: role={'admin' if enable else 'player'}")


market_app = typer.Typer(help="NPC market tools")
app.add_typer(market_app, name="market")


@market_app.command("recalc")
def market_recalc() -> None:
    """Reprice the market now (the worker does this every recalc_interval anyway)."""
    from hearthforge.clock import Clock
    from hearthforge.services import market

    cfg = load_config(get_settings().config_dir)

    async def go(session):  # noqa: ANN001, ANN202
        return await market.recalc(session, cfg, Clock().now())

    prices = asyncio.run(_with_db(go))
    for k, p in prices.items():
        typer.echo(f"{k:>12}  {p:8.3f}")


@market_app.command("seed")
def market_seed(
    hours: int = typer.Option(24, help="How much fake history to write"),
    seed: int = typer.Option(7),
    yes: bool = typer.Option(False, "--yes", help="Required: this writes made-up sales"),
) -> None:
    """DEV/DEMO ONLY: simulate a busy realm's sales for the last N hours and recalc at every step,
    so sparklines and trends have something to show. Never run this on a real server."""
    import math
    import random
    from datetime import timedelta

    from sqlalchemy.dialects.postgresql import insert

    from hearthforge.clock import Clock
    from hearthforge.db.models import MarketSalesBucket
    from hearthforge.domain import market as dom
    from hearthforge.services import market

    if not yes or get_settings().env == "prod":
        typer.secho("refusing: pass --yes, and never on prod", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    cfg = load_config(get_settings().config_dir)
    m = cfg.market
    rng = random.Random(seed)

    async def go(session):  # noqa: ANN001, ANN202
        now = Clock().now()
        step = m.recalc_interval
        n = int(hours * 3600 // step)
        start = dom.bucket_start(now, step) - timedelta(seconds=n * step)
        phase = {k: rng.random() * 6.28 for k in m.items}
        mood = {k: rng.choice([0.6, 0.9, 1.0, 1.2, 1.6]) for k in m.items}
        for i in range(n + 1):
            t = start + timedelta(seconds=i * step)
            for k, it in m.items.items():
                per_bucket = it.baseline * m.defaults.min_population * step / m.window
                wave = 1 + 0.6 * math.sin(phase[k] + i / 9)
                units = max(0, int(per_bucket * mood[k] * wave * rng.uniform(0.5, 1.5)))
                stmt = insert(MarketSalesBucket).values(item_key=k, bucket_start=t, units=units)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[MarketSalesBucket.item_key, MarketSalesBucket.bucket_start],
                        set_={"units": stmt.excluded.units},
                    )
                )
            await market.recalc(session, cfg, t)
        await market.recalc(session, cfg, now)
        return n

    n = asyncio.run(_with_db(go))
    typer.echo(f"seeded {n} buckets of demo sales and recalculated")


@app.command("economy")
def economy_cmd() -> None:
    """Coin supply and faucets vs sinks by reason (the same data as GET /api/admin/economy)."""
    from hearthforge.clock import Clock
    from hearthforge.services import economy

    rep = asyncio.run(_with_db(lambda s: economy.report(s, Clock().now())))
    supply, wallets, mean = rep["coin_supply"], rep["wallets"], rep["mean_coins"]
    typer.echo(f"coin supply {supply:,} across {wallets} wallets (mean {mean:,})")
    for label in ("day", "week"):
        f = rep[label]
        typer.echo(f"\n{label}: net {f['net']:+,}")
        for kind in ("faucets", "sinks"):
            for reason, v in sorted(f[kind].items(), key=lambda kv: -kv[1]):
                typer.echo(f"  {kind[:-1]:>6}  {reason:<24} {v:>12,}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
