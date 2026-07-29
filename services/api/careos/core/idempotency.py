"""Idempotency-Key handling for mutations with external side effects.

The contract (`05_API_Specification.md` Section 1):

* First request with a given key runs the handler and stores its response.
* A replay with the same key and the same body replays the stored response.
* A replay with the same key but a *different* body is rejected — silently returning the
  first response would discard the second request without the client ever knowing.
* A replay arriving while the first is still in flight gets 409 rather than a second
  execution.

Uniqueness is enforced by a unique index, not by a read-then-write check, so two concurrent
replays cannot both pass the check and both execute.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.errors import ConflictError, IdempotencyKeyRequiredError
from careos.core.security import Principal
from careos.modules.agency.idempotency_models import IdempotencyRecord, IdempotencyState


def hash_request(payload: Any) -> str:
    """Stable hash of a request body — key order must not change the digest."""
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(slots=True)
class IdempotencyOutcome:
    """Either a replayed response, or a claim entitling the caller to execute."""

    replayed_status: int | None
    replayed_body: dict[str, Any] | None
    record: IdempotencyRecord | None

    @property
    def is_replay(self) -> bool:
        return self.replayed_body is not None


async def claim(
    session: AsyncSession,
    *,
    principal: Principal,
    key: str | None,
    endpoint: str,
    payload: Any,
) -> IdempotencyOutcome:
    """Claim the right to execute `endpoint` for `key`, or return the stored response."""
    if not key:
        raise IdempotencyKeyRequiredError(
            "This endpoint has external side effects and requires an Idempotency-Key header",
            details={"endpoint": endpoint},
        )

    request_hash = hash_request(payload)
    record = IdempotencyRecord(
        agency_id=principal.agency_id,
        key=key,
        endpoint=endpoint,
        request_hash=request_hash,
        state=IdempotencyState.in_progress,
    )
    try:
        # SAVEPOINT: a duplicate-key violation must not poison the caller's transaction,
        # because on replay we still need to read the stored response from it.
        #
        # Both the `add` and the `flush` go inside the savepoint. Adding the instance
        # outside it would leave the failed INSERT attached to the outer transaction, and
        # the subsequent read would fail on a transaction the flush error had already
        # deactivated.
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError:
        existing = (
            await session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.agency_id == principal.agency_id,
                    IdempotencyRecord.endpoint == endpoint,
                    IdempotencyRecord.key == key,
                )
            )
        ).scalar_one()

        if existing.request_hash != request_hash:
            raise ConflictError(
                "This Idempotency-Key was already used with a different request body",
                details={"endpoint": endpoint},
            ) from None
        if existing.state is IdempotencyState.in_progress:
            raise ConflictError(
                "A request with this Idempotency-Key is still in progress",
                details={"endpoint": endpoint},
            ) from None
        return IdempotencyOutcome(
            replayed_status=existing.response_status,
            replayed_body=existing.response_body,
            record=existing,
        )

    return IdempotencyOutcome(replayed_status=None, replayed_body=None, record=record)


async def complete(
    session: AsyncSession,
    record: IdempotencyRecord,
    *,
    status: int,
    body: dict[str, Any],
) -> None:
    """Store the response so a later replay returns it verbatim."""
    record.state = IdempotencyState.completed
    record.response_status = status
    record.response_body = body
    record.completed_at = datetime.now(UTC)
    await session.flush()
