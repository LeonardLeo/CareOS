"""Application settings.

Secrets are read from the environment only. Per `08_Security_Architecture.md` Section 5,
no secret is ever committed to source control; in deployed environments these values are
injected from a dedicated secrets manager.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAREOS_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"

    # --- Database -------------------------------------------------------------
    # The application connects as an unprivileged role so Postgres Row-Level
    # Security is actually enforced (table owners bypass RLS unless FORCE is set,
    # and we do not want to rely on that alone). See db/session.py.
    database_url: str = "postgresql+asyncpg://careos_app:careos_app@localhost:5432/careos"
    # Narrow BYPASSRLS role: login lookups and agency provisioning only. See db/session.py.
    privileged_database_url: str = (
        "postgresql+asyncpg://careos_auth:careos_auth@localhost:5432/careos"
    )
    # Owner/DDL connection, used by migrations only.
    migration_database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/careos"
    db_echo: bool = False

    # --- Cache / queues -------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- Routing --------------------------------------------------------------
    #: Travel-time provider. "haversine" is a distance approximation, adequate for
    #: ranking candidates against each other but not for quoting or paying travel time.
    routing_adapter: str = "haversine"

    # --- Auth -----------------------------------------------------------------
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # 15 minutes — short-lived per API spec Section 1
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14

    # --- EVV ------------------------------------------------------------------
    # Guard rail from `03_Technical_Architecture.md` Section 7: staging must never
    # be pointed at production aggregator endpoints.
    evv_use_sandbox: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and settings.jwt_secret.startswith("dev-only"):
        raise RuntimeError("CAREOS_JWT_SECRET must be set in production")
    if settings.is_production and settings.evv_use_sandbox:
        # Inverse guard: production must transmit to real aggregators.
        raise RuntimeError("CAREOS_EVV_USE_SANDBOX must be false in production")
    return settings
