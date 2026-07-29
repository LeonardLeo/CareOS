# CareOS — Build Status

**Purpose:** the honest answer to "where is this actually?", assessed against the milestone
table in `10_Roadmap_Milestones_Team_Plan.md`. `12_Engineering_Handoff_Guide.md` Section 3
warns an incoming team not to assume any documented milestone was completed — this file
exists so that verification starts from a real inventory rather than from the roadmap's
intentions.

**Keep this current.** Drift between this file and the code is a bug
(`12_Engineering_Handoff_Guide.md` Section 5).

**Last updated:** 2026-07-29
**Assessed by:** build increment 7 (caregiver app — offline-first EVV)

---

## Summary

| | |
|---|---|
| Phase | 1 — AI Workforce Engine |
| Milestone reached | **M0–M4 backend complete.** M5 (Phase 1 GA) blocked on clients and compliance review |
| Stack | Python 3.11, FastAPI, PostgreSQL 16, SQLAlchemy 2 async, Alembic |
| Tests | 211 API tests against a real PostgreSQL instance, 13 sync-engine unit tests, 10 browser end-to-end tests including genuinely-offline clock-in |
| Lint / types | `ruff` and `mypy` clean |
| Clients | **Admin web app and caregiver app both built and working.** Caregiver app is an installable PWA, not React Native — see below |
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
| **M1 — Recruiting alpha** | Month 3 | **Backend done.** Job postings, normalized applicant intake, guarded stage transitions, applicant→caregiver hire, funnel report with conversion. No job-board integration yet |
| **M2 — Onboarding & credentialing** | Month 5 | **Mostly done.** Credential CRUD, expiration dashboard with 7/30/60-day buckets, exclusion-check endpoint and hard scheduling gate. No vendor integration, no digital onboarding paperwork |
| **M3 — Scheduling & EVV core** | Month 7 | **Done, both ends.** Care plans, RRULE visit generation, assignment with compliance gates, clock-in/out, EVV adapter layer, transmission worker with backoff and escalation. Caregiver app closes the loop: offline clock-in/out with an on-device outbox, verified exactly-once |
| **M4 — AI ranking + gap-fill** | Month 8 | **Backend done.** Explainable ranking for applicants and shift matching, gap detection, fair-hiring feature allowlist, bias-audit tooling |
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
- **CI.** Seven required jobs (`.github/workflows/ci.yml`). Three of them were failing on the
  first pull request for reasons worth recording, because each was invisible locally:
  - The repository's Python `.gitignore` carried an unanchored `lib/`, which matches a
    directory of that name at any depth and so excluded `apps/admin-web/src/lib` — the web
    app's API client and session module — from the repository entirely. It built locally,
    where the files were on disk, and failed the type-check here, where they had never been
    committed. The packaging rules are now anchored to the repo root, and a job step asserts
    against `git check-ignore` that no source path is excluded. That check reads the ignore
    *rules*, not the working tree: a clean checkout does not contain the missing files, so
    anything that looks for them on disk passes vacuously.
  - `pytest` and `python -m pytest` disagreed. With `tests/` not a package, the bare form puts
    `tests/` itself on `sys.path` rather than its parent, so `from tests.conftest import ...`
    fails at collection. CI runs the bare form. `pythonpath = ["."]` makes both work.
  - The session fixture shelled out to `services/api/.venv/bin/alembic` — a path created by
    `make install` and absent in CI, where the package is pip-installed into the runner's own
    Python. Every test errored in setup. It now runs alembic through the interpreter running
    the tests. The fixture's subprocess helper also raises with the captured stderr instead of
    only an exit status, so the next setup failure names itself rather than reporting nothing
    across every test.
  - `pip-audit` flagged PYSEC-2026-3447 in the runner's setuptools. Remediated by requiring
    `setuptools>=83.0.0` for the build rather than by excusing the finding.

  All three assumed a developer machine and were invisible from a working tree that already
  satisfied them. `make test-clean` now runs the suite against a fresh clone with its
  virtualenv outside the repo, which is the only local arrangement in which those assumptions
  fail the way they fail in CI.

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

### Recruiting and ranking
- Job postings; applicant intake normalized regardless of source, so no job board's schema
  reaches the domain model.
- Guarded pipeline transitions — a rejected applicant is not silently revived, and `hired` is
  terminal. Hiring converts an applicant into a caregiver in `onboarding` with
  `exclusion_check_status = not_run`: being hired and being clearable for a Medicaid visit
  are separate events.
- Funnel report with stage-to-stage conversion, counted cumulatively so rejected applicants
  still count at the top and the rates mean something.
- **Explainable ranking** for both applicants and shift matching, sharing one scorer. Every
  score carries its top three factors with human-readable rationales; a score without factors
  is rejected by a database check constraint, not merely by convention.

### Fair hiring
`06_Compliance_and_Regulatory_Requirements.md` Section 5 is enforced structurally rather than
by review:
- A closed **feature allowlist**. Anything unrecognised is refused — a denylist would only
  catch attributes someone thought to forbid.
