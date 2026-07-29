# CareOS — Build Status

**Purpose:** the honest answer to "where is this actually?", assessed against the milestone
table in `10_Roadmap_Milestones_Team_Plan.md`. `12_Engineering_Handoff_Guide.md` Section 3
warns an incoming team not to assume any documented milestone was completed — this file
exists so that verification starts from a real inventory rather than from the roadmap's
intentions.

**Keep this current.** Drift between this file and the code is a bug
(`12_Engineering_Handoff_Guide.md` Section 5).

**Last updated:** 2026-07-29
**Assessed by:** initial build

---

## Summary

| | |
|---|---|
| Phase | 1 — AI Workforce Engine |
| Milestone reached | **M0 (Foundation), plus the M3 scheduling/EVV core** |
| Stack | Python 3.11, FastAPI, PostgreSQL 16, SQLAlchemy 2 async, Alembic |
| Tests | 119 passing against a real PostgreSQL instance |
| Lint / types | `ruff` and `mypy` clean |
| Clients | **None.** No web admin app, no caregiver mobile app |
| Compliance review | **Not performed** |

The stack choice between TypeScript/NestJS and Python/FastAPI was left open by
`03_Technical_Architecture.md` Section 2. Python was chosen because the repository already
carried a Python `.gitignore`, and because that section prefers Python where the AI/ML
inference layer should share a language with the app layer — which applies here, since
ranking, ambient extraction, and claim scrubbing are all core to the roadmap.

## Milestone assessment

| Milestone | Target | Status |
|---|---|---|
| **M0 — Foundation** | Month 1 | **Done.** Tenant/agency model, auth, RBAC, CI/CD, containerized local stack |
| **M1 — Recruiting alpha** | Month 3 | **Schema only.** `job_posting` and `applicant_profile` exist with the explainability constraint; no endpoints, no job-board integration |
| **M2 — Onboarding & credentialing** | Month 5 | **Partial.** `caregiver`, `credential`, `screening_request` tables; exclusion-check endpoint and hard scheduling gate are live. No vendor integration, no digital paperwork, no credentialing dashboard |
| **M3 — Scheduling & EVV core** | Month 7 | **Substantially done, minus the mobile client.** Care plans, RRULE visit generation, assignment with compliance gates, clock-in/out, EVV adapter layer, transmission worker with backoff and escalation |
| **M4 — AI ranking + gap-fill** | Month 8 | **Not started.** Schema is ready (`ranking_score`, `ranking_factors`, `ranking_model_version`) |
| **M5 — Phase 1 GA** | Month 9 | **Not started.** Requires M1–M4, both clients, and compliance sign-off |

## What is built

### Foundation and cross-cutting
- **Multi-tenancy.** `agency_id` on every tenant table via `TenantMixin`; RLS enabled *and*
  forced on all 21 tenant tables; `careos_app` (no `BYPASSRLS`) for request handling and a
  narrow `careos_auth` for pre-tenant operations only.
- **RBAC.** All six roles; enforced by shared dependency; startup refuses to boot if any
  route lacks an access declaration. The auditor role is read-only by method, centrally.
- **Audit log.** Append-only by grant. Covers writes *and* PHI reads. Written in the
  caller's transaction.
- **Field-level encryption.** AES-256-GCM for tax ID, DOB, and street address, with a random
  per-encryption nonce; key required from the environment outside local/test.
- **Idempotency.** `Idempotency-Key` enforced on side-effecting mutations, with replay,
  body-mismatch rejection, and in-flight conflict handling.
- **Error envelope.** Single shape for every failure, including FastAPI validation errors.

### Scheduling and EVV
- Clients, care plans, RRULE-based visit generation (idempotent over overlapping windows).
- Assignment gates: OIG/GSA exclusion (hard, publicly-funded payers only), credential expiry
  checked against the *service* date, employment status, and double-booking.
- Clock-in/out with offline replay dedup; telephony and manual-exception capture are
  first-class paths, not degraded ones.
- EVV adapter layer: `EVVTransmissionAdapter` interface, per-state registry, a config-driven
  REST adapter with Sandata/HHAeXchange/Tellus mappings, and a loopback adapter for
  dev/test. Production use is blocked until `sandbox_validated` is set.
