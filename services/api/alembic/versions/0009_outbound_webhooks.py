"""Outbound webhook subscriptions and deliveries (`05_API_Specification.md` Section 7).

Two tables rather than one. A subscription is configuration an agency owns and edits; a
delivery is an immutable attempt record. Keeping the attempt count on the subscription would
mean one receiver's outage rewriting a row that an administrator is also editing, and would
leave no answer to "was this specific event delivered".

Both are tenant-scoped and both get RLS, like every other tenant table — a webhook queue is a
place cross-tenant leakage would be especially quiet, since nobody reads it by hand.

Revision ID: 0009_outbound_webhooks
Revises: 0008_session_revocation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from careos.db.rls import standard_tenant_table

revision: str = "0009_outbound_webhooks"
down_revision: str | None = "0008_session_revocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTS = (
    "background_check.completed",
    "evv.transmission_acknowledged",
    "evv.transmission_rejected",
    "claim.status_changed",
    "credential.expiring_soon",
)


def upgrade() -> None:
    op.create_table(
        "webhook_subscription",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("signing_secret", sa.Text(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "status",
            sa.Enum("active", "paused", "disabled", name="webhook_subscription_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_webhook_subscription_agency", "webhook_subscription", ["agency_id", "status"]
    )

    op.create_table(
        "webhook_delivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agency.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("webhook_subscription.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.Enum(*_EVENTS, name="webhook_event"), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "delivered", "failing", "abandoned", name="webhook_delivery_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_webhook_delivery_due", "webhook_delivery", ["agency_id", "status", "next_attempt_at"]
    )
    op.create_index("ix_webhook_delivery_subscription", "webhook_delivery", ["subscription_id"])

    for statement in standard_tenant_table("webhook_subscription"):
        op.execute(statement)
    for statement in standard_tenant_table("webhook_delivery"):
        op.execute(statement)


def downgrade() -> None:
    # DESTRUCTIVE-MIGRATION-APPROVED: reviewer=build-increment-16.
    #
    # Drops queued-but-undelivered webhooks and the record of what was delivered. Assessed as
    # acceptable only because both tables are new in this revision — a downgrade past it
    # necessarily returns to code that never enqueued anything. Receivers integrating against
    # this would need to reconcile from the API rather than from replayed events.
    op.drop_table("webhook_delivery")
    op.drop_table("webhook_subscription")
    sa.Enum(name="webhook_delivery_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="webhook_event").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="webhook_subscription_status").drop(op.get_bind(), checkfirst=True)
