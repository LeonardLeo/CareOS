"""Single import point that registers every model on ``Base.metadata``.

Alembic autogenerate and the test harness both import this module. A model that is not
reachable from here is invisible to migrations, so new model modules must be added below.
"""

from __future__ import annotations

from careos.db.base import Base
from careos.modules.agency import idempotency_models
from careos.modules.agency import models as agency_models
from careos.modules.audit import models as audit_models
from careos.modules.billing import models as billing_models
from careos.modules.credentialing import models as credentialing_models
from careos.modules.documentation import models as documentation_models
from careos.modules.recruiting import models as recruiting_models
from careos.modules.reference import models as reference_models
from careos.modules.scheduling import models as scheduling_models

#: Tables that are global reference data — no `agency_id`, no RLS policy.
GLOBAL_TABLES: frozenset[str] = frozenset(
    {"credential_type_ref", "evv_aggregator_ref", "payer_service_code_ref", "alembic_version"}
)

#: The tenant root. It is tenant-scoped like everything else, but its own primary key *is*
#: the tenant key, so its RLS policy compares `id` rather than `agency_id`.
TENANT_ROOT_TABLE = "agency"

#: Every table whose RLS policy keys on `agency_id`. Derived from the metadata rather than
#: hand-listed, so a new table cannot be added without either carrying the tenant key or
#: being deliberately classified above.
TENANT_TABLES: tuple[str, ...] = tuple(
    sorted(
        name
        for name, table in Base.metadata.tables.items()
        if name not in GLOBAL_TABLES and "agency_id" in table.columns
    )
)

#: Every table that must have RLS enabled, including the tenant root.
RLS_TABLES: tuple[str, ...] = tuple(sorted((*TENANT_TABLES, TENANT_ROOT_TABLE)))


def assert_every_table_is_classified() -> None:
    """Fail loudly if a table is neither tenant-scoped nor explicitly global.

    Called from `alembic/env.py` and from the schema test. This is the guard that keeps the
    "multi-tenant by construction" principle (`03_Technical_Architecture.md` Section 1)
    true as the schema grows, instead of depending on a reviewer noticing a missing column.
    """
    unclassified = [
        name
        for name, table in Base.metadata.tables.items()
        if name not in GLOBAL_TABLES
        and name != TENANT_ROOT_TABLE
        and "agency_id" not in table.columns
    ]
    if unclassified:
        raise RuntimeError(
            "Tables missing an agency_id and not declared global in GLOBAL_TABLES: "
            f"{sorted(unclassified)}. Every table is tenant-scoped unless deliberately "
            "global (04_Data_Model_and_Schema.md Section 1)."
        )


__all__ = [
    "GLOBAL_TABLES",
    "RLS_TABLES",
    "TENANT_ROOT_TABLE",
    "TENANT_TABLES",
    "Base",
    "agency_models",
    "assert_every_table_is_classified",
    "audit_models",
    "billing_models",
    "credentialing_models",
    "documentation_models",
    "idempotency_models",
    "recruiting_models",
    "reference_models",
    "scheduling_models",
]
