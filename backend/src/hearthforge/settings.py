"""Runtime settings, read from the environment (and `.env` for local dev)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


def normalize_database_url(url: str) -> str:
    """Accept Neon/libpq style URLs and turn them into something asyncpg understands (D-032).

    - ``postgres://`` / ``postgresql://`` → ``postgresql+asyncpg://``
    - ``sslmode=require`` → ``ssl=require``
    - ``channel_binding`` is dropped (asyncpg does not support it)
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
        if key == "sslmode":
            key = "ssl"
        query.append((key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def asyncpg_dsn(url: str) -> tuple[str, dict[str, str]]:
    """Plain asyncpg DSN (for LISTEN connections) plus connect kwargs."""
    parts = urlsplit(normalize_database_url(url))
    kwargs: dict[str, str] = {}
    query = []
    for key, value in parse_qsl(parts.query):
        if key == "ssl":
            kwargs["ssl"] = value
        else:
            query.append((key, value))
    dsn = urlunsplit(("postgresql", parts.netloc, parts.path, urlencode(query), ""))
    return dsn, kwargs


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_prefix="", extra="ignore")

    env: str = Field(default="dev", alias="HF_ENV")
    database_url: str = Field(
        default="postgresql+asyncpg://hf@127.0.0.1:5433/hearthforge", alias="DATABASE_URL"
    )
    config_dir: Path = Field(default=REPO_ROOT / "config", alias="HF_CONFIG_DIR")
    config_strict: bool = Field(default=False, alias="HF_CONFIG_STRICT")
    frontend_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173"], alias="FRONTEND_ORIGINS"
    )
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cookie_domain: str | None = Field(default=None, alias="COOKIE_DOMAIN")
    run_worker_in_process: bool = Field(default=False, alias="RUN_WORKER_IN_PROCESS")
    argon2_profile: str = Field(default="secure", alias="HF_ARGON2_PROFILE")  # secure | fast (tests)
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    enable_listener: bool = Field(default=True, alias="HF_ENABLE_LISTENER")
    monsters_enabled: bool = Field(default=True, alias="HF_MONSTERS")
    # Phase 18: serve the built frontend from the API (one origin, so cookies and the socket just work)
    static_dir: Path | None = Field(default=None, alias="HF_STATIC_DIR")

    @field_validator("database_url")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_database_url(v)

    @field_validator("frontend_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
