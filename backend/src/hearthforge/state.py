"""Process-wide singletons, hung off `app.state.hf`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hearthforge.clock import Clock
from hearthforge.config.loader import GameConfig
from hearthforge.core.rate_limit import RateLimiter
from hearthforge.core.security import Passwords
from hearthforge.settings import Settings

if TYPE_CHECKING:
    from hearthforge.realtime.hubs import VillageHub
    from hearthforge.sim.manager import RoomManager


@dataclass
class AppState:
    settings: Settings
    config: GameConfig
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    clock: Clock
    passwords: Passwords
    limiter: RateLimiter = field(default_factory=RateLimiter)
    village_hub: VillageHub | None = None
    rooms: RoomManager | None = None