- Named **proxies** are refused alongside the attributes themselves: ZIP code, graduation
  year, name, school, salary history, credit score, arrest record. Errors say *why*.
- Validation lives inside the scorer, so no caller can route around it. Applicant intake has
  no field for demographic data at all — the surest way to keep it out of the model.
- **Bias-audit tooling**: adverse-impact ratios against the EEOC four-fifths screen, with a
  minimum group size so an underpowered sample reports `insufficient_data` rather than a
  meaningless pass. Demographic labels are supplied by the auditor from separately-held
  voluntary data; nothing in the schema stores an applicant's race or sex.

### Shift matching and gap-fill
- Suggestions reuse `assert_assignable`, so a caregiver who would be refused at assignment is
  never suggested. Showing a scheduler a name they cannot act on, mid gap-fill, is worse than
  showing nothing.
- Factors: certification match, drive-time proximity, availability, continuity of care, and
  overtime headroom. Overtime is a warning, not a block — the scheduler decides.
- Gap detection over unfilled visits starting soon, ordered most-urgent-first.

### Credentialing
Credential CRUD plus an expiration dashboard bucketed at 7/30/60 days. Already-expired
credentials are surfaced rather than filtered out: they are the most urgent case, since the
caregiver is unassignable right now.

### Caregiver app
The surface `09_UX_Design_and_User_Flows.md` design principle 1 calls the highest-stakes one in
the product. Flow B works end to end: open the app, see today's schedule, tap into a visit,
clock in, clock out.

**Built as an installable PWA rather than React Native, and that is a deviation worth stating
plainly.** `03_Technical_Architecture.md` Section 2 names "React Native or Flutter" — but the
same row says the offline-first library choice, *not the framework*, is the critical decision.
A React Native app cannot be run or verified in this environment at all: with no simulator, an
offline clock-in path would have been shipped unexecuted, which on this surface means shipping
an unverified claim about whether caregivers get paid. The PWA runs in a real browser, so the
offline behaviour is tested rather than asserted. Everything in `src/lib` — the outbox, the
sync engine, the retry policy — is free of React and DOM imports and reusable verbatim behind a
SQLite adapter if the app is later rebuilt in React Native; the split `vitest.config.ts`
enforces that boundary rather than trusting it.

What holds it up:
- **The outbox** (`src/lib/outbox.ts`). An action is written to IndexedDB *before* the UI
  acknowledges it, carries a device-generated uuid used as both `client_local_uuid` and
  `Idempotency-Key`, records the time of the tap rather than of delivery, and is never deleted
  on failure. The flush stops at the first unreachable action rather than skipping past it,
  because a clock-out arriving before its clock-in would be rejected on the merits and turn a
  network problem into lost data. After repeated failures it escalates to "call the office"
  instead of retrying in silence.
- **Verified offline, not assumed.** 13 unit tests on the engine, and browser end-to-end tests
  that cut the network for real, clock in, restore it, and assert against the API that the
  visit synced. One test replays the same queued clock-in three times and asserts a single EVV
  record with one id and one timestamp — the dedup demonstrated rather than inferred.
- **Offline as a state, not an error.** A permanent connection bar, per-visit queued badges, and
  a cold start with no signal that opens onto the cached day labelled with its age.
- **The no-GPS path is first-class** (US-1.4.3). Location capture has an 8-second timeout and
  never blocks a clock-in; a missing fix is recorded as `manual_exception` with a reason in
  words an agency can act on, and the caregiver is told it saved either way.
- **Designed for the stated user.** 17px body minimum, 56px touch targets, an 88px primary
  action pinned in the thumb's reach, and AAA contrast (17.5:1 light, 16.1:1 dark) because
  sunlight eats the 4.5:1 that passes an audit indoors. Every colour pair was run through a
  WCAG check, not chosen by eye.
- **English and Spanish** as a baseline, keyed by meaning with named interpolation so a
  translation can reorder tokens.

Honest limitations on this surface specifically:

| Limitation | Detail |
|---|---|
| **Token reachable from JavaScript** | The admin app keeps its token in an httpOnly cookie; this one cannot, because the device replays its own queued writes. Mitigated with `sessionStorage` (not `localStorage`), no stored refresh token, and cached PHI wiped on sign-out — but it is a real reduction in XSS resistance, not an equivalent |
| **Telephony (IVR) fallback** | `capture_method: telephony` is accepted by the API and modelled throughout; no phone system is wired up. A caregiver with no smartphone is not yet served |
| **No push notifications** | Flow A step 4 (accept a shift offer in one tap) needs push and a shift-offer endpoint; neither exists. iOS also only delivers web push to a home-screen-installed PWA, which affects the framework decision above and should be re-examined before launch |
| **No background sync** | The queue flushes when the app is foregrounded or regains connectivity, not while closed. A caregiver who clocks out and force-quits before regaining signal syncs on next open |
| **Remote wipe is local-only** | `08_Security_Architecture.md` Section 6 wants an admin to cut off a terminated caregiver including cached PHI. Sign-out and a rejected token clear the local cache; server-side session revocation is not built |
| **Not verified on real devices** | Tested in Chromium at a phone viewport. No iOS Safari, no Android Chrome, no real GPS, no genuinely degraded network |

