"""Test harness: a throwaway Postgres database per run, migrated with Alembic, truncated per test.

Point TEST_DATABASE_ADMIN_URL at any Postgres you can CREATE DATABASE on
(default: the local dev cluster on port 5433, see README).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from hearthforge.clock import FrozenClock
from hearthforge.config.loader import GameConfig, load_config
from hearthforge.main import create_app
from hearthforge.settings import REPO_ROOT, Settings, asyncpg_dsn

ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://hf@127.0.0.1:5433/postgres")
BACKEND = Path(__file__).resolve().parents[1]
KEEP_TABLES = {"alembic_version", "item_defs", "config_versions"}


@pytest.fixture(scope="session")
def game_config() -> GameConfig:
    return load_config(REPO_ROOT / "config", strict=True)


@pytest.fixture(scope="session")
async def database_url() -> AsyncIterator[str]:
    name = f"hf_test_{secrets.token_hex(4)}"
    dsn, kw = asyncpg_dsn(ADMIN_URL)
    admin = await asyncpg.connect(dsn, **kw)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    base = ADMIN_URL.rsplit("/", 1)[0]
    url = f"{base}/{name}".replace("postgresql://", "postgresql+asyncpg://", 1)

    cfg = AlembicConfig(str(BACKEND / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield url
    admin = await asyncpg.connect(dsn, **kw)
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.close()


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(
        **{
            "DATABASE_URL": database_url,
            "HF_ARGON2_PROFILE": "fast",
            "COOKIE_SECURE": True,
            "FRONTEND_ORIGINS": "https://testserver",
            "HF_ENABLE_LISTENER": False,
            "HF_CONFIG_STRICT": True,
            "DB_POOL_SIZE": 10,
            "HF_MONSTERS": False,
        }
    )


@pytest.fixture(scope="session")
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture(scope="session")
async def app(settings: Settings, game_config: GameConfig, clock: FrozenClock) -> AsyncIterator[Any]:
    application = create_app(settings=settings, config=game_config, clock=clock)
    async with LifespanManager(application):
        yield application


@pytest.fixture
def st(app: Any) -> Any:
    return app.state.hf


@pytest.fixture(autouse=True)
async def clean_db(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    if "nodb" in request.keywords:
        yield
        return
    database_url = request.getfixturevalue("database_url")
    dsn, kw = asyncpg_dsn(database_url)
    conn = await asyncpg.connect(dsn, **kw)
    tables = [
        r["tablename"]
        for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        if r["tablename"] not in KEEP_TABLES
    ]
    if tables:
        await conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE")
    await conn.close()
    yield


@pytest.fixture(autouse=True)
def reset_state(request: pytest.FixtureRequest, clock: FrozenClock) -> None:
    from datetime import UTC, datetime

    clock.set(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    if "app" in request.fixturenames or "client" in request.fixturenames:
        app = request.getfixturevalue("app")
        app.state.hf.limiter.reset()


async def _idempotency_key(request: Any) -> None:
    """Like the real client: every mutation carries a fresh Idempotency-Key unless the test set one."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and "idempotency-key" not in request.headers:
        request.headers["idempotency-key"] = str(uuid.uuid4())


@pytest.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
        event_hooks={"request": [_idempotency_key]},
    ) as c:
        yield c


DEFAULT_LOOK = {
    "body": "slim",
    "skin": "honey",
    "hair_style": "crop",
    "hair_color": "chestnut",
    "eyes": "round",
    "eye_color": "brown",
    "outfit": "tunic",
    "outfit_color": "leaf",
}


async def signup(
    client: AsyncClient, username: str = "Tester", password: str = "correct horse"
) -> dict[str, Any]:
    r = await client.post(
        "/api/auth/signup", json={"username": username, "password": password, "appearance": DEFAULT_LOOK}
    )
    assert r.status_code == 201, r.text
    data = r.json()
    client.headers["x-csrf-token"] = data["csrf_token"]
    return data


@pytest.fixture
async def player(client: AsyncClient) -> dict[str, Any]:
    return await signup(client)
