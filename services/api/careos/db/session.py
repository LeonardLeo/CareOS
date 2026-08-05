"""Database engines and the tenant-scoped session.

Three connection pools, deliberately separated by database role:

* **`careos_app`** (`engine`) — the role every request handler uses. It has no
  `BYPASSRLS` attribute, so Postgres Row-Level Security is genuinely enforced against it.
  A handler that forgets to filter by `agency_id` still cannot read another tenant's rows.
* **`careos_auth`** (`privileged_engine`) — a narrow, separately-credentialed pool with
  `BYPASSRLS`, used *only* for the handful of operations that legitimately precede knowing
  the tenant: authenticating a user by email, and provisioning a brand-new agency.
* **`careos_platform`** (`platform_engine`) — the CareOS operator console. Also **no
  `BYPASSRLS`**. Its cross-tenant visibility is one `SELECT` grant on one aggregate view,
  and it holds no grant at all on any table carrying PHI. See `careos.db.rls` and
  `careos.modules.platform.models`.

Keeping these as distinct pools rather than one pool with a toggle means the privileged
path is a deliberate import, not a flag any handler can flip. This is the application-layer
half of the two-layer isolation required by `08_Security_Architecture.md` Section 2.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from careos.config import get_settings

_engine: AsyncEngine | None = None
_privileged_engine: AsyncEngine | None = None
_platform_engine: AsyncEngine | None = None

#: Postgres GUC read by every RLS policy. Set per transaction, never per connection —
#: a pooled connection outliving a request must not carry a tenant with it.
TENANT_GUC = "careos.agency_id"


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
        )
    return _engine


def get_privileged_engine() -> AsyncEngine:
    global _privileged_engine
    if _privileged_engine is None:
        settings = get_settings()
        _privileged_engine = create_async_engine(
            settings.privileged_database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
        )
    return _privileged_engine


def get_platform_engine() -> AsyncEngine:
    """The pool the CareOS platform console runs on.

    A third pool rather than a third setting on an existing one, for the same reason the
    privileged pool is separate: which database role a query runs as is the enforcement, so
    it should be decided by which module you imported rather than by an argument someone
    could pass from the wrong place.
    """
    global _platform_engine
    if _platform_engine is None:
        settings = get_settings()
        _platform_engine = create_async_engine(
            settings.platform_database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
            # Small on purpose. This pool serves a handful of CareOS staff, and sizing it
            # like the tenant pool would let the operator console compete for connections
            # with the caregivers clocking in.
            pool_size=3,
            max_overflow=2,
        )
    return _platform_engine


async def dispose_engines() -> None:
    global _engine, _privileged_engine, _platform_engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _privileged_engine is not None:
        await _privileged_engine.dispose()
        _privileged_engine = None
    if _platform_engine is not None:
        await _platform_engine.dispose()
        _platform_engine = None


async def begin_tenant_session(agency_id: uuid.UUID | None) -> AsyncSession:
    """Open a transaction with the tenant GUC set. **The caller owns commit and close.**

    `set_config(..., is_local => true)` scopes the setting to the transaction, so it is
    unset automatically on commit or rollback and cannot leak to the next request that
    borrows the same pooled connection.

    Passing ``agency_id=None`` sets the GUC to the empty string. Every RLS policy compares
    `agency_id` against `nullif(current_setting(...), '')::uuid`, which is NULL in that
    case — and `agency_id = NULL` is never true. The failure mode is therefore "no rows",
    not "all rows".

    Separate from `tenant_session` because the request path cannot use a context manager
    here. A `with` block that commits on exit puts the commit in the dependency's teardown,
    and FastAPI runs that *after* the response has gone to the client — which meant every
    write was answered before it was durable, and a failed commit had no status code left
    to be reported in. `careos.main` commits this in the middleware instead, while the
    response can still change. Background jobs and tests have no such constraint and should
    keep using `tenant_session`.
    """
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    session = session_factory()
    await session.begin()
    try:
        await session.execute(
            text("SELECT set_config(:guc, :value, true)"),
            {"guc": TENANT_GUC, "value": str(agency_id) if agency_id else ""},
        )
    except BaseException:
        # A session handed back without its tenant GUC set would read as an untenanted
        # caller. RLS makes that "no rows" rather than "every row", but it must not happen
        # silently either way.
        await session.close()
        raise
    return session


@asynccontextmanager
async def tenant_session(agency_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """`begin_tenant_session` with commit-on-exit and rollback-on-error.

    For background jobs, scripts, and tests. Request handlers get their session from
    `careos.api.deps.db_session`, which leaves the commit to the middleware.
    """
    session = await begin_tenant_session(agency_id)
    async with session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        if session.is_active:
            await session.commit()
        else:
            # A failed flush that the caller caught and carried on from leaves the transaction
            # deactivated: it can only be rolled back, and committing it raises a
            # PendingRollbackError that says nothing about the original error. The old
            # `session.begin()` context did the same thing by returning early once SQLAlchemy
            # had cleared the transaction; this states it rather than inheriting it.
            await session.rollback()


@asynccontextmanager
async def privileged_session() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for pre-authentication work only.

    Legitimate callers: login (resolve a user by email before the tenant is known), agency
    provisioning (the tenant does not exist yet), and the background runner enumerating
    `agency.id` (a worker has no tenant until it picks one). Anything else belongs in
    :func:`tenant_session` — including everything those callers do *after* the tenant is
    known, which is why login hands off mid-request and the runner reads ids and nothing else.
    """
    session_factory = async_sessionmaker(get_privileged_engine(), expire_on_commit=False)
    async with session_factory() as session, session.begin():
        yield session


