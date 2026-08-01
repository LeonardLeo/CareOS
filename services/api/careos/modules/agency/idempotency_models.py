"""Idempotency records for mutating endpoints with external side effects.

`05_API_Specification.md` Section 1 requires an `Idempotency-Key` on any mutation that
reaches outside the system — EVV transmission, claim submission, background-check
initiation. This matters most for the caregiver mobile app: it queues actions offline and
replays them on reconnect (`03_Technical_Architecture.md` principle 4), so a retry after a
flaky response is the normal case, not an edge case. Transmitting a duplicate visit to a
state aggregator is a compliance problem, not a cosmetic one.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin


class IdempotencyState(enum.StrEnum):
    in_progress = "in_progress"
    completed = "completed"


class IdempotencyRecord(Base, PrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        # The key is scoped per tenant and per endpoint: two different endpoints may
        # legitimately be called with the same client-generated key.
        Index("uq_idempotency_agency_endpoint_key", "agency_id", "endpoint", "key", unique=True),
    )

    key: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    #: Hash of the request body. A replay carrying the *same* key but a *different* payload
    #: is a client bug, and returning the first response would silently discard the second
    #: request — so it is rejected instead.
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[IdempotencyState] = mapped_column(
        SAEnum(IdempotencyState, name="idempotency_state"),
        nullable=False,
        default=IdempotencyState.in_progress,
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
