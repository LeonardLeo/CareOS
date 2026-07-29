"""CareOS API — the modular-monolith entrypoint.

`03_Technical_Architecture.md` principle 2: one well-modularized deployable, with domain
modules as packages, rather than premature microservices. The AI/ML inference layer is the
first extraction candidate and is already isolated behind `careos.integrations`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from careos.api.deps import authenticate
from careos.api.v1 import agencies, auth, caregivers, clients, recruiting, visits
from careos.config import get_settings
from careos.core.context import request_id_var, source_ip_var
from careos.core.errors import CareOSError, ValidationError
from careos.core.rbac import assert_all_routes_declare_access, public
from careos.db.models import assert_every_table_is_classified
from careos.db.session import dispose_engines

logger = structlog.get_logger(__name__)

API_PREFIX = "/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Both checks are startup gates rather than tests, so a misconfigured build fails to
    # boot instead of serving traffic with a hole in it.
    assert_every_table_is_classified()
    assert_all_routes_declare_access(app)
    logger.info("careos.startup", environment=get_settings().environment)
    yield
    await dispose_engines()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CareOS API",
        version="0.1.0",
        description=(
            "AI-native operating system for home-based care agencies. "
            "Phase 1 — AI Workforce Engine."
        ),
        lifespan=lifespan,
    )

    # Added for the caregiver app, which — unlike the admin app — calls this API from the
    # device rather than from its own server, because an on-device outbox has to be able to
    # replay a clock-in itself. `allow_credentials` stays False: this API authenticates with a
    # bearer header, not cookies, so there is nothing to gain from it and enabling it would
    # forbid the explicit-origin checks below from ever being relaxed safely.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        # Idempotency-Key is not a CORS-safelisted header, so without naming it here every
        # clock-in from a browser would fail its preflight — silently, since the request never
        # reaches a handler that could report why.
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ):
        """Establish request context and resolve the caller before routing.

        Authentication runs here rather than as a per-route dependency so that
        `request.state.principal` is available to the session dependency, which needs the
        tenant to scope the transaction before any handler code runs.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_token = request_id_var.set(request_id)
        source_ip_token = source_ip_var.set(
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else None)
        )
        try:
            try:
                await authenticate(request)
            except CareOSError as exc:
                return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(request_id_token)
            source_ip_var.reset(source_ip_token)

    @app.exception_handler(CareOSError)
    async def careos_error_handler(_request: Request, exc: CareOSError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Re-shape FastAPI's default 422 body into the single envelope from
        # `05_API_Specification.md` Section 1, so clients parse one error format.
        wrapped = ValidationError(
            "Request failed validation",
            details={"errors": jsonable_encoder(exc.errors())},
        )
        return JSONResponse(status_code=wrapped.status_code, content=wrapped.to_envelope())

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(auth.router)
    v1.include_router(agencies.router)
    v1.include_router(caregivers.router)
    v1.include_router(clients.router)
    v1.include_router(recruiting.router)
    v1.include_router(visits.router)
    app.include_router(v1)

    @app.get("/health", tags=["ops"])
    async def health(_: None = Depends(public())) -> dict[str, str]:
        """Liveness probe. Deliberately does not touch the database.

        A readiness check that fails on a transient database blip would take healthy
        instances out of rotation during exactly the incident you need them for.
        """
        return {"status": "ok", "service": "careos-api"}

    return app


app = create_app()
