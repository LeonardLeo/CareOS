"""Append-only audit trail — cross-cutting infrastructure, not a feature.

`08_Security_Architecture.md` Section 4 and the PRD's auditability NFR require that every
clinically or financially significant action is attributable and immutable. Immutability is
enforced at the database permission level: the `careos_app` role is granted SELECT and
INSERT on this table and nothing else, so an application bug — or an attacker holding the
application's credentials — cannot rewrite history. See the migration that revokes
UPDATE/DELETE.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from careos.db.base import Base, PrimaryKeyMixin, TenantMixin


class AuditLog(Base, PrimaryKeyMixin, TenantMixin):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "agency_id", "entity_type", "entity_id"),
        Index("ix_audit_log_occurred", "agency_id", "occurred_at"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    #: Dotted action name, e.g. "visit_note.signed", "claim.submitted", "evv.transmitted".
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: HIPAA's audit-control requirement covers reads of another user's PHI, not just
    #: writes, so read events are recorded here too and flagged by this column.
    is_phi_access: Mapped[bool] = mapped_column(nullable=False, default=False)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
