"""Audit trail writer — the one way anything gets into `audit_log`.

`08_Security_Architecture.md` Section 4 requires an attributable, immutable record of every
clinically or financially significant action, plus PHI reads. Two design choices make that
hold in practice:

**The audit row is written in the caller's transaction.** It is not queued, not emitted to a
log shipper, not written by a background worker. If the business change commits, its audit
row commits with it; if the change rolls back, so does the row. There is no window in which
one exists without the other.

**Actions are declared, not free-typed.** `AuditAction` is a closed set, so a typo cannot
quietly produce an action name that later audit queries filter out and nobody notices.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.context import current_request_id, current_source_ip
from careos.core.security import Principal
from careos.modules.audit.models import AuditLog


class AuditAction(enum.StrEnum):
    """Auditable actions. Add here before use; do not pass a bare string."""

    agency_created = "agency.created"
    agency_updated = "agency.updated"
    user_invited = "user.invited"
    user_role_changed = "user.role_changed"
    user_login_succeeded = "user.login_succeeded"
    user_login_failed = "user.login_failed"

    client_created = "client.created"
    client_viewed = "client.viewed"
    care_plan_created = "care_plan.created"
    care_plan_updated = "care_plan.updated"

    visits_generated = "visit.generated"
    visit_assigned = "visit.assigned"
    visit_clock_in = "visit.clock_in"
    visit_clock_out = "visit.clock_out"
    #: A caregiver opening their own schedule. It returns client names and addresses, so it is
    #: a PHI read even though the caregiver is entitled to see it for their assigned visits.
    caregiver_schedule_viewed = "visit.caregiver_schedule_viewed"

    evv_transmitted = "evv.transmitted"
    evv_acknowledged = "evv.acknowledged"
    evv_rejected = "evv.rejected"

    caregiver_created = "caregiver.created"
    credential_added = "credential.added"
    credential_verified = "credential.verified"
    exclusion_check_recorded = "caregiver.exclusion_check_recorded"

    job_posting_created = "job_posting.created"
    applicant_ingested = "applicant.ingested"
    applicants_ranked = "applicant.ranked"
    applicant_stage_changed = "applicant.stage_changed"
    applicant_hired = "applicant.hired"
    #: Recorded when a scheduler is shown AI-ranked caregiver suggestions. Ranking influences
    #: who gets offered work, so the suggestion event is auditable in its own right.
    shift_suggestions_generated = "visit.suggestions_generated"

    compliance_exception_raised = "compliance_exception.raised"
    compliance_exception_resolved = "compliance_exception.resolved"


#: Actions that constitute access to another person's PHI and are therefore recorded even
#: though they change nothing — HIPAA's audit-control requirement covers reads.
_PHI_READ_ACTIONS: frozenset[AuditAction] = frozenset(
    {AuditAction.client_viewed, AuditAction.caregiver_schedule_viewed}
)


async def record_audit(
    session: AsyncSession,
    *,
    principal: Principal | None,
    agency_id: uuid.UUID,
    action: AuditAction,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one audit row to the caller's open transaction.

    `principal` may be None only for pre-authentication events such as a failed login,
    where there is no established actor to attribute the action to.
    """
    entry = AuditLog(
        agency_id=agency_id,
        actor_user_id=principal.user_id if principal else None,
        action=action.value,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        is_phi_access=action in _PHI_READ_ACTIONS,
        request_id=current_request_id(),
        source_ip=current_source_ip(),
    )
    session.add(entry)
    # Flush rather than commit: the row must land in the same transaction as the change it
    # describes, and committing here would break that atomicity.
    await session.flush()
    return entry


def diff_state(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Reduce a before/after pair to just the fields that changed.

    Audit rows on wide entities are mostly noise otherwise, and noise is what stops people
    reading audit logs during an investigation.
    """
    changed = {}
    for key in set(before) | set(after):
        old, new = before.get(key), after.get(key)
        if old != new:
            changed[key] = {"before": old, "after": new}
    return changed
