"""Agency data export (`06_Compliance_and_Regulatory_Requirements.md` Section 8).

The export is the largest single disclosure this system can perform: one request produces a
plaintext PHI extract of everything an agency holds. Two properties matter more than whether
the ZIP opens.

**It must contain exactly one agency's data.** Every other endpoint returns a handful of rows,
so a leak is a leak of a handful. This one returns all of them at once, which makes it the
worst possible place for the tenant scoping to be wrong — and the reads go through RLS rather
than a `WHERE agency_id = ...` clause precisely so that being right does not depend on
remembering.

**It must be complete.** An export that quietly omits a table is worse than a failed one: the
agency finds out after they have migrated. Completeness is derived from the schema rather than
from a hand-written list, and the test below is what holds that derivation honest.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from careos.db.models import TENANT_ROOT_TABLE, TENANT_TABLES
from careos.db.session import tenant_session
from careos.modules.agency.models import Role
from careos.modules.audit.models import AuditLog
from careos.modules.reporting import export_service
from tests.conftest import TenantFixture, make_client_with_plan


async def _export(client, tenant: TenantFixture) -> zipfile.ZipFile:
    response = await client.post(
        f"/v1/agencies/{tenant.agency_id}/export", headers=tenant.headers(Role.owner_admin)
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def _rows(archive: zipfile.ZipFile, table: str) -> list[dict[str, str]]:
    with archive.open(f"{table}.csv") as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8")))


# --- Completeness ---------------------------------------------------------------------------


def test_every_tenant_table_is_either_exported_or_excluded_with_a_reason() -> None:
    """The guard that keeps the export complete as the schema grows.

    A table added next year is exported automatically because the list is derived from the
    metadata. This asserts nobody has quietly broken that derivation — and that anything left
    out was left out on purpose, with the reason written down next to it.
    """
    exported = set(export_service.exported_table_names())
    excluded = set(export_service.EXCLUDED_TABLES)

    uncovered = set(TENANT_TABLES) - exported - excluded
    assert uncovered == set(), (
        f"tenant tables neither exported nor deliberately excluded: {sorted(uncovered)}. "
        "An agency's export would silently be missing them."
    )
    assert exported & excluded == set(), "a table cannot be both exported and excluded"
    assert TENANT_ROOT_TABLE in exported, "the agency's own row belongs in its export"
    for table, reason in export_service.EXCLUDED_TABLES.items():
        assert len(reason) > 10, f"{table} is excluded without a stated reason"


async def test_the_archive_contains_a_file_for_every_exported_table(
    client, tenant_a: TenantFixture
) -> None:
    """Including the empty ones.

    A table with only a header is a feature the agency has not used. Omitting it would make an
    unused feature and a failed export look the same from outside.
    """
    archive = await _export(client, tenant_a)
    names = set(archive.namelist())
    for table in export_service.exported_table_names():
        assert f"{table}.csv" in names, f"{table} missing from the archive"
    assert "manifest.json" in names
    assert "README.txt" in names


# --- Tenant isolation -----------------------------------------------------------------------


async def test_an_export_contains_no_other_agency_s_data(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """The property this endpoint most needs to be right about.

    Both agencies get a client with a distinctive name; A's export must contain A's and not
    B's. Every file in the archive is searched, not just `client.csv`, so a leak into a table
    this test does not know to name still fails.

    Searched **decompressed**. The first version of this scanned the raw response bytes, which
    is worse than useless: the archive is deflated, so no plaintext appears in it and the
    "B's name is absent" assertion passed no matter what was inside. It was caught only because
    the paired positive assertion — that A's own name *is* present — failed for the same
    reason. A negative assertion that cannot fail is how a test becomes a comfort.
    """
    marker_a = f"Alpha Export Client {uuid.uuid4().hex[:8]}"
    marker_b = f"Beta Secret Client {uuid.uuid4().hex[:8]}"
    await make_client_with_plan(tenant_a, legal_name=marker_a)
    await make_client_with_plan(tenant_b, legal_name=marker_b)

    archive = await _export(client, tenant_a)
    contents = {name: archive.read(name).decode("utf-8") for name in archive.namelist()}
    whole = "\n".join(contents.values())

    assert marker_a in whole, "the agency's own client is missing from its export"
    leaked = [name for name, text in contents.items() if marker_b in text]
    assert leaked == [], f"another agency's client name appears in {leaked}"

    for row in _rows(archive, "client"):
        assert row["agency_id"] == str(tenant_a.agency_id)
    assert str(tenant_b.agency_id) not in whole, "another agency's id appears in this export"


async def test_an_owner_cannot_export_another_agency(
    client, tenant_a: TenantFixture, tenant_b: TenantFixture
) -> None:
    """Naming someone else's agency in the path must not widen what you get."""
    response = await client.post(
        f"/v1/agencies/{tenant_b.agency_id}/export",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "role", [Role.scheduler, Role.clinical_supervisor, Role.auditor, Role.caregiver]
)
async def test_only_an_owner_admin_can_export(client, tenant_a: TenantFixture, role: Role) -> None:
    """A bulk PHI extract is not a read every role should be able to perform.

    The auditor is included deliberately: read-only tenant-wide access is still not a licence
    to walk out with the whole data set in one file.
    """
    response = await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/export", headers=tenant_a.headers(role)
    )
    assert response.status_code == 403


