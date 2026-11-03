from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Auth,
    client_ip,
    current_user,
    get_db,
    get_state,
)
from hearthforge.core.errors import GameError, TooManyRequests, Unauthorized
from hearthforge.core.security import normalize_recovery_code
from hearthforge.db.models import RecoveryCode, User
from hearthforge.services import sessions, signup
from hearthforge.state import AppState

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    appearance: dict[str, Any]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class RecoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    code: str
    new_password: str


def _set_cookies(st: AppState, response: Response, token: str, csrf: str) -> None:
    ttl = int(st.config.game.auth.session_ttl)
    common = {
        "max_age": ttl,
        "secure": st.settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
        "domain": st.settings.cookie_domain,
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)


def _clear_cookies(st: AppState, response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", domain=st.settings.cookie_domain)


def _limit_auth(st: AppState, request: Request, username: str | None = None) -> None:
    rl = st.config.game.rate_limits
    if not st.limiter.hit(f"auth-ip:{client_ip(request)}", rl.auth_per_ip_per_min):
        raise TooManyRequests("rate_limited", "Too many attempts. Wait a minute and try again.")
    if username and not st.limiter.hit(f"auth-user:{username.lower()}", rl.auth_per_username_per_min):
        raise TooManyRequests("rate_limited", "Too many attempts for this account. Wait a minute.")


@router.get("/username-available")
async def username_available(
    name: str, request: Request, st: AppState = Depends(get_state), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if not st.limiter.hit(f"uname:{client_ip(request)}", 120):
        raise TooManyRequests("rate_limited", "Slow down a little!")
    try:
        signup.check_username(st.config, name)
    except GameError as e:
        return {"ok": False, "reason": e.message}
    if await signup.username_taken(db, name):
        return {"ok": False, "reason": "That username is taken."}
    return {"ok": True, "reason": None}


@router.post("/signup", status_code=201)
async def signup_route(
    body: SignupIn,
    request: Request,
    response: Response,
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _limit_auth(st, request)
    now = st.clock.now()
    try:
        async with db.begin():
            user, codes = await signup.create_player(
                db, st.config, st.passwords, now, body.username, body.password, body.appearance
            )
            token, csrf = await sessions.create_session(db, user.id, now, st.config.game.auth.session_ttl)
    except IntegrityError as e:
        raise GameError("username_taken", "That username is taken.", status=409) from e
    _set_cookies(st, response, token, csrf)
    return {"user_id": str(user.id), "username": user.username, "csrf_token": csrf, "recovery_codes": codes}


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _limit_auth(st, request, body.username)
    now = st.clock.now()
    async with db.begin():
        user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
        # Verify against a dummy hash when the user doesn't exist, so timing doesn't leak usernames.
        stored = user.password_hash if user else st.passwords.hash("not-a-real-password")
        ok = st.passwords.verify(stored, body.password)
        if not user or not ok or user.banned_at is not None:
            raise Unauthorized("bad_credentials", "Wrong username or password.")
        if st.passwords.needs_rehash(user.password_hash):
            user.password_hash = st.passwords.hash(body.password)
        user.last_seen_at = now
        token, csrf = await sessions.create_session(db, user.id, now, st.config.game.auth.session_ttl)
    _set_cookies(st, response, token, csrf)
    return {"user_id": str(user.id), "username": user.username, "csrf_token": csrf}


@router.post("/logout")
async def logout(
    response: Response,
    auth: Auth = Depends(current_user),
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    async with db.begin():
        await sessions.revoke(db, auth.token)
    _clear_cookies(st, response)
    return {"ok": True}


@router.post("/recover")
async def recover(
    body: RecoverIn,
    request: Request,
    response: Response,
    st: AppState = Depends(get_state),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _limit_auth(st, request, body.username)
    signup.check_password(st.config, body.new_password)
    code = normalize_recovery_code(body.code)
    now = st.clock.now()
    async with db.begin():
        user = (
            await db.execute(select(User).where(User.username == body.username).with_for_update())
        ).scalar_one_or_none()
        if user is None:
            raise Unauthorized("bad_recovery", "That recovery code didn't work.")
        rows = (
            (
                await db.execute(
                    select(RecoveryCode).where(
                        RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        match = next((r for r in rows if st.passwords.verify(r.code_hash, code)), None)
        if match is None:
            raise Unauthorized("bad_recovery", "That recovery code didn't work.")
        match.used_at = now
        user.password_hash = st.passwords.hash(body.new_password)
        await sessions.revoke_all(db, user.id)
        token, csrf = await sessions.create_session(db, user.id, now, st.config.game.auth.session_ttl)
        remaining = len(rows) - 1
    _set_cookies(st, response, token, csrf)
    return {"user_id": str(user.id), "username": user.username, "csrf_token": csrf, "codes_left": remaining}
