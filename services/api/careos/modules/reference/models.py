"""Global (non-tenant) reference tables — `04_Data_Model_and_Schema.md` Section 6.

These carry no `agency_id` and no RLS policy: they are shared lookup data, readable by
every tenant and writable only by migrations/seed jobs.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, TimestampMixin


class EVVModel(enum.StrEnum):
    """How a state chooses to receive EVV data (`06_Compliance...` Section 1)."""

    state_mandated_vendor = "state_mandated_vendor"
    state_provided_open_system = "state_provided_open_system"
    open_vendor_to_aggregator = "open_vendor_to_aggregator"


class CredentialTypeRef(Base, TimestampMixin):
    __tablename__ = "credential_type_ref"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Some credentials are required only in certain states, or carry state-specific
    #: renewal intervals — kept as JSONB because the shape varies per credential.
    state_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Whether expiry blocks scheduling outright, versus merely warning.
    blocks_scheduling_on_expiry: Mapped[bool] = mapped_column(nullable=False, default=True)


class EVVAggregatorRef(Base, TimestampMixin):
    """Per-state EVV aggregator assignment.

    States periodically reassign vendors (`06_Compliance...` Section 1), so this is data,
    not code. Changing a state's aggregator is a row update plus an adapter that already
    exists — never a change to the scheduling module.
    """

    __tablename__ = "evv_aggregator_ref"

    state_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    #: Key into the adapter registry (careos.integrations.evv.registry).
    adapter_key: Mapped[str] = mapped_column(Text, nullable=False)
    evv_model: Mapped[EVVModel] = mapped_column(SAEnum(EVVModel, name="evv_model"), nullable=False)
    aggregator_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Non-secret connection details. Credentials live in the secrets manager, keyed by
    #: `adapter_key` — never here (`08_Security_Architecture.md` Section 5).
    connection_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: Set false until this state's adapter has been validated against the vendor sandbox
    #: (`07_Integration_Specifications.md` Section 2 makes that a hard precondition).
    sandbox_validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PayerServiceCodeRef(Base, TimestampMixin):
    """Billing/service codes, scoped per state and payer type.

    `06_Compliance...` Section 4 is explicit that no billing rule discovered for one
    state's Medicaid program generalizes to another, so the primary key includes the state.
    """

    __tablename__ = "payer_service_code_ref"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    state_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    payer_type: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_minutes: Mapped[int | None] = mapped_column(nullable=True)
    #: Modifiers and payer-specific required fields, consumed by the Phase 3 scrubber.
    billing_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requires_evv: Mapped[bool] = mapped_column(nullable=False, default=True)
