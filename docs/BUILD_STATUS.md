# CareOS — Build Status

**Purpose:** the honest answer to "where is this actually?", assessed against the milestone
table in `10_Roadmap_Milestones_Team_Plan.md`. `12_Engineering_Handoff_Guide.md` Section 3
warns an incoming team not to assume any documented milestone was completed — this file
exists so that verification starts from a real inventory rather than from the roadmap's
intentions.

**Keep this current.** Drift between this file and the code is a bug
(`12_Engineering_Handoff_Guide.md` Section 5).

**Last updated:** 2026-07-30
**Assessed by:** build increment 11 (transaction boundary)

---

## Summary

| | |
|---|---|
| Phase | 1 — AI Workforce Engine |
| Milestone reached | **M0–M4 backend complete.** M5 (Phase 1 GA) blocked on clients and compliance review |
| Stack | Python 3.11, FastAPI, PostgreSQL 16, SQLAlchemy 2 async, Alembic |
| Tests | 275 API tests against real PostgreSQL and real Redis instances, 19 sync-engine unit tests, 10 browser end-to-end tests including genuinely-offline clock-in |
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
- **Session revocation and offboarding.** `08_Security_Architecture.md` Section 6 requires an
  admin to be able to immediately cut off a terminated caregiver *including the PHI cached on
  their device*. Only the device half existed: the caregiver app wiped its cache when the API
  rejected a token, and the API could not reject one.
  - `app_user.sessions_revoked_at` is a watermark; any access token issued at or before it is
    refused. Chosen over a token denylist, which would need every issued `jti` retained until
    expiry — a watermark invalidates every outstanding session in one write and cannot grow.
  - It costs one query per authenticated request. That is deliberate: the requirement says
    "immediately", and any cache defines a window in which a terminated caregiver still has
    access. Redis is now in the request path for rate limiting and could hold this too if the
    query ever shows up in latency — at the price of naming that window explicitly.
  - Comparison needs sub-second precision on both sides, so tokens carry a microsecond
    `iat_us` claim alongside the standard whole-second `iat`. The first version compared
    against `iat` and locked users out of *signing back in* for up to a second after a
    revocation — caught by a test asserting re-login works, not by reading the code.
  - **Termination performs the revocation itself.** `POST /caregivers/{id}/terminate` sets
    `terminated` and revokes the linked login in one transaction. Two endpoints an
    administrator is trusted to call in sequence is how the second one does not happen on a
    busy Friday. Before this there was no way to terminate anyone at all — `employment_status`
    was only ever set to `onboarding` or `active`, so an agency could hire through this system
    but not part ways through it.
  - A reason is required and audited. "We removed their access when they left" is a claim, and
    a reason attached to a timestamp and an actor is what evidences it.
