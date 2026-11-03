"""FastAPI app factory. `uvicorn hearthforge.main:app` for production; `create_app()` in tests."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hearthforge.clock import Clock
from hearthforge.config.loader import GameConfig, load_config
from hearthforge.core.errors import GameError, game_error_handler
from hearthforge.core.security import Passwords
from hearthforge.db.engine import make_engine, make_sessionmaker
from hearthforge.services.config_sync import sync_config
from hearthforge.settings import Settings, get_settings
from hearthforge.state import AppState

log = logging.getLogger("hearthforge")

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(
    settings: Settings | None = None, config: GameConfig | None = None, clock: Clock | None = None
) -> FastAPI:
    settings = settings or get_settings()
    config = config or load_config(settings.config_dir, strict=settings.config_strict)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url, settings.db_pool_size)
        sm = make_sessionmaker(engine)
        from hearthforge.realtime.hubs import VillageHub
        from hearthforge.realtime.pg_listener import PgListener

        st = AppState(
            settings=settings,
            config=config,
            engine=engine,
            sessionmaker=sm,
            clock=clock or Clock(),
            passwords=Passwords(settings.argon2_profile),
        )
        st.village_hub = VillageHub(st)
        app.state.hf = st
        async with sm() as session, session.begin():
            await sync_config(session, config)
        log.info("config %s loaded (%s)", config.hash, config.summary())

        tasks: list[asyncio.Task[None]] = []
        if settings.enable_listener:
            tasks.append(asyncio.create_task(PgListener(st).run(), name="pg-listener"))
            tasks.append(asyncio.create_task(st.village_hub.fallback_poll(), name="village-poll"))
        if settings.run_worker_in_process:
            from hearthforge.worker.poller import Worker

            tasks.append(asyncio.create_task(Worker(st).run_forever(), name="worker"))
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            await engine.dispose()

    app = FastAPI(
        title="Hearthforge", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.add_exception_handler(GameError, game_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type", "x-csrf-token", "idempotency-key"],
    )

    @app.middleware("http")
    async def origin_check(request: Request, call_next):  # noqa: ANN001, ANN202
        # Browsers send Origin on unsafe requests; reject anything not from our frontend.
        origin = request.headers.get("origin")
        if request.method in UNSAFE and origin and origin not in settings.frontend_origins:
            host_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin != host_origin:
                return JSONResponse(
                    status_code=403, content={"error": {"code": "bad_origin", "message": "Bad origin."}}
                )
        return await call_next(request)

    from hearthforge.api import auth, me, realm, village
    from hearthforge.realtime import gateway

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(village.router)
    app.include_router(realm.router)
    app.include_router(gateway.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "config": config.hash}

    return app


def _make_default() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()


def __getattr__(name: str) -> FastAPI:
    # Lazy so importing this module in tests doesn't load config from the environment.
    if name == "app":
        return _make_default()
    raise AttributeError(name)
