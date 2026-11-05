"""`uv run python -m hearthforge.worker` — the separate timer worker process."""

from __future__ import annotations

import asyncio
import logging

from hearthforge.clock import Clock
from hearthforge.config.loader import load_config
from hearthforge.core.security import Passwords
from hearthforge.db.engine import make_engine, make_sessionmaker
from hearthforge.settings import get_settings
from hearthforge.state import AppState
from hearthforge.worker.poller import Worker


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    config = load_config(settings.config_dir, strict=settings.config_strict)
    engine = make_engine(settings.database_url, pool_size=3)
    st = AppState(
        settings=settings,
        config=config,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        clock=Clock(),
        passwords=Passwords(settings.argon2_profile),
    )
    from hearthforge.services import market

    async with st.sessionmaker() as session, session.begin():
        await market.ensure_started(session, config, st.clock.now())  # first prices + the recalc chain
    try:
        await Worker(st).run_forever()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