- **Error envelope.** Single shape for every failure, including FastAPI validation errors.
- **Rate limiting** (`05_API_Specification.md` Section 9). Token buckets, three tiers, and the
  exemption is the point of the design rather than a footnote:
  - **Clock-in and clock-out are never throttled**, as Section 9 requires. An EVV record that
    could not be created because someone else filled the agency's budget becomes this
    caregiver's unpaid visit. Verified by a test that exhausts the standard budget and asserts
    a clock-in still gets a non-429 answer.
  - **Standard: 100/minute per agency**, the documented figure, keyed by agency so two agencies
    behind one address do not consume each other's allowance — and falling back to the address
    when there is no token, or an unauthenticated flood would have no key and therefore no
    limit.
  - **Auth endpoints get their own tier**, which the spec does not describe. Keyed by agency,
    login cannot be limited at all, so the password form was the one endpoint with no ceiling —
    and session revocation had just given an attacker a reason to hammer it. 10/minute per
    account and address (applied inside the login handler, because the email is in the body and
    reading a body in middleware consumes the stream the handler needs) plus 30/minute per
    address, so credential spraying across many accounts is caught by the second counter even
    though each account stays under the first.
  - **Buckets, not fixed windows.** A fixed window permits the whole allowance at the end of
    one window and again at the start of the next, and that 2x burst arrives exactly when
    retrying clients have synchronized to the boundary.
  - `Retry-After` on refusals and `RateLimit-*` on every answered request, so a client can slow
    down before it is turned away. The caregiver app's outbox honours the header rather than
    its own backoff — retrying sooner than instructed is how a client turns a rate limit into
    the load that caused it.
  - Two bugs found while building it, both by tests rather than review. The first version
    resolved route templates with Starlette's `route.matches()`, which silently matched nothing
    because FastAPI wraps included routers — so every request fell to the standard tier and
    **clock-in was being throttled**, the one outcome Section 9 forbids. The startup path check
    did not catch it, because that check reads a different traversal which already worked. The
    second: templates were ordered by length, so `/v1/visits/{visit_id}` beat the literal
    `/v1/visits/gaps`; specificity is wildcard count, not string length.
  - **Buckets are shared across instances** (`CAREOS_RATE_LIMIT_BACKEND=redis`), so the
    configured figure is what the cluster enforces. This replaced an in-process store under
    which N instances enforced N x the documented ceiling while the `RateLimit-*` headers kept
    reporting the documented one — a limiter that looked correct from the outside and was not.
    Production refuses to boot on the in-process backend for that reason; nothing about a
    running system reveals the difference, so boot is the only place it can be caught.
    - The refill runs as a **Lua script**, not a read-modify-write. Fifty concurrent requests
      against a budget of five admit exactly five; the same pattern against a Python
      read-modify-write admitted all fifty, which is what "not a limiter" means here.
    - The clock is **Redis's own `TIME`**. Instances sharing a bucket must share a clock, or an
      instance running fast refills everyone's bucket early. Tested by handing a store a
      monotonic clock that never advances and watching the bucket recover anyway.
    - **A Redis outage degrades rather than fails.** Limiting falls back to in-process buckets:
      fail closed would make a legally time-sensitive clock-in depend on a cache, and fail open
      would lift the brute-force ceiling on login exactly when the system is least healthy.
      Logged at `error` with the consequence stated, re-logged while it persists, and a short
      circuit breaker keeps a dead Redis from costing a connect timeout per request. Verified
      against a real server by killing it mid-traffic: the API kept answering, the limit kept
      applying, and six requests took 69 ms rather than six connect timeouts.
    - The store's tests run against a **real Redis** in CI, and a test fails the build if that
      service ever goes missing — a module that silently skips itself in CI looks like a pass.
  - **`Retry-After` and `RateLimit-*` were invisible to the caregiver app** until this
    increment. Neither is a CORS-safelisted response header, so a browser discarded both: the
    server was sending pacing instructions the PWA could not read, and the outbox fell back to
    its own backoff and retried a throttled server sooner than it had been asked to. Fixed by
    naming them in `expose_headers`. Found while wiring the shared store, not by a test — the
    suite calls the API same-origin through ASGI, where CORS never applies.
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
- **Two real bugs the CI run found that local runs did not.** `flush()` had no mutual
  exclusion, and it is triggered from four places — queueing an action, the reconnect event,
  the foreground event, and the retry timer. Two overlapping flushes sent the same action
  concurrently and the server correctly answered the loser with 409 "a request with this
  Idempotency-Key is still in progress". Worse, the transport mapped that 409 to a permanent
  rejection, so the app told a caregiver "could not send — call the office" about a clock-in
  that had in fact succeeded. That is the worst failure this surface can produce: it errs
  toward the caregiver believing they will not be paid. `flush()` is now serialized and a 409
  is treated as retry-later. Both are pinned by tests that hang without the fix.
- **Verified offline, not assumed.** 16 unit tests on the engine, and browser end-to-end tests
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
queue, compliance review standing, user administration (invite, role change, end sessions). Verified end to end against a live API — assigning a
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
| **Redis** | Holds the shared rate-limit buckets, and nothing else | Deploy it as a real dependency — HA, monitored, with the eviction policy set so buckets are not silently dropped under memory pressure. A single node quietly turns every limit back into a per-instance one |
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
| Brute-force protection | **Built and tested.** 10 login attempts per minute per account and address, 30 per address across accounts, counted before the password is checked. Account lockout after repeated failures is *not* implemented — the limiter slows an attacker rather than stopping them, and a lockout policy needs a decision about the denial-of-service it enables |
| EVV abuse detection | **Detection only.** Section 9 asks for heuristics in place of throttling on clock-in/out; volume per caregiver is counted and logged above a ceiling no human reaches, but it is not surfaced in the exception queue, and device fingerprinting and geo-velocity are not built — the app does not yet send a device identity |
| Offboarding | **Built and tested.** Terminating a caregiver revokes their login in the same transaction, and an owner can end any user's sessions from the Users screen with an audited reason. Account *disablement* (as distinct from ending sessions) is still not exposed |

