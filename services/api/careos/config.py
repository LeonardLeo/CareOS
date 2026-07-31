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

    # --- Rate limits (`05_API_Specification.md` Section 9) --------------------
    #: Where the token buckets live. "redis" shares them across instances, so the ceiling below
    #: is the ceiling the cluster enforces; "memory" keeps them in this process, which multiplies
    #: every limit by the instance count and is therefore only honest for a single instance.
    #:
    #: Defaults to memory so development and the test suite need no Redis. Production may not
    #: use it — see `validate_settings`, and the reasoning in `careos.core.ratelimit`.
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    #: The documented default: 100 requests/minute per agency for standard endpoints.
    rate_limit_standard_per_minute: int = 100
    #: Login and refresh attempts per minute for one address/account pair. Tight on purpose:
    #: nobody types their own password ten times a minute, and an attacker needs thousands.
    rate_limit_auth_per_minute: int = 10
    #: Auth attempts per minute from one address across all accounts, so credential spraying
    #: across many emails is limited even though each account stays under its own ceiling.
    rate_limit_auth_per_ip_per_minute: int = 30
    #: Clock-ins/outs per minute from one caregiver above which the volume is logged as
    #: anomalous. Never throttles — Section 9 forbids that — it only makes abuse visible.
    rate_limit_evv_anomaly_per_minute: int = 30

    # --- Background worker (`careos.workers.runner`) --------------------------
    #: How often the runner wakes up. Each job has its own interval on top of this, so the
    #: poll is the resolution of the schedule rather than the schedule itself.
    worker_poll_seconds: float = 15.0
    #: EVV first: late transmission is a compliance problem, and the adapter has its own
    #: backoff, so a tight poll costs little.
    worker_evv_interval_seconds: float = 30.0
    #: Webhooks match it. A receiver waiting minutes for an event polls the API instead,
    #: which is the load webhooks exist to remove.
    worker_webhook_interval_seconds: float = 30.0
    #: Daily, because nothing changes about "expires in 12 days" between one minute and the
    #: next. Safe to run more often — the announcer deduplicates — but pointless.
    worker_credential_interval_seconds: float = 86_400.0
    #: Port for the worker's own metrics endpoint. 0 disables it.
    worker_metrics_port: int = 9101
    #: Bind address for that endpoint. A collector in another container needs 0.0.0.0; a
    #: deployment that scrapes over localhost should narrow it.
    worker_metrics_host: str = "0.0.0.0"  # noqa: S104

    # --- Observability --------------------------------------------------------
    #: Bearer token a collector must present to scrape `/metrics`. Empty leaves the endpoint
    #: open, which is fine behind a private network and is the local default.
    #:
    #: Production must set it — see `validate_settings`. The series are deliberately free of
    #: tenant and person labels, but they still describe traffic shape, error rates, and when
    #: the system is degraded, which is reconnaissance worth denying.
    metrics_token: str = ""

    # --- Browser clients ------------------------------------------------------
    #: Origins allowed to call this API from a browser. The caregiver app needs this and the
    #: admin app does not: the admin app calls from its own server, while the caregiver PWA
    #: must call from the device so a service worker and an on-device queue can replay a
    #: clock-in themselves.
    #:
    #: An explicit allowlist, never a wildcard. These requests carry a bearer token and the
    #: responses carry PHI, so `*` would let any page a caregiver has open read their schedule.
    #: Defaults cover the local dev ports only; a deployed environment must set this.
    cors_allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]

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


def validate_settings(settings: Settings) -> Settings:
    """Refuse to run on a configuration that would be unsafe in the target environment.

    Separate from `get_settings` so each guard can be tested against a constructed Settings
    rather than only through an `lru_cache`d factory reading process environment — which is the
    difference between these rules being verified and merely being written down.
    """
    if not settings.is_production:
        return settings

    if settings.jwt_secret.startswith("dev-only"):
        raise RuntimeError("CAREOS_JWT_SECRET must be set in production")
    if settings.evv_use_sandbox:
        # Inverse guard: production must transmit to real aggregators.
        raise RuntimeError("CAREOS_EVV_USE_SANDBOX must be false in production")
    if "*" in settings.cors_allowed_origins:
        raise RuntimeError("CAREOS_CORS_ALLOWED_ORIGINS must not be a wildcard in production")
    if any(
        origin.startswith(("http://localhost", "http://127.0.0.1"))
        for origin in settings.cors_allowed_origins
    ):
        # A localhost origin left in a production allowlist is a standing invitation: any page
        # can host a listener on 127.0.0.1 and read a caregiver's schedule from a real token.
        raise RuntimeError("CAREOS_CORS_ALLOWED_ORIGINS must not include localhost in production")
    if settings.rate_limit_backend == "memory":
        # A production deployment is more than one instance by definition, and in-process
        # buckets there enforce N times the documented ceiling while the `RateLimit-*` headers
        # keep reporting the documented one. The failure is invisible from the outside — the
        # limiter looks like it is working — which is exactly why it is a boot gate rather than
        # a warning.
        raise RuntimeError(
            "CAREOS_RATE_LIMIT_BACKEND must be 'redis' in production: in-process buckets "
            "multiply every published limit by the instance count"
        )
    if not settings.metrics_token:
        # An unauthenticated `/metrics` on a public listener hands out request rates, error
        # rates, and a flag saying when rate limiting is degraded. A boot gate rather than a
        # default token, because a default would be the same as no token everywhere it was
        # not changed.
        raise RuntimeError(
            "CAREOS_METRICS_TOKEN must be set in production, or /metrics is readable by anyone"
        )
    return settings


@lru_cache
def get_settings() -> Settings:
    return validate_settings(Settings())
