"""Agency data export (`06_Compliance_and_Regulatory_Requirements.md` Section 8).

That section asks for export tooling "as a first-class feature, not an afterthought, both as
a compliance safeguard and a competitive/trust signal against lock-in concerns", and the PRD's
non-functional table requires an agency to be able to export its full data set — clients,
caregivers, visits, claims — in a standard format.

Three decisions carry most of the weight.

**Completeness is derived, not curated.** The table list comes from `TENANT_TABLES`, which is
itself derived from the SQLAlchemy metadata. A table added next year is exported without anyone
remembering to add it here, and a table deliberately left out has to be named in
`EXCLUDED_TABLES` with a reason. A hand-written list of tables to export is a list that silently
goes stale, and the failure is invisible: the export succeeds, and the agency finds out what was
missing after they have migrated.

**Encrypted columns are decrypted.** `dob_encrypted`, `address_encrypted`, and `tax_id_encrypted`
would otherwise leave as base64 ciphertext keyed to a secret the agency does not have, which is
not portability — it is the appearance of it. Detected by the `_encrypted` suffix rather than
listed, for the same reason as above. The consequence is that an export file is a plaintext PHI
extract, and everything about how this endpoint is guarded follows from that: owner-admin only,
audited with row counts, and never written to disk on the server.

**It refuses rather than degrades.** The archive is built in memory, so a large agency would
otherwise trade a clear failure for an out-of-memory kill that takes every other request on the
instance with it. `MAX_EXPORT_ROWS` is checked first and the caller is told plainly. Streaming
was the obvious alternative and is worse here: a response whose body is generated after the
status code has been sent cannot report a mid-stream failure — which is the exact defect this
codebase just spent an increment removing from the write path.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from careos.core.crypto import decrypt_field
from careos.core.errors import CareOSError
from careos.db.models import TENANT_ROOT_TABLE, TENANT_TABLES, Base

#: Tenant tables deliberately left out of an export, each with the reason it is not the
#: agency's data to take with them. Every other tenant table is exported; the test that pairs
#: with this asserts the two sets cover everything, so a new table cannot slip through either
#: side unnoticed.
EXCLUDED_TABLES: dict[str, str] = {
    # A replay cache for in-flight requests, holding stored response bodies keyed by
    # Idempotency-Key. Operational state with a short life, not a record of care, and it
    # would duplicate PHI already present in its proper table.
    "idempotency_key": "request replay cache, not agency data",
}

#: Above this many rows the export is refused rather than attempted. The archive is built in
#: memory; the honest failure is a 4xx that names the limit, not an OOM that takes the instance
#: down with every other request on it.
MAX_EXPORT_ROWS = 500_000

#: Suffix marking a column stored under field-level encryption. Exported decrypted, under the
#: name with the suffix removed.
_ENCRYPTED_SUFFIX = "_encrypted"

EXPORT_FORMAT_VERSION = 1


class ExportTooLargeError(CareOSError):
    """The agency's data set exceeds what a synchronous export can safely build."""

    status_code = 413
    code = "EXPORT_TOO_LARGE"


@dataclass
class ExportResult:
    archive: bytes
    #: Row count per table, in the manifest and in the audit entry — the latter is what makes
    #: "how much PHI left the system, and when" an answerable question.
    row_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return sum(self.row_counts.values())


def exported_table_names() -> tuple[str, ...]:
    """Every tenant table an export includes, plus the agency row itself."""
    return tuple(
        sorted({TENANT_ROOT_TABLE, *(t for t in TENANT_TABLES if t not in EXCLUDED_TABLES)})
    )


def _export_column_name(column_name: str) -> str:
    return (
        column_name[: -len(_ENCRYPTED_SUFFIX)]
        if column_name.endswith(_ENCRYPTED_SUFFIX)
        else column_name
    )


def _render(value: Any, *, encrypted: bool) -> str:
    """One database value as a CSV cell.

    JSON columns are re-serialized rather than str()'d: Python's repr of a dict uses single
    quotes and `None`, which no other system parses. An export that needs a Python interpreter
    to read is not a standard format.
    """
    if encrypted:
        value = decrypt_field(value)
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        # A non-encrypted binary column. Nothing has one today; if one appears, a readable
        # marker beats a mojibake cell that looks like data.
        return f"<{len(value)} bytes, not exported>"
    return str(value)


