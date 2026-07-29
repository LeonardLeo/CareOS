"""Clients, care plans, and visit generation (`05_API_Specification.md` Section 4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.api import schemas
from careos.api.deps import db_session
from careos.core.audit import AuditAction, record_audit
from careos.core.crypto import encrypt_field
from careos.core.errors import NotFoundError
from careos.core.rbac import requires
from careos.core.security import Principal
from careos.modules.agency.models import Role
from careos.modules.scheduling import service as scheduling_service
from careos.modules.scheduling.models import CarePlan, Client

router = APIRouter(tags=["clients"])


@router.post("/clients", response_model=schemas.ClientOut, status_code=201)
async def create_client(
    payload: schemas.ClientCreate,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.ClientOut:
    client = Client(
        agency_id=principal.agency_id,
        legal_name=payload.legal_name,
        # DOB and street address are field-encrypted before they reach Postgres
        # (`08_Security_Architecture.md` Section 3). `geo_lat`/`geo_lng` stay in the clear
        # because the geofence rule needs to compute against them.
        dob_encrypted=encrypt_field(payload.dob.isoformat() if payload.dob else None),
        address_encrypted=encrypt_field(payload.address),
        geo_lat=payload.geo_lat,
        geo_lng=payload.geo_lng,
        service_state=payload.service_state,
        primary_payer_type=payload.primary_payer_type,
    )
    session.add(client)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.client_created,
        entity_type="client",
        entity_id=client.id,
        after_state={"legal_name": client.legal_name, "service_state": client.service_state},
    )
    return schemas.ClientOut.model_validate(client)


@router.get("/clients/{client_id}", response_model=schemas.ClientOut)
async def get_client(
    client_id: uuid.UUID,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.ClientOut:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("Client not found")

    # HIPAA's audit-control requirement covers reads of PHI, not only writes
    # (`08_Security_Architecture.md` Section 4), so viewing a client record is itself an
    # audited event.
    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.client_viewed,
        entity_type="client",
        entity_id=client.id,
    )
    return schemas.ClientOut.model_validate(client)


@router.post(
    "/clients/{client_id}/care-plans",
    response_model=schemas.CarePlanOut,
    status_code=201,
)
async def create_care_plan(
    client_id: uuid.UUID,
    payload: schemas.CarePlanCreate,
    principal: Principal = Depends(requires(Role.owner_admin, Role.clinical_supervisor)),
    session: AsyncSession = Depends(db_session),
) -> schemas.CarePlanOut:
    client = await session.get(Client, client_id)
    if client is None:
        raise NotFoundError("Client not found")

    care_plan = CarePlan(
        agency_id=principal.agency_id,
        client_id=client.id,
        authorized_tasks=payload.authorized_tasks,
        visit_frequency_rule=payload.visit_frequency_rule,
        effective_start=payload.effective_start,
        effective_end=payload.effective_end,
        clinical_supervisor_id=payload.clinical_supervisor_id,
        default_service_type_code=payload.default_service_type_code,
    )
    session.add(care_plan)
    await session.flush()

    await record_audit(
        session,
        principal=principal,
        agency_id=principal.agency_id,
        action=AuditAction.care_plan_created,
        entity_type="care_plan",
        entity_id=care_plan.id,
        after_state={
            "client_id": str(client.id),
            "effective_start": payload.effective_start.isoformat(),
        },
    )
    return schemas.CarePlanOut.model_validate(care_plan)


@router.post(
    "/care-plans/{care_plan_id}/generate-visits",
    response_model=list[schemas.VisitOut],
    status_code=201,
)
async def generate_visits(
    care_plan_id: uuid.UUID,
    payload: schemas.GenerateVisitsRequest,
    principal: Principal = Depends(requires(Role.owner_admin, Role.scheduler)),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.VisitOut]:
    """Materialize `scheduled_visit` rows from the plan's recurrence rule.

    Re-running over an overlapping window is safe — visits already generated for the same
    start time are skipped — so no Idempotency-Key is required here. There are no external
    side effects at this point in the flow.
    """
    care_plan = await session.get(CarePlan, care_plan_id)
    if care_plan is None:
        raise NotFoundError("Care plan not found")

    visits = await scheduling_service.generate_visits(
        session,
        principal=principal,
        care_plan=care_plan,
        window=scheduling_service.GenerationWindow(
            start=payload.window_start, end=payload.window_end
        ),
        duration_minutes=payload.duration_minutes,
    )
    return [schemas.VisitOut.model_validate(v) for v in visits]


@router.get("/care-plans/{care_plan_id}", response_model=schemas.CarePlanOut)
async def get_care_plan(
    care_plan_id: uuid.UUID,
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> schemas.CarePlanOut:
    care_plan = await session.get(CarePlan, care_plan_id)
    if care_plan is None:
        raise NotFoundError("Care plan not found")
    return schemas.CarePlanOut.model_validate(care_plan)


@router.get("/clients", response_model=list[schemas.ClientOut])
async def list_clients(
    principal: Principal = Depends(
        requires(Role.owner_admin, Role.scheduler, Role.clinical_supervisor, Role.auditor)
    ),
    session: AsyncSession = Depends(db_session),
) -> list[schemas.ClientOut]:
    clients = (await session.execute(select(Client).order_by(Client.legal_name))).scalars().all()
    return [schemas.ClientOut.model_validate(c) for c in clients]
