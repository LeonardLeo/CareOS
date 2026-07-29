"""Database engines and the tenant-scoped session.

Two connection pools, deliberately separated by database role:

* **`careos_app`** (`engine`) — the role every request handler uses. It has no
  `BYPASSRLS` attribute, so Postgres Row-Level Security is genuinely enforced against it.
  A handler that forgets to filter by `agency_id` still cannot read another tenant's rows.
* **`careos_auth`** (`privileged_engine`) — a narrow, separately-credentialed pool with
  `BYPASSRLS`, used *only* for the handful of operations that legitimately precede knowing
  the tenant: authenticating a user by email, and provisioning a brand-new agency.

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


async def dispose_engines() -> None:
    global _engine, _privileged_engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _privileged_engine is not None:
        await _privileged_engine.dispose()
        _privileged_engine = None


@asynccontextmanager
async def tenant_session(agency_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """Open a transaction with the tenant GUC set for the life of that transaction.

    `set_config(..., is_local => true)` scopes the setting to the transaction, so it is
    unset automatically on commit or rollback and cannot leak to the next request that
    borrows the same pooled connection.

    Passing ``agency_id=None`` sets the GUC to the empty string. Every RLS policy compares
    `agency_id` against `nullif(current_setting(...), '')::uuid`, which is NULL in that
    case — and `agency_id = NULL` is never true. The failure mode is therefore "no rows",
    not "all rows".
    """
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config(:guc, :value, true)"),
            {"guc": TENANT_GUC, "value": str(agency_id) if agency_id else ""},
        )
        yield session


@asynccontextmanager
async def privileged_session() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for pre-authentication work only.

    Legitimate callers: login (resolve a user by email before the tenant is known) and
    agency provisioning (the tenant does not exist yet). Anything else belongs in
    :func:`tenant_session`.
    """
    session_factory = async_sessionmaker(get_privileged_engine(), expire_on_commit=False)
    async with session_factory() as session, session.begin():
        yield session