### Agency admin web app
Next.js App Router, server-rendered, with the design-token pass `09_UX...` Section 5 asks for
done before any screen. Charts are chosen by the data's job — a meter for coverage, an
ordinal-ramp funnel for pipeline stages, a length-comparable bar for match scores, a timeline
for schedule occupancy — and the palette was validated for colour-vision separation against
both surfaces rather than picked by eye. The access token is held in an httpOnly cookie and never reaches page
JavaScript, because this surface renders PHI. Screens: dashboard, scheduling board with gap
queue and ranked suggestions (Flow A), client roster with intake and care-plan authoring,
compliance-exception queue, recruiting funnel and applicant pipeline, credentialing renewal
queue, compliance review standing. Verified end to end against a live API — assigning a
caregiver through the UI moves the visit out of the gap queue, and admitting a client then
authoring a plan produces visits that appear on the scheduling timeline.

Three things were found only by driving the flows rather than by reading the code. A care
plan's id existed nowhere but the query string of the redirect that created it, so returning to
a client later left no way to generate further visits from a plan that already existed —
`GET /v1/clients/{id}/care-plans` closes that. `CarePlanOut` then omitted
`visit_frequency_rule`, so the generate-visits form could not show the recurrence the visits
would follow, and with two plans on a client gave no indication which one it was about to use;
both are now on screen above the form. And the schedule timeline encoded each visit's detail in
a `title` attribute, which a keyboard user never sees; marks are now buttons with a tooltip on
focus as well as hover, and a hit area padded past the 2px bar.

### Compliance-exception queue
`06_Compliance_and_Regulatory_Requirements.md` Section 4 requires exceptions be worked, not
just recorded. Open findings are listed severity-first — critical, then warning, then info,
oldest first inside each band, so the queue reads top-down as a work order — with a resolution
that writes `compliance_exception_resolved` to the audit log against the resolving user. The
nav carries the open count, so an unattended queue is visible without opening it.

### Compliance operations
`06_Compliance_and_Regulatory_Requirements.md` Section 9 sets a review cadence, and
`12_Engineering_Handoff_Guide.md` Section 5 requires outcomes and dates recorded durably.
Reviews are rows in `compliance_review`, so overdue reviews are computable rather than
remembered. `GET /v1/agencies/{id}/compliance-reviews` enumerates the full cadence including
reviews never performed — a gap shows as `never_performed` rather than being absent from the
list. The bias audit writes its own outcome here when it runs.

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
| **Drive time** | `HaversineRoutingAdapter` — straight-line distance with a circuity correction, marked `is_estimate` throughout | Adequate for ranking candidates against each other; register a real routing provider before travel time is quoted to a caregiver or paid on a timesheet |

## Not started

- **Native mobile packaging.** The caregiver app is built and its offline clock-in is verified
  (see above), but as an installable PWA rather than a React Native build. App Store / Play
  distribution, iOS web push, and background sync all depend on revisiting that.
- **Telephony (IVR) clock-in.** Accepted by the API, modelled end to end, no phone system
  attached. Until it exists, a caregiver without a smartphone cannot clock in at all.
- **Hosted-LLM inference** — ranking is a deterministic weighted scorer behind a `Scorer`
  protocol. `03_Technical_Architecture.md` Section 5 makes that the intended first step and
  warns against over-building; an LLM implementation slots in behind the same interface and
  the same allowlist. Ambient documentation and claim scrubbing remain unbuilt.
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
| AI hiring bias audit | **Runnable and self-logging; no audit has been run on real outcomes.** `python -m careos.scripts.run_bias_audit` performs one and records it to the compliance log; it exits non-zero on adverse impact so it can gate a release. Requires demographic labels supplied separately, plus employment-counsel review |
| Incident-response plan | **Not written.** Required before Phase 1 launch |
| SOC 2 | **Not started.** Several underlying controls exist (access management, audit logging, encryption); no evidence collection |
| Penetration test | **Not performed** |

## Suggested next steps

1. **Run the caregiver app on real devices.** It is verified in Chromium at a phone viewport
   against a real API, which is a much stronger position than unexecuted code but is not the
   same as iOS Safari, a real GPS chip, and a genuinely bad connection. Decide native
   packaging at the same time, since iOS push and background sync depend on it.
2. **User administration in the admin app.** Client management, care-plan authoring, and the
   compliance-exception queue now exist as first-class screens; inviting a user and changing a
   role still require calling the API directly, even though both endpoints exist.
3. **First real EVV integration** for one state, end to end through that vendor's sandbox.
   This is the assumption most likely to be wrong, and the cheapest time to find out is now.
4. **Engage compliance counsel**, and run the bias audit on real outcomes before the ranking
   model influences actual hiring. The tooling exists; the audit does not.
5. **Register a real routing provider.** The `RoutingAdapter` interface and registry
   exist; only the haversine approximation is implemented. This is now a one-class change.
6. **Job-board and background-check integrations**, behind the adapter interfaces
   `07_Integration_Specifications.md` Section 1 requires.