async def begin_platform_session() -> AsyncSession:
    """Open a transaction as `careos_platform`. **The caller owns commit and close.**

    Deliberately sets no tenant GUC. There is no tenant: this connection reads one
    cross-tenant aggregate view and writes to `agency`, `platform_audit_log`, and
    `audit_log`, and every one of those is governed by a policy naming this role rather than
    by `careos.agency_id`.

    Leaving the GUC unset is also the safer failure. If somebody later grants this role
    something on a tenant table by mistake, the tenant policy it would then be evaluated
    against compares `agency_id` against `nullif(current_setting(...), '')::uuid`, which is
    NULL — and `agency_id = NULL` matches nothing. The accident reads as an empty result
    rather than as another tenant's rows.

    Split from `platform_session` for the same reason `begin_tenant_session` is split from
    `tenant_session`: the request path needs the middleware to own the commit, so that a
    failed one can still change the response.
    """
    session_factory = async_sessionmaker(get_platform_engine(), expire_on_commit=False)
    session = session_factory()
    await session.begin()
    return session


@asynccontextmanager
async def platform_session() -> AsyncIterator[AsyncSession]:
    """`begin_platform_session` with commit-on-exit and rollback-on-error.

    For the login path, scripts, and tests. Platform request handlers get their session from
    `careos.api.deps.platform_db_session`, which leaves the commit to the middleware.
    """
    session = await begin_platform_session()
    async with session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        if session.is_active:
            await session.commit()
        else:
            await session.rollback()


@asynccontextmanager
async def advisory_job_lock(key: str) -> AsyncIterator[bool]:
    """Try to take a cluster-wide lock named `key`; yield whether we got it.

    For background jobs, where "two workers doing this at once" ranges from wasteful to wrong.
    `SKIP LOCKED` already stops two workers sending the same queued row twice, but it cannot
    help a job that *reads* to decide whether to write — the credential-expiry announcer checks
    for an existing delivery before queueing one, and two workers can both read "no" before
    either writes.

    Try-and-skip rather than wait-and-queue. A worker that cannot get the lock has nothing
    useful to do with the time: another worker is already doing that exact job, and the next
    tick is seconds away. Waiting would just build a queue of workers all about to discover
    there is no work left.

    Held on its own connection for the life of the block, so it spans the job's transactions
    rather than ending with the first commit. Session-level, so it is released by
    `pg_advisory_unlock` here and by the connection closing if this process dies — a crashed
    worker cannot leave a job permanently locked.

    `hashtext` narrows the key to 32 bits, so two different keys can collide. The consequence
    is bounded and self-correcting: one job is skipped for one tick and runs on the next.
    """
    engine = get_engine()
    async with engine.connect() as connection:
        acquired = bool(
            (
                await connection.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}
                )
            ).scalar_one()
        )
        try:
            yield acquired
        finally:
            if acquired:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key}
                )
