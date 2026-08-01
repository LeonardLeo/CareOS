"""Compliance-exception queue.

The rules engine already writes to `compliance_exception`, and the EVV worker escalates
exhausted transmissions there, but nothing could read the queue back. That made the table a
write-only sink — findings were recorded and then invisible, which is worse than not
recording them, because it looks like coverage.

`09_UX_Design_and_User_Flows.md` principle 3 puts exception queues in front of schedulers as
their default view, so this is the read side of that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.audit import AuditAction, record_audit
from careos.core.errors import ConflictError, NotFoundError
from careos.core.security import Principal
from careos.modules.scheduling.models import ComplianceException

#: Severity order for the queue. Critical first — these block billing or mean a caregiver
#: cannot legally work — then warning, then info.
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


@dataclass(slots=True)
class ExceptionSummary:
    total_open: int
    by_severity: dict[str, int]


async def list_exceptions(
    session: AsyncSession,
    *,
    include_resolved: bool = False,
    severity: str | None = None,
    limit: int = 200,
) -> list[ComplianceException]:
    """Open exceptions, most severe first, then oldest first within a severity.

    Oldest-first within a band on purpose: an exception that has sat unresolved for a week
    is a worse problem than one raised an hour ago, and a newest-first queue buries it.
    """
    query = select(ComplianceException)
    if not include_resolved:
        query = query.where(ComplianceException.resolved_at.is_(None))
    if severity:
        query = query.where(ComplianceException.severity == severity)

    rows = (await session.execute(query.limit(limit))).scalars().all()
    return sorted(
        rows,
        key=lambda e: (_SEVERITY_RANK.get(e.severity, 9), e.created_at),
    )


async def summarize(session: AsyncSession) -> ExceptionSummary:
    rows = (
        await session.execute(
            select(ComplianceException.severity, func.count())
            .where(ComplianceException.resolved_at.is_(None))
            .group_by(ComplianceException.severity)
        )
    ).all()
    by_severity = {row[0]: row[1] for row in rows}
    return ExceptionSummary(total_open=sum(by_severity.values()), by_severity=by_severity)


async def resolve_exception(
    session: AsyncSession,
    *,
    principal: Principal,
    exception_id: uuid.UUID,
    note: str | None = None,
) -> ComplianceException:
    """Mark an exception resolved.

    Resolution is an audited act by a named person, not a silent dismissal: someone is
    asserting the underlying problem is dealt with, and an auditor may later ask who.
    """
    exception = await session.get(ComplianceException, exception_id)
    if exception is None:
        raise NotFoundError("Compliance exception not found")
    if exception.resolved_at is not None:
        raise ConflictError("This exception is already resolved")

    exception.resolved_at = datetime.now(UTC)
    exception.resolved_by_user_id = principal.user_id
    if note:
        exception.details = {**(exception.details or {}), "resolution_note": note}
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.compliance_exception_resolved,
        entity_type="compliance_exception",
        entity_id=exception.id,
        after_state={"rule_key": exception.rule_key, "note": note},
    )
    return exception