## Fixed: responses were sent before their transaction committed

Found by chasing an intermittent CI failure in the caregiver-app job, not by review. Recorded
in full because the mechanism is not obvious and the same shape can come back.

**What was wrong.** `db_session` is a FastAPI dependency with `yield`, wrapping a
`session.begin()` block that issued the `COMMIT` on exit. FastAPI runs a `yield` dependency's
exit code *after the response has gone out on the wire*, so every write endpoint answered the
client before its own transaction had committed. Reproduced over a real socket against uvicorn:
the client received `200` in 3 ms and an immediate follow-up read could not see the write; the
commit landed 300 ms later.

Two consequences, in increasing order of seriousness:

1. **Read-after-write was not guaranteed.** A client that created a resource and immediately
   used its id could get a 404. That is what the e2e seed kept hitting — `POST /caregivers`
   returning 201 and the very next call 404ing on that id. The seed already carried a defensive
   check whose comment guessed at "missing or merely invisible to the reading transaction"; it
   was the latter.
2. **A failed commit could not be reported.** The response was already sent, so no status code
   was left to change. Reproduced: with the commit forced to raise, the client received
   `200 {"status": "clocked_in", "evv_record": "created"}` while the server logged the
   rollback. A caregiver told their clock-in was recorded when it was not — the same class of
   bug as the 409 handling fixed in the outbox, in the opposite and more dangerous direction.

**The fix.** The unit of work moved in front of the response. `db_session` opens the session,
publishes it on `request.state.unit_of_work`, and no longer commits; the request middleware —
which already owns authentication, rate limiting, and revocation, and which still holds the
response — commits after the handler and before answering. A commit that fails now replaces the
response with a 500 `COMMIT_FAILED` whose message states that nothing was changed, which is
true, so retrying is safe.

The rollback deliberately stayed in the dependency. An exception unwinds through the teardown
before any response exists, so a handler that raises has its transaction discarded on the way
past — which is what makes the middleware's "is this session still in a transaction?" test mean
exactly "did this request succeed?". A transaction that a handler deactivated by swallowing a
database error is also refused rather than quietly rolled back behind a success response.

**How it is held.** `tests/test_transaction_boundary.py`, and the tests are the point:

* The read-after-write test runs over a **real TCP socket**, because the in-process ASGI
  transport the rest of the suite uses waits for the whole application coroutine — teardown
  included — before returning the response, and so serializes away the exact race. A test on
  that transport passed against the broken code.
* It slows the commit and asserts *both* that the POST took at least that long and that the
  immediate read succeeded. The timing assertion is what catches a regression that stops
  routing through `AsyncSession.commit` — which the original `session.begin()` did, committing
  through SQLAlchemy's synchronous `SessionTransaction` and slipping past the patch, leaving
  the read to pass on luck. Both assertions fail against the pre-fix code; verified by
  reverting it.

`tenant_session` remains, with commit-on-exit, for background jobs, scripts, and tests, which
have no response to race.

## Suggested next steps

1. **Run the caregiver app on real devices.** It is verified in Chromium at a phone viewport
   against a real API, which is a much stronger position than unexecuted code but is not the
   same as iOS Safari, a real GPS chip, and a genuinely bad connection. Decide native
   packaging at the same time, since iOS push and background sync depend on it.
2. **Observability.** There is now a component whose failure is invisible from the outside: a
   degraded rate limiter still answers every request, just with the wrong ceiling. It logs, but
   nothing collects the logs, and the same is true of the EVV anomaly counter and the bias
   audit. Structured logging exists; metrics, traces, and somewhere to send them do not.
3. **First real EVV integration** for one state, end to end through that vendor's sandbox.
   This is the assumption most likely to be wrong, and the cheapest time to find out is now.
4. **Engage compliance counsel**, and run the bias audit on real outcomes before the ranking
   model influences actual hiring. The tooling exists; the audit does not.
5. **Register a real routing provider.** The `RoutingAdapter` interface and registry
   exist; only the haversine approximation is implemented. This is now a one-class change.
6. **Job-board and background-check integrations**, behind the adapter interfaces
   `07_Integration_Specifications.md` Section 1 requires.
