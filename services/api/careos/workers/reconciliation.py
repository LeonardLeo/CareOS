"""The reconciliation pass, in the shape the runner expects.

Daily rather than every few minutes. Every divergence it reports is defined by something
*not* having happened for at least a day, so a tighter schedule would re-derive the same
answer and re-open the same exceptions without any of them being newer.

Kept separate from `evv_transmission` although both concern EVV, because they answer opposite
questions. Transmission asks "what should I send next?" and acts on individual records.
Reconciliation asks "is what I think I sent the same as what was received?" and only
ever looks. Merging them would give the auditing half a write path into the thing it audits.
"""

from __future__ import annotations

import uuid

import structlog

from careos.db.session import tenant_session
from careos.modules.compliance_rules import reconciliation

logger = structlog.get_logger(__name__)


async def reconcile_agency(agency_id: uuid.UUID) -> reconciliation.ReconciliationRun:
    """Reconcile one agency's delivered visits against their EVV records."""
    async with tenant_session(agency_id) as session:
        run = await reconciliation.reconcile(session, agency_id=agency_id)

    if run.divergences or run.resolved:
        logger.info(
            "evv.reconciled",
            agency_id=str(agency_id),
            visits_examined=run.visits_examined,
            divergences=len(run.divergences),
            by_rule=run.by_rule(),
            raised=run.raised,
            resolved=run.resolved,
        )
    return run
