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

from careos.api.deps import authenticate, enforce_session_revocation
from careos.api.v1 import agencies, auth, caregivers, clients, recruiting, visits
from careos.config import get_settings
from careos.core.context import request_id_var, source_ip_var
from careos.core.errors import (
    CareOSError,
    CommitFailedError,
    RateLimitExceededError,
    ValidationError,
)
from careos.core.ratelimit import (
    Decision,
    Tier,
    assert_rate_limit_paths_exist,
    get_rate_limiter,
    resolve_route_path,
    tier_for,
)
from careos.core.rbac import assert_all_routes_declare_access, public
from careos.db.models import assert_every_table_is_classified
from careos.db.session import dispose_engines

logger = structlog.get_logger(__name__)

API_PREFIX = "/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # These are startup gates rather than tests, so a misconfigured build fails to boot
    # instead of serving traffic with a hole in it.
    assert_every_table_is_classified()
    assert_all_routes_declare_access(app)
    assert_rate_limit_paths_exist(app)
    limiter = get_rate_limiter()
    # Not a gate: a Redis that is unreachable at boot logs an error and the limiter runs
    # degraded. Refusing to start would take down clock-in — the one endpoint Section 9 says
    # must never be refused — in order to protect a counter.
    await limiter.startup()
    logger.info("careos.startup", environment=get_settings().environment)
    yield
    await limiter.aclose()
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
        # `Retry-After` and the `RateLimit-*` family have to be named here or a browser hides
        # them: only a handful of response headers are readable cross-origin by default, and
        # these are not among them. The caregiver app's outbox reads `Retry-After` to pace its
        # retries, so without this the header was being sent and silently discarded — the queue
        # would fall back to its own backoff and retry a throttled server sooner than asked.
        expose_headers=[
            "X-Request-ID",
            "Retry-After",
            "RateLimit-Limit",
            "RateLimit-Remaining",
            "RateLimit-Reset",
        ],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ):
        """Establish request context, resolve the caller, and apply rate limits.

        Authentication runs here rather than as a per-route dependency so that
        `request.state.principal` is available to the session dependency, which needs the
        tenant to scope the transaction before any handler code runs.

        The order inside is load-bearing:

        1. **Verify the token** — signature only, no database access.
        2. **Rate limit** — using the agency from that token where there is one.
        3. **Check session revocation** — which costs a query, and so must sit behind the
           limiter rather than in front of it. Reversed, an unauthenticated flood would buy a
           database round trip per request, and the limiter would be protecting nothing.
        4. **Commit the request's transaction**, after the handler and before the response
           goes back. See `_commit_unit_of_work` for why it cannot live anywhere else.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_token = request_id_var.set(request_id)
        source_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
            request.client.host if request.client else None
        )
        source_ip_token = source_ip_var.set(source_ip)
        try:
            try:
                principal = await authenticate(request)
                decision = await _apply_rate_limit(request, principal, source_ip)
                if principal is not None:
                    await enforce_session_revocation(principal)
            except RateLimitExceededError as exc:
                response = JSONResponse(status_code=429, content=exc.to_envelope())
                response.headers["Retry-After"] = str(exc.retry_after)
                response.headers["X-Request-ID"] = request_id
                return response
            except CareOSError as exc:
                return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

            response = await call_next(request)

            # Before any header work, because a failed commit replaces the response entirely.
            commit_failure = await _commit_unit_of_work(request)
            if commit_failure is not None:
                commit_failure.headers["X-Request-ID"] = request_id
                return commit_failure

            response.headers["X-Request-ID"] = request_id
            if decision is not None:
                # Advertised on every answered request, not only on refusals, so a client can
                # slow down before it is turned away rather than after.
                response.headers["RateLimit-Limit"] = str(decision.limit)
                response.headers["RateLimit-Remaining"] = str(decision.remaining)
                response.headers["RateLimit-Reset"] = str(decision.reset_after)
            return response
        finally:
            request_id_var.reset(request_id_token)
            source_ip_var.reset(source_ip_token)

    # Registered before the general CareOSError handler because a 429 also needs Retry-After,
    # and the login endpoint raises one from inside a handler rather than from middleware.
    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_handler(_request: Request, exc: RateLimitExceededError) -> JSONResponse:
        response = JSONResponse(status_code=exc.status_code, content=exc.to_envelope())
        response.headers["Retry-After"] = str(exc.retry_after)
        return response

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


async def _commit_unit_of_work(request: Request) -> JSONResponse | None:
    """Commit the request's transaction. Returns a response to send *instead* on failure.

    **Why here.** `db_session` is a dependency with `yield`, and FastAPI runs that teardown
    after the response has been written to the socket. Committing there meant two things, both
    bad, and both reproduced against a real server rather than argued from the docs:

    * A client could not read its own write. The response came back in 3 ms and the commit
      landed 300 ms later, so anything that created a resource and immediately used its id
      could get a 404. That is what the caregiver-app end-to-end seed kept hitting.
    * **A failed commit could not be reported.** The response was already gone, so there was no
      status code left to change: with the commit forced to fail, the client received
      `200 {"status": "clocked_in", "evv_record": "created"}` while the server logged the
      rollback. A caregiver told their clock-in was recorded when it was not is the exact
      failure this product exists to prevent.

    Middleware is where a request can still change its own answer, so the commit belongs here.

    `in_transaction()` is the test for whether to commit, and it means "did this request
    succeed?". A handler that raised has already unwound through `db_session`, which rolled
    back on the way past — so there is nothing open to commit. A handler that returned
    normally, including one that returned an error response without raising, still holds its
    transaction, and committing it preserves exactly what the old teardown did.
    """
    session = getattr(request.state, "unit_of_work", None)
    if session is None or not session.in_transaction():
        return None

    if not session.is_active:
        # A flush failed and the handler swallowed it, so the transaction can only be rolled
        # back. The handler was about to answer as though the write had happened, which is the
        # very thing this function exists to stop — so the answer becomes the truth instead.
        logger.error(
            "request.transaction_deactivated",
            path=request.url.path,
            method=request.method,
            note="a database error was caught by a handler that then answered successfully",
        )
        await session.rollback()
        return _commit_failed_response()

    try:
        await session.commit()
    except Exception as exc:
        logger.error(
            "request.commit_failed",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        try:
            await session.rollback()
        except Exception:  # pragma: no cover - the connection is already in trouble
            logger.exception("request.rollback_after_commit_failure_failed")
        return _commit_failed_response()
    return None


def _commit_failed_response() -> JSONResponse:
    error = CommitFailedError(
        "The request could not be saved. Nothing was changed — please try again."
    )
    return JSONResponse(status_code=error.status_code, content=error.to_envelope())


async def _apply_rate_limit(
    request: Request, principal: object | None, source_ip: str | None
) -> Decision | None:
    """Apply the tier's limit and raise 429 if it is spent. Returns the decision when allowed.

    The tier comes from the matched route *template*, so `/v1/visits/{visit_id}/clock-in` is
    exempt for every visit id rather than for a literal path nobody requests.
    """
    resolved = resolve_route_path(request.app, request.url.path, request.method)
    if resolved is None:
        # Nothing matched, so this is a 404 in the making — a scanner's traffic. Limit it as
        # standard rather than letting unmatched paths through unlimited.
        tier = Tier.standard
    else:
        path, method = resolved
        tier = tier_for(path, method)

    limiter = get_rate_limiter()
    agency_id = getattr(principal, "agency_id", None)

    if tier is Tier.exempt and resolved is not None and "clock-" in resolved[0]:
        # Exempt from throttling, per Section 9 — but the same section asks for abuse detection
        # in its place, so the volume is still counted and logged. This never refuses.
        #
        # It does put a Redis round trip on the clock-in path, which is telemetry blocking the
        # one endpoint that must never be delayed unnecessarily. Accepted rather than made
        # fire-and-forget: the call is bounded by a 250 ms socket timeout, the breaker stops a
        # dead Redis from costing even that more than once, and it is one hop among several
        # database round trips the handler makes anyway. Revisit if it ever shows up in the
        # clock-in latency rather than on the strength of the argument.
        await limiter.note_evv_volume(
            agency_id=str(agency_id) if agency_id else None,
            caregiver_id=(
                str(getattr(principal, "caregiver_id", None))
                if getattr(principal, "caregiver_id", None)
                else None
            ),
        )

    decision = await limiter.check(
        tier=tier,
        agency_id=str(agency_id) if agency_id else None,
        source_ip=source_ip,
    )
    if decision is not None and not decision.allowed:
        raise RateLimitExceededError(
            "Too many requests. Please retry shortly.",
            retry_after=decision.retry_after,
            details={"limit_per_minute": decision.limit, "tier": tier.value},
        )
    return decision


app = create_app()
