from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.core.errors import Forbidden, TooManyRequests, Unauthorized
from hearthforge.db.models import Session, User
from hearthforge.services import sessions
from hearthforge.state import AppState

SESSION_COOKIE = "hf_session"
CSRF_COOKIE = "hf_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def get_state(request: Request) -> AppState:
    return request.app.state.hf


async def get_db(st: AppState = Depends(get_state)) -> AsyncIterator[AsyncSession]:
    async with st.sessionmaker() as session:
        yield session


@dataclass
class Auth:
    user: User
    session: Session
    token: str


async def current_user(
    request: Request, st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> Auth:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized("not_logged_in", "Please log in.")
    now = st.clock.now()
    found = await sessions.lookup(db, token, now)
    if found is None:
        raise Unauthorized("not_logged_in", "Your session expired. Please log in again.")
    sess, user = found
    if request.method in UNSAFE:
        header = request.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(header, sess.csrf_token):
            raise Forbidden("csrf", "Security check failed. Please reload the page.")
    if now - sess.last_used_at > timedelta(minutes=5):
        sess.last_used_at = now
        user.last_seen_at = now
    # Always close the implicit transaction so routes can open their own with `db.begin()`.
    await db.commit()
    return Auth(user=user, session=sess, token=token)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, per_minute_attr: str):  # noqa: ANN201
    """Dependency factory: per-user limit for logged-in action endpoints."""

    async def dep(auth: Auth = Depends(current_user), st: AppState = Depends(get_state)) -> None:
        limit = getattr(st.config.game.rate_limits, per_minute_attr)
        if not st.limiter.hit(f"{bucket}:{auth.user.id}", limit):
            raise TooManyRequests("rate_limited", "Slow down a little!")

    return dep


async def admin_user(auth: Auth = Depends(current_user)) -> Auth:
    from hearthforge.db.models import UserRole

    if auth.user.role != UserRole.admin:
        raise Forbidden("admin_only", "Admins only.")
    return auth
