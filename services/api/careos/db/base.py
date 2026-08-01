"""Declarative base and shared column mixins.

Multi-tenancy convention (`04_Data_Model_and_Schema.md` Section 1): every tenant-scoped
table carries `agency_id`. `TenantMixin` is the single place that is defined, so a new
table cannot accidentally omit it — inherit the mixin and the tenant key, its index, and
its foreign key all come along.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """Tenant key for every non-global table.

    `agency_id` is denormalized onto child tables (e.g. `credential`, `evv_record`) rather
    than reached via a join. That is deliberate: the RLS policy needs the tenant key on the
    row itself to filter without a subquery, and a denormalized key means an isolation bug
    cannot hide behind a join path.
    """

    agency_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
