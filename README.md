# CareOS

An AI-native operating system for home-based care agencies — home care, home health, and
hospice. CareOS replaces the workforce, documentation, and billing workflows currently split
across legacy EHR-style systems, spreadsheets, and phone calls.

Full product rationale, scope, and constraints live in [`docs/`](docs/). **Read
[`docs/12_Engineering_Handoff_Guide.md`](docs/12_Engineering_Handoff_Guide.md) first** — it
explains how the document set fits together and what to verify before writing code.

---

## Current state

**Phase 1 (AI Workforce Engine) — M0 through M4 complete on the backend, with a working
agency admin web app and a working caregiver app.** Offline EVV clock-in is built and verified
against a real API with the browser's network genuinely cut. The caregiver app is an installable
PWA rather than a React Native build — a deviation from `03_Technical_Architecture.md` Section 2
that is explained in BUILD_STATUS. Remaining before launch: real-device testing, telephony
clock-in, and the compliance reviews.

See [`docs/BUILD_STATUS.md`](docs/BUILD_STATUS.md) for what is built, what is deliberately
stubbed, and what has not been started — assessed against the milestone table in
`docs/10_Roadmap_Milestones_Team_Plan.md`.

## Repository layout

```
docs/                    The 13-document product and architecture set (source of truth)
apps/admin-web/          Agency admin web app (Next.js 15, React 19, TypeScript)
apps/caregiver-app/      Caregiver app — offline-first EVV (Vite, React 19, PWA)
  src/lib/               Outbox and sync engine; no React or DOM imports, so a
                         React Native shell could reuse it behind a SQLite adapter
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
make dev              # API at http://localhost:8000/docs

# Admin web app (needs the API running)
cd apps/admin-web && npm install && npm run dev   # http://localhost:3000

# Caregiver app (needs the API running)
cd apps/caregiver-app && npm install && npm run dev   # http://localhost:3001
```

The caregiver app's offline behaviour only exists in a production build — the service worker is
not registered by the dev server — so test it with `npm run build && npm run preview`, then use
the browser's offline toggle.

```bash
cd apps/caregiver-app
npm test              # sync-engine unit tests, no browser needed
npm run test:e2e      # browser end-to-end, including genuinely-offline clock-in
```

```bash
make check            # everything CI runs: lint, types, tests
make test-isolation   # just the multi-tenant isolation suite
make help             # all targets
```

## Admin web app

Next.js App Router, server-rendered. Three deliberate choices:

- **The access token never reaches the browser.** It lives in an httpOnly cookie and every
  API call runs server-side. This app renders PHI, so an XSS able to read a token would be a
  reportable breach rather than a bug.
- **Every AI suggestion shows its reasoning inline**, per `docs/09_UX_Design_and_User_Flows.md`
  principle 4 — there is no bare score anywhere in the UI.
- **Design tokens before screens**, per that document's Section 5, so the caregiver mobile app
  and family portal can adopt the same scale rather than diverging.

Screens: dashboard, scheduling board with gap queue and ranked suggestions (Flow A, the
highest-frequency flow), recruiting funnel and applicant pipeline, credentialing renewal
queue, and compliance review standing.

### Information design

It is an operational console for someone working a live gap under time pressure, not a
marketing dashboard — so the chrome is recessive (hairline borders, no drop shadows, one
accent) and the data is the only loud thing on screen.

Each view starts from the data's job rather than a chart type. Coverage is a single ratio
against a limit, so it is a **meter**, not a two-slice pie. The recruiting funnel is an
ordered scale, so it uses a validated **ordinal ramp**. A match score is magnitude, so it is
a **bar** you compare by length instead of two numbers you read. The schedule is occupancy
over time, so it is a **timeline** — a list sorted by start time answers "what's next" but
hides clustering, and three unfilled visits at the same hour on Thursday is a different
problem from three spread across the week.

**The palette is computed, not chosen by eye.** The categorical slots and the ordinal ramp
were run through a validator against both surfaces: adjacent CVD ΔE 9.1 light / 8.4 dark
(≥8 target), normal-vision ΔE 22.9 / 19.8 (≥15 floor), and the ordinal ramp passes
monotone-lightness with ≥0.06 ΔL between steps in both modes. Dark mode is the same hues
re-stepped for the dark surface, not an automatic flip. Status colors are reserved — critical
means "act on this" — and always ship with an icon or label, since colour alone is not a
signal.

## Caregiver app: how offline works

This is the part of the product most likely to be got wrong, so the design is stated rather than
left to be inferred.

A clock-in is written to IndexedDB **before** the UI acknowledges it. The caregiver is told
"saved on this phone — will send when you have signal", and the network is attempted afterwards.
Everything else follows from that ordering:

- **The recorded time is the tap, not the delivery.** A visit began when the caregiver arrived,
  not when they next found a cell tower. For EVV that distinction is the whole point.