async def _count_rows(session: AsyncSession, table_names: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in table_names:
        table = Base.metadata.tables[name]
        result = await session.execute(select(func.count()).select_from(table))
        counts[name] = int(result.scalar_one())
    return counts


async def build_export(
    session: AsyncSession, *, agency_id: uuid.UUID, generated_by: str
) -> ExportResult:
    """Build a ZIP of one CSV per table, plus a manifest.

    Every read goes through the caller's tenant-scoped session, so Row-Level Security decides
    what is in the file. That is deliberate: an export that queried with an explicit
    `WHERE agency_id = ...` would be one forgotten clause away from handing an agency someone
    else's clients, and the whole point of enforcing isolation in the database is not to depend
    on remembering.
    """
    tables = exported_table_names()

    counts = await _count_rows(session, tables)
    total = sum(counts.values())
    if total > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(
            f"This agency has {total:,} rows, above the {MAX_EXPORT_ROWS:,} an immediate "
            "export can build. Contact support for a staged export.",
            details={"total_rows": total, "limit": MAX_EXPORT_ROWS},
        )

    buffer = io.BytesIO()
    written: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in tables:
            table = Base.metadata.tables[name]
            columns = list(table.columns)
            header = [_export_column_name(c.name) for c in columns]
            encrypted_flags = [c.name.endswith(_ENCRYPTED_SUFFIX) for c in columns]

            text = io.StringIO(newline="")
            writer = csv.writer(text, lineterminator="\n")
            writer.writerow(header)

            rows = 0
            result = await session.execute(select(table))
            for row in result:
                writer.writerow(
                    [
                        _render(value, encrypted=is_encrypted)
                        for value, is_encrypted in zip(row, encrypted_flags, strict=True)
                    ]
                )
                rows += 1

            written[name] = rows
            archive.writestr(f"{name}.csv", text.getvalue())

        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format_version": EXPORT_FORMAT_VERSION,
                    "agency_id": str(agency_id),
                    "generated_at": datetime.now(UTC).isoformat(),
                    "generated_by": generated_by,
                    "row_counts": written,
                    "excluded_tables": EXCLUDED_TABLES,
                    "decrypted_columns_note": (
                        "Columns stored encrypted at rest are exported in plaintext, under "
                        "their name without the _encrypted suffix. This archive therefore "
                        "contains PHI and should be handled accordingly."
                    ),
                },
                indent=2,
                sort_keys=True,
            ),
        )
        archive.writestr("README.txt", _readme(agency_id, written))

    return ExportResult(archive=buffer.getvalue(), row_counts=written)


def _readme(agency_id: uuid.UUID, counts: dict[str, int]) -> str:
    """Plain text for whoever opens the archive, who may not be an engineer.

    The two things they need to know before anything else are that it contains PHI and that
    the empty files are empty because the feature is unused, not because the export failed.
    """
    lines = [
        "CareOS data export",
        "==================",
        "",
        f"Agency: {agency_id}",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Format version: {EXPORT_FORMAT_VERSION}",
        "",
        "THIS ARCHIVE CONTAINS PROTECTED HEALTH INFORMATION.",
        "Client names, dates of birth, and home addresses are included in readable form, as",
        "are caregiver tax identifiers. Store and transfer it accordingly.",
        "",
        "One CSV per table, named for the table. Columns keep their database names, except",
        "that fields encrypted at rest are exported decrypted under the name without the",
        "'_encrypted' suffix — dob_encrypted becomes dob, and so on.",
        "",
        "Identifiers are UUIDs and are stable across this archive, so rows can be joined",
        "back together: scheduled_visit.client_id matches client.id, and so on.",
        "",
        "A table with only a header row is a feature this agency has not used. It is included",
        "so that the export is the same shape every time.",
        "",
        "Row counts:",
    ]
    lines.extend(f"  {name:<32} {count:>9,}" for name, count in sorted(counts.items()))
    return "\n".join(lines) + "\n"
