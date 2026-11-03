"""Password hashing (argon2id), session tokens, recovery codes."""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def make_hasher(profile: str) -> PasswordHasher:
    if profile == "fast":  # tests only
        return PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    # OWASP 2024+ minimum for argon2id: m=19 MiB, t=2, p=1
    return PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


class Passwords:
    def __init__(self, profile: str) -> None:
        self._ph = make_hasher(profile)

    def hash(self, secret: str) -> str:
        return self._ph.hash(secret)

    def verify(self, stored: str, secret: str) -> bool:
        try:
            return self._ph.verify(stored, secret)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, stored: str) -> bool:
        return self._ph.check_needs_rehash(stored)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def normalize_recovery_code(code: str) -> str:
    c = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{c[:5]}-{c[5:]}" if len(c) == 10 else c