- **Replay is safe.** Each action carries a device-generated uuid, sent as both
  `client_local_uuid` and `Idempotency-Key`, and reused on every retry. A request that succeeded
  but whose response was lost is indistinguishable from one that never arrived — so the device
  retries, and the server recognises it. An end-to-end test delivers one clock-in three times
  and asserts a single EVV record.
- **The queue is ordered and stops at the first failure.** Sending a clock-out whose clock-in
  has not landed would be rejected on its merits, turning a network problem into lost data.
- **Nothing is dropped.** A rejected action stops being retried but is never deleted; it becomes
  "call the office". A caregiver's record of work performed is not the app's to discard.
- **No location is not a failure.** Location capture times out in 8 seconds and never blocks a
  clock-in. A missing fix is recorded as `manual_exception` with a readable reason, which is
  what `02_Product_Requirements_Document.md` US-1.4.3 asks for.

The sync engine (`apps/caregiver-app/src/lib/`) imports no React and no DOM. Storage and
transport are interfaces, so it is unit-testable without a browser and portable to a React
Native shell with a SQLite-backed store.

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

## Rate limits

`05_API_Specification.md` Section 9 gives two rules. Both are enforced, and the second one is
the interesting half.

| Tier | Limit | Keyed by |
|---|---|---|
| Standard | 100/minute | Agency, falling back to source address when unauthenticated |
| Auth (`/auth/login`, `/auth/refresh`, `POST /agencies`) | 10/minute per account, 30/minute per address | Address, and address + email |
| Exempt (`clock-in`, `clock-out`, `/health`) | none | — |

**Clock-in and clock-out are never throttled.** A caregiver whose EVV record could not be
created because someone else's traffic filled the agency's budget has an unpaid visit and the
agency has a compliance exception, so throttling is not an available answer. Section 9 asks for
abuse detection in its place: volume per caregiver is counted and logged above a ceiling no human
reaches, and it never refuses a request. That is a shallow version of what the section describes —
device fingerprinting and geo-velocity need a device identity the app does not send yet.

The auth tier is not in the spec. Everything there is keyed by agency, and login happens before
an agency is known, which left the password form as the only endpoint with no ceiling at all.

Refusals carry `Retry-After`; answered requests carry `RateLimit-Limit`, `RateLimit-Remaining`,
and `RateLimit-Reset`, so a client can slow down before it is turned away. The caregiver app's
outbox honours the header in preference to its own backoff.

Limits are configurable (`CAREOS_RATE_LIMIT_*`). The buckets live in Redis
(`CAREOS_RATE_LIMIT_BACKEND=redis`), so the figures above are what the cluster enforces rather than
what each instance enforces separately. The refill arithmetic runs as a Lua script and reads
Redis's own clock, because a read-modify-write over the network lets N concurrent requests each
see the same balance, and instances sharing a bucket must also share a clock.

`memory` keeps the buckets in process and is the default for development and tests; it multiplies
every limit by the instance count, so production refuses to boot on it.

**When Redis is unreachable the API keeps serving and limiting falls back to in-process buckets.**
Fail closed would make an EVV clock-in depend on a cache; fail open would lift the brute-force
ceiling on login at the worst possible moment. Degraded means the limits still apply, just per
instance. It is logged at `error` with the consequence spelled out, and a short circuit breaker
keeps a dead Redis from costing a connect timeout on every request.

## Metrics

Prometheus exposition at `GET /metrics`, scraped by a collector rather than pushed anywhere, so
nothing outbound sits in a request path.

It exists because several things here **degrade rather than break**, which is deliberate — a
system that keeps serving caregivers beats one that stops — but it means the only evidence was a
log line nothing collected:

| Signal | Why it is invisible otherwise |
|---|---|
| `careos_rate_limit_degraded` | A limiter that has lost Redis answers every request; the cluster just enforces N× the published ceiling |
| `careos_evv_anomalous_volume_total` | Section 9 asks for detection instead of throttling on clock-in. Nothing is ever refused, so the counter *is* the response |
| `careos_evv_escalations_total` | A record that exhausted its retries now needs a person, and nobody is told |
| `careos_request_commit_failures_total` | How often the database will not accept a write |
| `careos_sessions_rejected_total{reason}` | Revoked-session refusals separated from ordinary bad tokens — a spike in the first means an offboarding just happened |
| `careos_http_requests_total`, `careos_http_request_duration_seconds` | By route template and status |

**No label carries a tenant or a person.** No `agency_id`, no `caregiver_id`, no client name.
Metrics outlive logs, are exported to systems with looser access control than the database, and
land on dashboards a lot of people can see. Route *templates* are used rather than paths for the
same reason, and because `/v1/visits/{visit_id}` is one time series where the concrete path is
one per visit. A test walks every registered collector and fails on a forbidden label, so a
metric added later cannot quietly reintroduce it.

Scraping is gated by `CAREOS_METRICS_TOKEN` as a bearer token, compared in constant time.
Production refuses to boot without one; local development may leave it empty. The endpoint is
`public()` in the RBAC sense because a collector has no agency and fits no role in this model —
inventing one would put a login in the monitoring path.

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