- Transmission worker: exponential backoff, `SKIP LOCKED` so concurrent workers cannot
  double-transmit, escalation to a compliance exception after exhausting retries.

### Compliance rules engine
Built generically in Phase 1 as `02_Product_Requirements_Document.md` Section 6 requires, so
Phase 2's copilot and Phase 3's scrubber extend it rather than reimplementing it. Six Phase 1
visit rules; per-agency enable/severity/threshold configuration; one failing rule cannot
suppress the others.

### Schema
All tables from `04_Data_Model_and_Schema.md` exist, in the documented migration order —
including the Phase 2 and Phase 3 tables, which ship unused so that visits recorded today can
be traced onto a claim line later without a backfill.

## What is deliberately stubbed

These are honest placeholders, not oversights:

| Area | State | What it needs |
|---|---|---|
| **Authentication** | Local Argon2 password hashing | `08_Security_Architecture.md` Section 1 calls for a managed OIDC provider. `app_user.auth_provider_id` is the seam; the password path is deleted when the IdP lands. MFA enrolment is tracked but not enforced |
| **EVV vendor field maps** | Structurally correct, contents provisional | Confirm against current vendor documentation during sandbox validation |
| **EVV state assignments** | Seeded, marked `UNVERIFIED` | Confirm per state before operating there (`06_Compliance...` Section 1) |
| **Service codes** | A handful of `T1019`-style rows | Populate per state and payer contract with a certified billing consultant |
| **Object storage** | `*_s3_key` columns exist; nothing writes them | Encrypted S3 bucket plus an upload path |
| **Redis** | In the compose stack, unused by the app | Wire up when caching or a durable queue is needed |

## Not started

- **Caregiver mobile app** and **agency admin web app** — no client exists. This is the
  largest remaining gap in Phase 1, and the caregiver app is called out in
  `09_UX_Design_and_User_Flows.md` as the highest-stakes surface in the product.
- **AI/ML service** — no ranking, no inference. Schema and explainability constraint ready.
- **All third-party integrations** — background check, job boards, STT, clearinghouse,
  payroll, legacy EHR import.
- **Phase 2 and Phase 3 behaviour** — tables only, by design.
- **Rate limiting**, with the clock-in/out exemption in `05_API_Specification.md` Section 9.
- **Outbound webhooks** (`05_API_Specification.md` Section 7).
- **Data export tooling** — required by the PRD's portability NFR and by
  `06_Compliance...` Section 8, and explicitly meant to be first-class rather than an
  afterthought.
- **Observability** — structured logging exists; no APM, tracing, or alerting on the
  EVV/scheduling critical paths, which the 99.9% NFR requires.
- **Infrastructure-as-code** — no Terraform, no deployed environment.
- **Localization** — English only. The PRD requires English + Spanish at MVP.

## Compliance and security posture

| Item | Status |
|---|---|
| Healthcare-compliance counsel review | **Not performed.** Required before Phase 1 launch |
| BAAs with subprocessors | **None.** No PHI-touching vendor is integrated yet |
| AI hiring bias audit | **N/A.** Epic 1.2.2 is not built. Required before it ships |
| Incident-response plan | **Not written.** Required before Phase 1 launch |
| SOC 2 | **Not started.** Several underlying controls exist (access management, audit logging, encryption); no evidence collection |
| Penetration test | **Not performed** |

## Suggested next steps

1. **Agency admin web app**, starting with the scheduling board and the compliance-exception
   queue — the exception queue is the scheduler's default view per `09_UX...` principle 3,
   and the backend for it already exists.
2. **Caregiver mobile app** with a genuine offline store, since clock-in is the highest-stakes
   surface and cannot be validated without a real client.
3. **First real EVV integration** for one state, end to end through that vendor's sandbox —
   this is the assumption most likely to be wrong, and the cheapest time to find out is now.
4. **Engage compliance counsel.** `10_Roadmap_Milestones_Team_Plan.md` Section 5 is explicit
   that this should begin immediately rather than when a question arises.
5. **Recruiting endpoints (M1) and the AI ranking layer (M4)**, with the bias audit
   completed before ranking ships — not after.
