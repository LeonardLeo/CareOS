"""Shared test fixtures.

Tests run against a real PostgreSQL database, not SQLite or mocks. That is not incidental:
the isolation guarantees this system depends on are Row-Level Security policies, `FORCE ROW
LEVEL SECURITY`, and role grants — all of which exist only in Postgres. A test suite that
stubbed the database would verify the application's intentions while proving nothing about
the mechanism that actually enforces them.

Every test connects as `careos_app`, the same unprivileged role production uses, so the
policies bind here exactly as they do in production.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Set before any careos module imports, because Settings is read at import time in places.
os.environ.setdefault("CAREOS_ENVIRONMENT", "test")

TEST_DB = os.environ.get("CAREOS_TEST_DB", "careos_test")
PG_HOST = os.environ.get("PGHOST", "localhost")
PG_PORT = os.environ.get("PGPORT", "5432")
SUPERUSER = os.environ.get("PGSUPERUSER", "postgres")
SUPERPASS = os.environ.get("PGPASSWORD", "postgres")

os.environ["CAREOS_DATABASE_URL"] = (
    f"postgresql+asyncpg://careos_app:careos_app@{PG_HOST}:{PG_PORT}/{TEST_DB}"
)
os.environ["CAREOS_PRIVILEGED_DATABASE_URL"] = (
    f"postgresql+asyncpg://careos_auth:careos_auth@{PG_HOST}:{PG_PORT}/{TEST_DB}"
)
os.environ["CAREOS_MIGRATION_DATABASE_URL"] = (
    f"postgresql+asyncpg://{SUPERUSER}:{SUPERPASS}@{PG_HOST}:{PG_PORT}/{TEST_DB}"
)

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from careos.core.security import Principal, create_token, hash_password  # noqa: E402
from careos.db.session import (  # noqa: E402
    dispose_engines,
    privileged_session,
    tenant_session,
)
from careos.main import create_app  # noqa: E402
from careos.modules.agency.models import Agency, AppUser, Role, UserStatus  # noqa: E402
from careos.modules.credentialing.models import (  # noqa: E402
    Caregiver,
    EmploymentStatus,
    ExclusionCheckStatus,
)
from careos.modules.reference.models import (  # noqa: E402
    EVVAggregatorRef,
    EVVModel,
    PayerServiceCodeRef,
)
from careos.modules.scheduling.models import CarePlan, Client  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]


def _psql(sql: str, *, database: str = "postgres") -> None:
    subprocess.run(
        [
            "psql",
            "-h",
            PG_HOST,
            "-p",
            PG_PORT,
            "-U",
            SUPERUSER,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        env={**os.environ, "PGPASSWORD": SUPERPASS},
    )


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Build the test database from scratch, then migrate it.

    Recreated per session rather than truncated, so a migration that only works against an
    already-populated database cannot pass here.
    """
    _psql(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    _psql(f"CREATE DATABASE {TEST_DB}")

    bootstrap = API_ROOT / "scripts" / "bootstrap_db.sql"
    subprocess.run(
        [
            "psql",
            "-h",
            PG_HOST,
            "-p",
            PG_PORT,
            "-U",
            SUPERUSER,
            "-d",
            TEST_DB,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-f",
            str(bootstrap),
        ],
        check=True,
        capture_output=True,
        env={**os.environ, "PGPASSWORD": SUPERPASS},
    )
    subprocess.run(
        [str(API_ROOT / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        check=True,
        capture_output=True,
        cwd=API_ROOT,
        env=os.environ,
    )


@pytest.fixture(autouse=True)
async def _clean_tables(database: None) -> AsyncIterator[None]:
    """Truncate tenant data between tests, leaving schema and reference data intact."""
    yield
    from careos.db.models import RLS_TABLES

    # TRUNCATE runs as superuser: the app role deliberately cannot delete audit rows.
    tables = ", ".join(f'"{t}"' for t in RLS_TABLES)
    _psql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE", database=TEST_DB)


@pytest.fixture(scope="session", autouse=True)
async def _dispose() -> AsyncIterator[None]:
    yield
    await dispose_engines()


@pytest.fixture(scope="session", autouse=True)
def reference_data(database: None) -> None:
    """Seed the global reference rows the scheduling tests depend on.

    Seeded as superuser, not through the application session, because neither `careos_app`
    nor `careos_auth` holds write access to reference tables — they are migration/seed-owned
    by design. Attempting this through the app role fails, which is the intended behaviour.

    Session-scoped and never truncated, so reference data behaves in tests the way it does
    in production: present before any tenant exists.
    """
    _psql(
        """
        INSERT INTO evv_aggregator_ref
            (state_code, adapter_key, evv_model, aggregator_name, connection_config,
             sandbox_validated, created_at, updated_at)
        VALUES ('NY', 'loopback', 'state_mandated_vendor', 'Loopback (test)', '{}'::jsonb,
                true, now(), now())
        ON CONFLICT (state_code) DO NOTHING;

        INSERT INTO payer_service_code_ref
            (code, state_code, payer_type, display_name, unit_minutes, billing_rules,
             requires_evv, created_at, updated_at)
        VALUES ('T1019', 'NY', 'medicaid_waiver', 'Personal care services, per 15 min',
                15, '{}'::jsonb, true, now(), now())
        ON CONFLICT (code, state_code, payer_type) DO NOTHING;

        INSERT INTO credential_type_ref
            (code, display_name, state_requirements, blocks_scheduling_on_expiry,
             created_at, updated_at)
        VALUES ('HHA', 'Home Health Aide', '{}'::jsonb, true, now(), now()),
               ('CNA', 'Certified Nursing Assistant', '{}'::jsonb, true, now(), now()),
               ('CPR', 'CPR Certification', '{}'::jsonb, false, now(), now())
        ON CONFLICT (code) DO NOTHING;
        """,
        database=TEST_DB,
    )


class TenantFixture:
    """One tenant plus the handles tests need to act as it."""

    def __init__(self, agency: Agency, owner: AppUser, caregiver: Caregiver | None = None) -> None:
        self.agency = agency
        self.agency_id = agency.id
        self.owner = owner
        self.owner_id = owner.id
        self.caregiver = caregiver
        self.caregiver_id = caregiver.id if caregiver else None

    def principal(self, role: Role = Role.owner_admin) -> Principal:
        return Principal(
            user_id=self.owner_id,
            agency_id=self.agency_id,
            role=role,
            caregiver_id=self.caregiver_id,
        )

    def token(self, role: Role = Role.owner_admin, user_id: uuid.UUID | None = None) -> str:
        return create_token(
            user_id=user_id or self.owner_id,
            agency_id=self.agency_id,
            role=role,
            token_type="access",
            caregiver_id=self.caregiver_id,
        )

    def headers(self, role: Role = Role.owner_admin) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(role)}"}


async def _make_tenant(name: str, *, with_caregiver: bool = True) -> TenantFixture:
    async with privileged_session() as session:
        agency = Agency(
            legal_name=name,
            service_states=["NY"],
            service_lines=["home_care"],
            accepted_payer_types=["medicaid_waiver"],
        )
        session.add(agency)
        await session.flush()

        owner = AppUser(
            agency_id=agency.id,
            role=Role.owner_admin,
            email=f"owner+{uuid.uuid4().hex[:8]}@{name.lower().replace(' ', '')}.test",
            password_hash=hash_password("correct-horse-battery-staple"),
            status=UserStatus.active,
        )
        session.add(owner)
        await session.flush()
        agency_id, owner_id = agency.id, owner.id
        owner_email = owner.email

    caregiver_id = None
    if with_caregiver:
        async with tenant_session(agency_id) as session:
            caregiver = Caregiver(
                agency_id=agency_id,
                legal_name=f"{name} Caregiver",
                employment_status=EmploymentStatus.active,
                exclusion_check_status=ExclusionCheckStatus.cleared,
                exclusion_checked_at=datetime.now(UTC),
                geo_lat=40.7128,
                geo_lng=-74.0060,
            )
            session.add(caregiver)
            await session.flush()
            caregiver_id = caregiver.id

    # Rebuild detached stand-ins so tests can read ids without a live session.
    agency_stub = Agency(
        legal_name=name,
        service_states=["NY"],
        service_lines=["home_care"],
        accepted_payer_types=["medicaid_waiver"],
    )
    agency_stub.id = agency_id
    owner_stub = AppUser(
        agency_id=agency_id, role=Role.owner_admin, email=owner_email, status=UserStatus.active
    )
    owner_stub.id = owner_id
    caregiver_stub = None
    if caregiver_id:
        caregiver_stub = Caregiver(
            agency_id=agency_id,
            legal_name=f"{name} Caregiver",
            employment_status=EmploymentStatus.active,
            exclusion_check_status=ExclusionCheckStatus.cleared,
        )
        caregiver_stub.id = caregiver_id

    return TenantFixture(agency_stub, owner_stub, caregiver_stub)


@pytest.fixture
async def tenant_a(database: None) -> TenantFixture:
    return await _make_tenant("Alpha Home Care")


@pytest.fixture
async def tenant_b(database: None) -> TenantFixture:
    return await _make_tenant("Beta Home Care")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def app():
    return create_app()


async def make_client_with_plan(
    tenant: TenantFixture,
    *,
    service_state: str = "NY",
    payer_type: str = "medicaid_waiver",
    service_code: str | None = "T1019",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a client and a weekday care plan, returning their ids."""
    async with tenant_session(tenant.agency_id) as session:
        care_client = Client(
            agency_id=tenant.agency_id,
            legal_name="Test Client",
            service_state=service_state,
            primary_payer_type=payer_type,
            geo_lat=40.7128,
            geo_lng=-74.0060,
        )
        session.add(care_client)
        await session.flush()

        plan = CarePlan(
            agency_id=tenant.agency_id,
            client_id=care_client.id,
            authorized_tasks=[{"code": "bathing", "label": "Assist with bathing"}],
            visit_frequency_rule={"rrule": "FREQ=DAILY;COUNT=3", "start_hour": 9},
            effective_start=(datetime.now(UTC) - timedelta(days=1)).date(),
            default_service_type_code=service_code,
        )
        session.add(plan)
        await session.flush()
        return care_client.id, plan.id


__all__ = [
    "AsyncSession",
    "EVVAggregatorRef",
    "EVVModel",
    "PayerServiceCodeRef",
    "TenantFixture",
    "make_client_with_plan",
]
