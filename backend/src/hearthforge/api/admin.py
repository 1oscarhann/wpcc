"""Admin endpoints (role=admin). Phase 7: the economy view. The rest of the admin panel is Phase 18."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import Auth, admin_user, get_db, get_state
from hearthforge.services import economy
from hearthforge.state import AppState

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/economy")
async def economy_view(
    _: Auth = Depends(admin_user), st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Coin supply now and over 7 days (one sample per market recalc), faucets vs sinks by reason."""
    async with db.begin():
        return await economy.report(db, st.clock.now())
