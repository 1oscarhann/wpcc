from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class GameError(Exception):
    """A rule violation the player can see. `code` is stable; `message` is a friendly default."""

    status = 400

    def __init__(self, code: str, message: str, status: int | None = None, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status
        self.details = details


class NotFound(GameError):
    status = 404


class Forbidden(GameError):
    status = 403


class Unauthorized(GameError):
    status = 401


class TooManyRequests(GameError):
    status = 429


async def game_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GameError)
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )
