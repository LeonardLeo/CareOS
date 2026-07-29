# CareOS

An AI-native operating system for home-based care agencies — home care, home health, and
hospice. CareOS replaces the workforce, documentation, and billing workflows currently split
across legacy EHR-style systems, spreadsheets, and phone calls.

Full product rationale, scope, and constraints live in [`docs/`](docs/). **Read
[`docs/12_Engineering_Handoff_Guide.md`](docs/12_Engineering_Handoff_Guide.md) first** — it
explains how the document set fits together and what to verify before writing code.

---

## Current state

**Phase 1 (AI Workforce Engine), milestone M0 plus the scheduling/EVV core.** The backend
runs, is migrated, and is tested end to end. There is no web or mobile client yet.

See [`docs/BUILD_STATUS.md`](docs/BUILD_STATUS.md) for what is built, what is deliberately
stubbed, and what has not been started — assessed against the milestone table in
`docs/10_Roadmap_Milestones_Team_Plan.md`.

## Repository layout

```
docs/                    The 13-document product and architecture set (source of truth)
services/api/            Modular-monolith backend (Python 3.11, FastAPI, PostgreSQL)
  careos/
    api/                 HTTP layer — routers, schemas, dependencies
    core/                Cross-cutting: RBAC, audit, errors, idempotency, crypto, security
    db/                  Engines, session/tenant context, RLS helpers, model registry
    integrations/evv/    Per-state EVV adapters behind one interface
    modules/             Domain modules per 03_Technical_Architecture.md Section 4
    workers/             Async jobs (EVV transmission)
    scripts/             Reference-data seeding
  alembic/versions/      Migrations, sequenced per 04_Data_Model_and_Schema.md Section 8
  tests/                 Includes the CI-required multi-tenant isolation suite
.github/workflows/ci.yml Required checks
docker-compose.yml       Local stack
```

The folder structure mirrors the modular-monolith decomposition on purpose, so the
architecture is visible in the tree rather than only in the document
(`docs/12_Engineering_Handoff_Guide.md` Section 4).

## Quick start

Requires Python 3.11+ and PostgreSQL 16 (or just Docker).

```bash
# With Docker — brings up Postgres, Redis, and the API, migrated and seeded
make up

# Or locally
make install
make bootstrap-db     # creates the database and the careos_app / careos_auth roles
make migrate
make seed
make dev              # http://localhost:8000/docs
```

```bash
make check            # everything CI runs: lint, types, tests
make test-isolation   # just the multi-tenant isolation suite
make help             # all targets
```

## Architecture at a glance

A **modular monolith** (`docs/03_Technical_Architecture.md` principle 2): one deployable,
with hard module boundaries, rather than premature microservices. The AI/ML inference layer
is the first intended extraction and is already isolated behind `careos/integrations/`.

Four things are structural rather than conventional — enforced by the system, not by
reviewer vigilance:

**Tenant isolation has two independent layers.** Every tenant-scoped table has a PostgreSQL
Row-Level Security policy with `FORCE ROW LEVEL SECURITY`, keyed on a transaction-local
`careos.agency_id` setting. The application connects as `careos_app`, which holds no
`BYPASSRLS` — so a handler that forgets to filter still cannot read another tenant's rows.
A separate, narrowly-granted `careos_auth` role exists only for the two operations that
precede knowing the tenant (login and agency provisioning). Cross-tenant read, write,
update, delete, and insert attempts are all tested against a real database.

**Every route declares who may call it.** `careos/core/rbac.py` validates at startup that
each route declares either `requires(...)` roles or an explicit `public()` opt-out, and the
app refuses to boot otherwise. `route_access_map()` dumps the full matrix as control
evidence.

**The audit trail cannot be rewritten.** The application role has `SELECT` and `INSERT` on
`audit_log` and nothing else, so immutability is a database grant rather than a promise.
Audit rows are written in the same transaction as the change they describe — if the change
rolls back, so does its audit row.

**No table can quietly skip the tenant key.** `careos/db/models.py` derives the tenant-table
list from metadata and fails at startup if any table is neither tenant-scoped nor explicitly
declared global. `alembic check` in CI catches migration/model drift.

### EVV

Electronic Visit Verification is a hard compliance requirement, not a feature
(`docs/06_Compliance_and_Regulatory_Requirements.md` Section 1). Three properties are
load-bearing:

- **Per-state adapters behind one interface.** States change EVV vendors; when that happens
  the fix is a row in `evv_aggregator_ref`, not a change to the scheduling module.
- **A visit is compliant only when *acknowledged*,** not when submitted.
- **An adapter cannot transmit production data until validated against the vendor sandbox.**
  The registry enforces this from `evv_aggregator_ref.sandbox_validated`.

Clock-in and clock-out never block on a compliance problem. A caregiver standing in a
client's home must always be able to record that they are there; problems surface as
compliance exceptions afterwards. Transmission happens in a background worker with
exponential backoff, escalating to a human after repeated failure.

## Non-negotiable constraints

From `docs/01_Product_Vision_and_Executive_Summary.md` Section 7 and
`docs/02_Product_Requirements_Document.md` Section 4:

| Constraint | Where it lives |
|---|---|
| HIPAA from day one | Field-level encryption (`core/crypto.py`), audit on PHI reads, RBAC |
| Multi-tenant isolation architected in, never retrofitted | `db/rls.py`, `db/session.py`, migrations |
| EVV compliance is not optional scope | `integrations/evv/`, `modules/scheduling/` |
| Offline-first mobile | `client_local_uuid` dedup, `Idempotency-Key` on side-effecting mutations |
| Auditability — attributable and immutable | `core/audit.py`, append-only grants |
| Design for Phase 3 from Phase 1 | Phase 2/3 tables ship unused; visits carry billing fields |

## Compliance status

**No compliance review has been performed.** `docs/06_Compliance_and_Regulatory_Requirements.md`
Section 9 requires healthcare-compliance counsel review before Phase 1 launch, and a
certified billing/coding consultant before Phase 3. The EVV aggregator assignments in
`careos/scripts/seed_reference_data.py` are marked `UNVERIFIED` and must be confirmed per
state before operating there. No BAAs are in place, because no third-party vendor is
integrated yet.

## Contributing

`make check` must pass. Beyond that, three rules specific to this codebase:

1. **A new table carries `agency_id`** — inherit `TenantMixin` — **and its migration calls
   `standard_tenant_table()`.** If it is genuinely global reference data, add it to
   `GLOBAL_TABLES` so the omission is a decision on the record.
2. **A new route declares its roles.** The app will not start otherwise.
3. **Drift between `docs/` and the code is a bug** (`docs/12_Engineering_Handoff_Guide.md`
   Section 5). If you change scope or an architectural decision, update the document in the
   same change — not later.