# --- Content --------------------------------------------------------------------------------


async def test_encrypted_fields_are_exported_readable(client, tenant_a: TenantFixture) -> None:
    """Ciphertext keyed to a secret the agency does not hold is not portability.

    The column loses its `_encrypted` suffix on the way out, so the header says `dob` rather
    than `dob_encrypted` — the name a receiving system would expect.
    """
    legal_name = f"Readable Export {uuid.uuid4().hex[:8]}"
    await make_client_with_plan(
        tenant_a,
        legal_name=legal_name,
        dob="1950-01-01",
        address="412 Ashbury Lane, Rochester NY",
    )

    archive = await _export(client, tenant_a)
    rows = _rows(archive, "client")
    exported = next(r for r in rows if r["legal_name"] == legal_name)

    assert "dob_encrypted" not in exported
    assert "address_encrypted" not in exported
    # The fixture writes these through the same encryption path the API uses.
    assert exported["dob"] == "1950-01-01", exported
    assert "Rochester" in exported["address"], exported


async def test_json_columns_are_exported_as_json(client, tenant_a: TenantFixture) -> None:
    """Not as a Python repr, which nothing else can parse.

    `str({"a": 1})` gives single quotes, and `None` where JSON needs `null`. An export that
    needs a Python interpreter to read is not a standard format.
    """
    await make_client_with_plan(tenant_a)
    archive = await _export(client, tenant_a)
    plans = _rows(archive, "care_plan")
    assert plans, "the fixture should have produced a care plan"
    tasks = json.loads(plans[0]["authorized_tasks"])
    assert isinstance(tasks, list)
    assert tasks and "code" in tasks[0]


async def test_the_manifest_and_readme_say_what_is_in_the_file(
    client, tenant_a: TenantFixture
) -> None:
    """Whoever opens the archive may not be an engineer, and it contains PHI."""
    archive = await _export(client, tenant_a)
    manifest = json.loads(archive.read("manifest.json"))

    assert manifest["agency_id"] == str(tenant_a.agency_id)
    assert manifest["format_version"] == export_service.EXPORT_FORMAT_VERSION
    assert set(manifest["row_counts"]) == set(export_service.exported_table_names())
    assert manifest["excluded_tables"] == export_service.EXCLUDED_TABLES

    readme = archive.read("README.txt").decode()
    assert "PROTECTED HEALTH INFORMATION" in readme
    assert "_encrypted" in readme, "the column renaming has to be explained somewhere"


# --- The record that it happened ------------------------------------------------------------


async def test_an_export_is_audited_with_its_size(client, tenant_a: TenantFixture) -> None:
    """An auditor's question is "what left, and when" — so the row counts are in the entry.

    Without them the audit log says an export happened but not whether it covered three
    clients or thirty thousand.
    """
    from careos.core.audit import AuditAction

    await make_client_with_plan(tenant_a)
    await _export(client, tenant_a)

    async with tenant_session(tenant_a.agency_id) as session:
        entries = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.agency_data_exported)
                )
            )
            .scalars()
            .all()
        )

    assert len(entries) == 1
    after = entries[0].after_state or {}
    assert after["total_rows"] > 0
    assert after["row_counts"]["client"] >= 1
    assert after["bytes"] > 0
    assert entries[0].actor_user_id == tenant_a.owner_id


async def test_a_refused_export_writes_no_audit_row_and_no_archive(
    client, tenant_a: TenantFixture, monkeypatch
) -> None:
    """Refusing above the size limit must not look like an export that happened.

    The archive is built in memory, so the ceiling is real. What matters is that crossing it
    produces a clear 413 rather than an out-of-memory kill that takes every other request on
    the instance down with it — and that nothing is recorded as disclosed, because nothing was.
    """
    from careos.core.audit import AuditAction

    monkeypatch.setattr(export_service, "MAX_EXPORT_ROWS", 0)

    response = await client.post(
        f"/v1/agencies/{tenant_a.agency_id}/export",
        headers=tenant_a.headers(Role.owner_admin),
    )
    assert response.status_code == 413
    body = response.json()["error"]
    assert body["code"] == "EXPORT_TOO_LARGE"
    assert body["details"]["limit"] == 0

    async with tenant_session(tenant_a.agency_id) as session:
        entries = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == AuditAction.agency_data_exported)
                )
            )
            .scalars()
            .all()
        )
    assert entries == []
