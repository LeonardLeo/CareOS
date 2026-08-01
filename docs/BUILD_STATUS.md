# CareOS — Build Status

**Scope:** what exists in this repository, assessed against the milestone table in
`10_Roadmap_Milestones_Team_Plan.md`.

**Why it exists:** `12_Engineering_Handoff_Guide.md` Section 3 advises against assuming a
documented milestone was completed. This file is the inventory to check instead.

**Maintenance:** drift between this file and the code is a bug
(`12_Engineering_Handoff_Guide.md` Section 5).

**Last updated:** 2026-07-31
**Assessed by:** build increment 19 (MFA enforcement, with three post-ship fixes)

---

## Summary

| | |
|---|---|
| Phase | 1 — AI Workforce Engine |
| Milestone reached | **M0–M4 backend complete.** M5 (Phase 1 GA) blocked on clients and compliance review |
| Stack | Python 3.11, FastAPI, PostgreSQL 16, SQLAlchemy 2 async, Alembic |
| Tests | 394 API tests against real PostgreSQL and Redis, 19 sync-engine unit tests, 10 browser end-to-end tests including genuinely-offline clock-in |
| Lint / types | `ruff` and `mypy` clean |
| Clients | Admin web app and caregiver app both built and working. The caregiver app is an installable PWA, not React Native |
| Compliance review | **Not performed** |

**Stack choice.** `03_Technical_Architecture.md` Section 2 left TypeScript/NestJS and
Python/FastAPI open. Python was chosen on two grounds: the repository already carried a Python
`.gitignore`, and that section prefers Python where the AI/ML inference layer shares a language
with the app layer. Ranking, ambient extraction, and claim scrubbing all sit there.

## Milestone assessment

| Milestone | Target | Status |
|---|---|---|
| **M0 — Foundation** | Month 1 | **Done.** Tenant/agency model, auth, RBAC, CI/CD, containerized local stack |
| **M1 — Recruiting alpha** | Month 3 | **Backend done.** Job postings, normalized applicant intake, guarded stage transitions, applicant→caregiver hire, funnel report with conversion. No job-board integration |
| **M2 — Onboarding & credentialing** | Month 5 | **Mostly done.** Credential CRUD, expiration dashboard with 7/30/60-day buckets, exclusion-check endpoint, hard scheduling gate. No vendor integration, no digital onboarding paperwork |
| **M3 — Scheduling & EVV core** | Month 7 | **Done, both ends.** Care plans, RRULE visit generation, assignment with compliance gates, clock-in/out, EVV adapter layer, transmission worker with backoff and escalation. Caregiver app closes the loop with offline clock-in/out and an on-device outbox, verified exactly-once |
| **M4 — AI ranking + gap-fill** | Month 8 | **Backend done.** Explainable ranking for applicants and shift matching, gap detection, fair-hiring feature allowlist, bias-audit tooling |
| **M5 — Phase 1 GA** | Month 9 | **Not started.** Requires M1–M4, both clients, and compliance sign-off |

## What is built

### Foundation and cross-cutting

| Area | State |
|---|---|
| Multi-tenancy | `agency_id` on every tenant table via `TenantMixin`. RLS enabled and forced on all tenant tables. `careos_app` (no `BYPASSRLS`) for request handling; a narrow `careos_auth` for pre-tenant operations |
| RBAC | All six roles, enforced by a shared dependency. Startup refuses to boot if any route lacks an access declaration. The auditor role is read-only by HTTP method, centrally |
| Audit log | Append-only by database grant. Covers writes and PHI reads. Written in the caller's transaction |
| Field-level encryption | AES-256-GCM for tax ID, DOB, street address, and the TOTP secret, with a random per-encryption nonce. Key required from the environment outside local and test |
| Idempotency | `Idempotency-Key` enforced on side-effecting mutations, with replay, body-mismatch rejection, and in-flight conflict handling |
| Error envelope | One shape for every failure, including FastAPI validation errors |
| Rate limiting | Shared Redis token buckets, so published limits are cluster-wide. Fails degraded behind a circuit breaker. Clock-in and clock-out are exempt per `05_API_Specification.md` Section 9 |
| Metrics and alerting | Prometheus endpoint behind a bearer token, alert rules with promtool unit tests, Alertmanager routing and inhibitions |
| Data export | `POST /agencies/{id}/export` returns a ZIP of one CSV per table, plus a manifest. Owner-admin only. Table list derived from schema metadata, so a table added later is exported without anyone remembering |

**Session revocation and offboarding.** `08_Security_Architecture.md` Section 6 requires an
admin to cut off a terminated caregiver immediately, including PHI cached on their device. Only
the device half existed: the app wiped its cache when the API rejected a token, and the API
could not reject one.

- `app_user.sessions_revoked_at` is a watermark. Any access token issued at or before it is
  refused. Chosen over a token denylist, which would retain every issued `jti` until expiry.
- Costs one query per authenticated request. The requirement says "immediately", and any cache
  defines a window in which a terminated caregiver still has access.
- Tokens carry a microsecond `iat_us` claim alongside the whole-second `iat`. The first version
  compared against `iat` and locked users out of signing back in for up to a second.
- `POST /caregivers/{id}/terminate` sets `terminated` and disables the linked login in one
  transaction. A reason is required and audited.

**Account disablement.** Distinct from revoking sessions, and the distinction was a hole.
Revocation invalidates tokens in hand and leaves the password working. Termination did only
that, so a terminated caregiver could sign back in seconds later while the audit log recorded
that access had been removed. The test proving it was written first and answered 200 where it
asserted 401.

- `disable_user` sets `status` and the revocation watermark in one transaction. `status` stops
  the login path issuing tokens and the refresh path renewing them; the watermark kills tokens
  already issued. Either half alone leaves a gap.
- Enabling does not clear the watermark. Clearing it would revive every token issued before the
  disablement, including one on a returned phone.
- Refused for your own account, and for the agency's last enabled owner/admin. The second guard
  is unreachable through current routes and is held at the service boundary.
- A reason is required, stored on the row, and audited.
- `ACCOUNT_INACTIVE` is a distinct error code, so both apps say the account was disabled rather
  than "invalid email or password". The password is verified first, so only someone holding
  valid credentials sees it.

### Multi-factor authentication

Required by `08_Security_Architecture.md` Section 1 for owner/admin, clinical supervisor, and
billing/RCM. `app_user.mfa_enrolled` existed from the first migration with nothing setting or
reading it.

| Property | Implementation |
|---|---|
| TOTP | RFC 6238, written rather than depended on, verified against the published test vectors so interoperability with real authenticator apps is checked rather than assumed. SHA-1, because essentially no app implements the SHA-256 variant the RFC permits |
| Single-use codes | The last accepted counter is stored, so a code cannot be presented twice inside its own window. Applies across enrolment and login, which is why confirming enrolment returns a session |
| Recovery codes | Ten, hashed with the password hasher, single-use. Without them a lost phone locks the agency's only owner/admin out of the agency |
| Secret at rest | Encrypted with the same field key as DOB and tax ID |
| Enforcement | Central, in `requires()`, with exactly two `mfa_exempt` routes: the enrolment pair. `/auth/refresh` re-derives state from the user rather than trusting the presented token |
| Caregivers | Cannot enrol. The caregiver app has no field for a code, so enrolling would lock them out of the phone they clock in with |
| Production gate | `CAREOS_MFA_REQUIRED`. Production refuses to boot without it. Off by default, because enabling it turns every existing privileged session into an enrolment prompt |

**Three defects found after the first version shipped**, each by exercising the feature rather
than reading it, and each invisible to a passing test suite:

1. **A stolen session could replace the second factor.** `POST /auth/mfa/enroll` needed only a
   token. An attacker enrolled their own authenticator, received ten fresh recovery codes, and
   left the owner locked out. Re-enrolment now requires proving the factor in force. A recovery
   code is accepted, so a lost phone still leads somewhere.
2. **The enrolment screen re-minted the secret on every render.** The page called the enrolment
   endpoint directly, and that endpoint replaces the stored secret by design. A refresh, or the
   redirect after one mistyped code, invalidated the secret the user had just scanned. The
   secret is now minted once by a POST and held in an httpOnly cookie until confirmed.
3. **Every ordinary sign-in wrote a "login failed" audit row.** An enrolled user's first request
   cannot carry a code. One false failure per person per day buries the real ones. A wrong code
   is still recorded.

**No QR code.** The enrolment screen shows the secret and the `otpauth://` URI as text, which
every authenticator accepts by manual entry. Rendering a QR needs an encoder the admin app does
not have. A real usability gap.

### Scheduling and EVV

- Clients, care plans, RRULE-based visit generation, idempotent over overlapping windows.
- Assignment gates: OIG/GSA exclusion (hard, publicly-funded payers only), credential expiry
  checked against the service date, employment status, double-booking.
- EVV adapter layer: an `EVVTransmissionAdapter` interface, a per-state registry, a
  config-driven REST adapter with Sandata, HHAeXchange, and Tellus mappings, and a loopback
  adapter for dev and test. Production use is blocked until `sandbox_validated` is set.
- Transmission worker: exponential backoff, `SKIP LOCKED` so concurrent workers cannot
  double-transmit, escalation to a compliance exception after retries are exhausted.
- Clock-in and clock-out support offline replay dedup. Telephony and manual-exception capture
  are first-class paths.

### Compliance rules engine

Built generically in Phase 1, as `02_Product_Requirements_Document.md` Section 6 requires, so
Phase 2's copilot and Phase 3's scrubber extend it rather than reimplementing it. Six Phase 1
visit rules, per-agency enable, severity, and threshold configuration. One failing rule cannot
suppress the others.

### Recruiting and ranking

- Job postings. Applicant intake normalized at the boundary, so no job board's schema reaches
  the domain model.
- Guarded pipeline transitions: a rejected applicant is not silently revived, and `hired` is
  terminal. Hiring converts an applicant into a caregiver in `onboarding` with
  `exclusion_check_status = not_run`. Being hired and being clearable for a Medicaid visit are
  separate events.
- Funnel report with stage-to-stage conversion, counted cumulatively so rejected applicants
  still count at the top.
- Explainable ranking for applicants and shift matching, sharing one scorer. Every score carries
  its top three factors with human-readable rationales. A score without factors is rejected by a
  database check constraint.

### Fair hiring

`06_Compliance_and_Regulatory_Requirements.md` Section 5, enforced structurally:

- A closed feature allowlist. Anything unrecognised is refused. A denylist would only catch
  attributes someone thought to forbid.
- Named proxies refused alongside the attributes: ZIP code, graduation year, name, school,
  salary history, credit score, arrest record. Errors state which and why.
- Validation lives inside the scorer, so no caller can route around it. Applicant intake has no
  field for demographic data.
- Bias-audit tooling: adverse-impact ratios against the EEOC four-fifths screen, with a minimum
  group size so an underpowered sample reports `insufficient_data`. Demographic labels come from
  separately-held voluntary data; nothing in the schema stores an applicant's race or sex.

**Ranking shadow period.** `agency.ranking_display_enabled` defaults to false. While it is off
the scorer runs and persists — the audit needs those rows — and the API returns a null score, no
factors, no model version, and the applicant list in the order people applied. Ordering is part
of what is withheld, because the top of a list is a recommendation whether or not it carries a
number. Every ranking run records `ranking_displayed` in its audit row, so the shadow period is
evidenced when it happens rather than asserted later from a config value. The one endpoint that
ends it is owner/admin only and refuses unless a passing `ai_hiring_bias_audit` review is on
file; `inconclusive` does not count, since the usual reason an audit is inconclusive is a sample
too small to say anything. There is no endpoint to turn it back off.

### Background screening

`careos.integrations.screening`, built because `assert_assignable` gates publicly-funded
assignment on `exclusion_check_status` and nothing set that except an administrator checking the
OIG and GSA sites by hand — workable for twenty caregivers, not beyond.

- **Fails closed everywhere.** The registry raises rather than defaulting; the status mapping
  raises on any vendor status not explicitly mapped; a pending, unreadable, or unreachable result
  leaves the caregiver where they were. Nothing writes `cleared` except a vendor verdict of
  `clear`. The loopback adapter is refused outside local and test, and production will not boot
  configured to use it.
- **Async by construction.** Order returns 202 and clears nobody. A second order while one is
  outstanding is refused — these are billed per search and touch a real person's records.
- **Two worker jobs.** Verdict polling every five minutes; re-screens ordered daily against
  `exclusion_checked_at`, exclusion-list only, because a monthly full criminal-history bundle on
  every caregiver is not what the recurring obligation asks for.
- **A flagged caregiver with future visits raises a critical compliance exception** and keeps
  their visits. New assignments are already blocked by the gate; silently emptying five slots
  would leave five clients with nobody arriving and no record of why.
- Produces `background_check.completed`, which was in the published webhook contract with no
  producer. The payload carries a verdict, not the match detail — that is adjudication material
  for the employment decision-maker, not for a third party's inbox.

Verified by running it, and that run caught a defect the tests could not: the loopback adapter
kept its orders in instance memory, so the worker process — a different instance from the API
that placed the order — logged `No such loopback screening request` and could never have
resolved anything. A real vendor adapter holds no such state. The fake now encodes the verdict
in the request id and is stateless, pinned by a test that fetches from a second instance.

### Shift matching and gap-fill

- Suggestions reuse `assert_assignable`, so a caregiver who would be refused at assignment is
  never suggested.
- Factors: certification match, drive-time proximity, availability, continuity of care,
  overtime headroom. Overtime is a warning, not a block.
- Gap detection over unfilled visits starting soon, most urgent first.

### Credentialing

Credential CRUD plus an expiration dashboard bucketed at 7, 30, and 60 days. Already-expired
credentials are surfaced rather than filtered out: the caregiver is unassignable now.

### Caregiver app

Flow B works end to end: open the app, see today's schedule, tap into a visit, clock in, clock
out.

**Built as an installable PWA rather than React Native.** `03_Technical_Architecture.md`
Section 2 names "React Native or Flutter", and the same row says the offline-first library
choice, not the framework, is the critical decision. A React Native app cannot be run or
verified in this environment: with no simulator, the offline clock-in path would have shipped
unexecuted, which on this surface means shipping an unverified claim about whether caregivers
get paid. Everything in `src/lib` — outbox, sync engine, retry policy — is free of React and DOM
imports and is reusable behind a React Native shell.

Offline behaviour, verified in a real browser with the network cut:

- A clock-in is written to IndexedDB before the UI acknowledges it. The recorded time is the tap,
  not the delivery.
- Each action carries a device-generated uuid, sent as both `client_local_uuid` and
  `Idempotency-Key`, reused on every retry.
- The queue flushes on foreground and on regained connectivity.

| Limitation | Detail |
|---|---|
| **Token reachable from JavaScript** | The admin app keeps its token in an httpOnly cookie; this one cannot, because the device replays its own queued writes. Mitigated with `sessionStorage` rather than `localStorage`, no stored refresh token, and cached PHI wiped on sign-out. A real reduction in XSS resistance |
| **Telephony (IVR) fallback** | `capture_method: telephony` is accepted by the API and modelled throughout. No phone system is wired up. A caregiver with no smartphone is not served |
| **No push notifications** | Flow A step 4, accepting a shift offer in one tap, needs push and a shift-offer endpoint. Neither exists. iOS delivers web push only to a home-screen-installed PWA, which bears on the framework decision |
| **No background sync** | The queue flushes when the app is foregrounded or regains connectivity, not while closed |
| **Not verified on real devices** | Chromium at a phone viewport. No iOS Safari, no Android Chrome, no real GPS, no genuinely degraded network |

### Agency admin web app

Next.js App Router, server-rendered. Screens: dashboard, scheduling board with gap queue and
ranked suggestions, clients and care plans, recruiting funnel, credentialing renewal queue,
compliance review standing, compliance-exception queue, users, security and MFA enrolment.

- The access token never reaches the browser. It lives in an httpOnly cookie and every API call
  runs server-side.
- Every AI suggestion shows its reasoning inline, per `09_UX_Design_and_User_Flows.md`
  principle 4. There is no bare score in the UI.
- Fully localized English and Spanish, resolved server-side. Parity is compiler-enforced;
  `npm run i18n:check` fails on user-facing strings that bypass the translator, and runs in CI.
- Route handlers redirect with a code rather than an English sentence, so the sign-in screen
  answers in the reader's language.

**Information design.** An operational console for someone working a live gap under time
pressure. Recessive chrome, data as the only loud thing on screen. Each view starts from the
data's job: coverage is a ratio against a limit, so a meter; the recruiting funnel is an ordered
scale, so a validated ordinal ramp; a match score is magnitude, so a bar; the schedule is
occupancy over time, so a timeline. The palette was run through a validator against both
surfaces rather than chosen by eye: adjacent CVD ΔE 9.1 light and 8.4 dark against an ≥8 target,
normal-vision ΔE 22.9 and 19.8 against a ≥15 floor, and the ordinal ramp passes
monotone-lightness with ≥0.06 ΔL between steps in both modes.

### Compliance-exception queue

`06_Compliance_and_Regulatory_Requirements.md` Section 4 requires exceptions be worked, not only
recorded. Open findings list severity-first — critical, warning, info, oldest first within each
band — with a resolution that writes `compliance_exception_resolved` against the resolving user.
The nav carries the open count.

### Compliance operations

Reviews are rows in `compliance_review`, so overdue reviews are computable rather than
remembered. `GET /v1/agencies/{id}/compliance-reviews` enumerates the full cadence including
reviews never performed; a gap shows as `never_performed` rather than being absent. The bias
audit writes its outcome here when it runs.

### Outbound webhooks

`05_API_Specification.md` Section 7, built as a transactional outbox with a delivery worker.

| Property | Implementation |
|---|---|
| Payloads | Identifiers and status only. `assert_payload_carries_no_phi` raises at enqueue on a PHI-shaped field name at any depth, matching on the key rather than the value |
| Signing | HMAC-SHA256 over a signed timestamp, so a captured delivery cannot be replayed past the published 300-second window. The receiver-side `verify` lives in the codebase, so the suite tests the algorithm an integrator will implement |
| SSRF | Checked at subscription time and again immediately before the connection, because DNS can answer differently. Redirects are not followed |
| Failure | Six attempts with widening backoff, then abandoned but kept. Twenty consecutive failures disables the subscription with a written reason |
| Concurrency | Due deliveries selected `FOR UPDATE SKIP LOCKED` |

Producers exist for `evv.transmission_acknowledged`, `evv.transmission_rejected`, and
`credential.expiring_soon`. **`background_check.completed` and `claim.status_changed` are
defined and never fire** — the first needs a screening vendor, the second is Phase 3. Stated
here because a subscriber reading the enum has no other way to know.

`credential.expiring_soon` is calendar-driven, so `enqueue(..., dedupe_on=...)` sends a notice
once per credential per horizon. Crossing into a tighter horizon is a new event. Without it a
daily job re-announces every expiring credential every day.

### Background workers

`python -m careos.workers.runner`, its own container in the local stack. This closed the largest
gap in the system: EVV transmission, webhook delivery, and the credential-expiry announcer were
written, tested, and green in CI while nothing called any of them. Screening polling and
re-screening joined later, for five jobs.

- **No broker.** Five coroutines taking an `agency_id`. What was missing was a loop, a clock,
  and a way not to do the work twice. The durable queue is already in Postgres.
- **Advisory lock per (job, agency).** Replicas divide the tenants; no two work the same agency
  at once. `SKIP LOCKED` stops duplicate sends. The lock is what makes the read-then-write
  credential announcer safe, since two workers can otherwise both read "no notice yet".
- **Per-agency isolation.** Each job is wrapped per agency per tick. An exception is counted and
  logged, a hang is abandoned after `JOB_TIMEOUT_SECONDS`, and the loop continues.
- **Own metrics port, same bearer token as the API's.** A worker reporting through the API would
  go silent in the case the alerts exist for: API healthy, worker dead. `CareOSWorkerDown`
  covers the process being gone; `CareOSEvvTransmissionStalled` covers a process that answers
  scrapes while its pass is wedged. Both have promtool tests, including the negative one:
  `skipped_locked` is normal with two replicas, and a rule counting it would page on a healthy
  deployment.
- **SIGTERM stops between agencies**, not mid-delivery. Measured at about 2 seconds.

Verified by running it: a real receiver on localhost, a real queued event, the runner started as
a process, a signed delivery arriving with nothing else driving it. That run caught a defect no
test could — the runner registered only the models it names, so a webhook delivery's foreign key
to `agency` would have raised `NoReferencedTableError` on the first write in a deployment. Fixed
by importing the model registry, pinned by a subprocess test.

### Public site

`apps/site` — fifteen pages as a static Next.js export, its own app rather than a route in the
admin console: home, product, security, about, careers, contact, a policy index, and eight
policies — privacy, terms, cookies, HIPAA, acceptable use, availability, subprocessors,
accessibility.
No session, no API call, nothing personalised, so it needs no server: it is a directory of
files that stays up when the API does not, which matters because a marketing page that goes
down with the product cannot tell anyone the product is down. No font CDN, no icon library,
no analytics — a page with no third-party requests loads on a bad connection and leaks
nothing about who visited.

Every figure carries its source in the markup, and it claims nothing about customers or
results, because there are none. The product page has a "what is not built" section and the
security page an "open items" one, for the same reason: a capability list with no edges is one
a buyer assumes is padded.

Typography is Fraunces and Inter, self-hosted as npm packages — no font CDN, no icon library,
no analytics, no third-party request of any kind. The one illustration is the product's own
coverage board with the unfilled shifts in red, which is the same argument the console makes
to a scheduler.

The policy set is written to be read rather than to be scrolled past, and each page states
what is *not* done: no counsel review, no incident-response plan, no penetration test, no
signed subprocessor agreements, no service level agreement — because the pager receivers are
still placeholders and an availability guarantee you cannot detect yourself breaking is not a
guarantee. The cookie page says the site sets nothing, which was checked in a browser (no
cookies, no storage, one host) rather than assumed.

Three scripts check the site, all reading their page list from the built `sitemap.xml`, which
is itself generated from the same content module the header, footer, and policy index render —
so a page cannot be added and audited by nothing.

`scripts/check-routes.mjs` asserts the export and the sitemap describe the same pages. Both
drifts it catches are silent: a published page nothing links to, and a navigation entry
pointing at a route that was never built.

`scripts/audit.mjs` drives every page in a real browser at two widths and reports horizontal
overflow, failed requests, and elements left in the pre-reveal hidden state. The last is the
one that matters: a stuck element is invisible, not merely un-animated. Two defects came out
of running it — display headings rendering near-white on near-white cards inside the inverted
section, and a harness that reported the whole document unrevealed because `scroll-behavior:
smooth` meant a scripted scroll loop moved the page 231px out of 4612.

`scripts/a11y.mjs` runs in CI and fails the build: contrast on every rendered text node
against the background actually behind it, real Tab-key traversal of the skip link, accessible
names, form labels, heading order, landmarks, `lang`, and `alt`. It found four things a green
test suite did not. Muted text at `#7c746a` measured 3.97:1 — every eyebrow, figure source,
and field hint on the site failed AA. The skip link scrolled but never moved focus, because
`main` had no `tabindex="-1"`, so the next Tab went back into the nav. A section eyebrow that
passed at 8.2:1 in light mode measured 4.0:1 in dark, since the same colour mix is symmetrical
and contrast is not — which is why dark is a full pass rather than a spot check. And the
harness's own colour parser read `color(srgb 0.97 0.96 0.94)` on a 0-255 scale, reporting
near-white as near-black; it accused the site header of 1.18:1 before it accused itself. Each
check was then mutation-tested by breaking the page and confirming it failed.

### EVV reconciliation and conformance

Two controls from `13_Phase_1_Launch_Plan.md` 5.1, both buildable before a vendor sandbox.

**Reconciliation** (`compliance_rules/reconciliation.py`, daily worker job) compares delivered
visits against their EVV records. The four divergences it reports are all states the rest of
the system calls healthy: a delivered visit with no record at all — which has nothing to retry
and is invisible to every alert, since they are keyed on a record — one submitted and never
acknowledged, one queued and never sent, and a rejection nobody resolved. Exceptions close
themselves when the divergence resolves, because a queue full of already-fixed problems is one
that stops being read.

**Conformance fixtures** (`integrations/evv/conformance.py`, `tests/fixtures/`) pin the exact
bytes each adapter puts on the wire for four shaped records: a normal visit, a telephony
capture with no coordinates, a manual exception, and a visit crossing midnight. A state's field
map is a dict of a dozen strings, and renaming one is a two-character edit nothing else would
catch. The remaining two records the plan asks for — a cancellation and a correction — are
recorded as *not expressible*: both are separate message types and the adapter interface has
only `submit`. Guessing at each vendor's vocabulary would produce fixtures that look like
coverage and pin nothing.

The response half of the fixture is empty, and a test asserts it stays that way until a real
sandbox run. A recorded acknowledgement nobody received would make the suite assert that our
own guess is stable.

### Schema

All tables from `04_Data_Model_and_Schema.md` exist, in the documented migration order,
including the Phase 2 and Phase 3 tables. Those ship unused so that visits recorded today can be
traced onto a claim line later without a backfill.

## Fixed defects worth recording

Four increments, four defects, each found by running the feature rather than reading it. In
every case the test suite was passing and the code read correctly.

**Responses were sent before their transaction committed.** FastAPI runs `yield` dependency
teardown after the response is sent, so the commit happened once the client already held a 200.
A failed commit was reported as success: a caregiver told their clock-in was recorded when it
was not. The unit of work moved in front of the response. `db_session` publishes the session on
`request.state.unit_of_work` and no longer commits; the middleware commits after the handler and
before answering. A failed commit now replaces the response with a 500 `COMMIT_FAILED` stating
that nothing was changed.

The test runs over a real TCP socket. The in-process ASGI transport the rest of the suite uses
waits for the whole application coroutine, teardown included, and serializes the race away; a
test on that transport passed against the broken code.

**Middleware-built responses carried no CORS headers.** `CORSMiddleware` was registered before
`request_context`, and Starlette runs the most recently added middleware first. Every response
the middleware built without calling the router — a 429, an auth failure, a failed commit — went
out with no `Access-Control-Allow-Origin`, and a browser blocks such a response entirely. Fixed
by registering CORS last.

The same ordering defeated the clock-in rate-limit exemption. A cross-origin POST carrying
`Authorization` is preceded by an `OPTIONS` preflight, which matched no declared route method
and resolved to the standard tier. Once an agency's budget was spent the preflight returned 429,
and a browser that cannot complete a preflight never sends the request. Section 9's one hard
rule was defeatable through its own preflight.

**A terminated caregiver could sign back in.** See account disablement above.

**A stolen session could replace someone's second factor.** See multi-factor authentication
above.

## What is deliberately stubbed

| Area | State | What it needs |
|---|---|---|
| **Authentication** | Local Argon2 password hashing, with TOTP MFA built and enforced | `08_Security_Architecture.md` Section 1 calls for a managed OIDC provider. `app_user.auth_provider_id` is the seam. The password path is deleted when the IdP lands, and MFA moves with it |
| **EVV vendor field maps** | Structurally correct, contents provisional | Confirmation against current vendor documentation during sandbox validation |
| **EVV state assignments** | Seeded, marked `UNVERIFIED` | Confirmation per state before operating there (`06_Compliance_and_Regulatory_Requirements.md` Section 1) |
| **Service codes** | A handful of `T1019`-style rows | Population per state and payer contract, with a certified billing consultant |
| **Object storage** | `*_s3_key` columns exist; nothing writes them | An encrypted S3 bucket and an upload path |
| **Redis** | Holds the shared rate-limit buckets and nothing else | Deployment as a real dependency: HA, monitored, eviction policy set so buckets are not dropped silently under memory pressure. A single node turns every limit back into a per-instance one |
| **Drive time** | `HaversineRoutingAdapter`: straight-line distance with a circuity correction, marked `is_estimate` throughout | Adequate for ranking candidates against each other. A real routing provider before travel time is quoted to a caregiver or paid on a timesheet |

## Not started

| Area | Detail |
|---|---|
| **Native mobile packaging** | The caregiver app is a PWA. App Store and Play distribution, iOS web push, and background sync all depend on revisiting that |
| **Telephony (IVR) clock-in** | Accepted by the API, modelled end to end, no phone system attached. A caregiver without a smartphone cannot clock in |
| **Hosted-LLM inference** | Ranking is a deterministic weighted scorer behind a `Scorer` protocol, which `03_Technical_Architecture.md` Section 5 names as the intended first step. Ambient documentation and claim scrubbing are unbuilt |
| **Third-party integrations** | Background check, job boards, STT, clearinghouse, payroll, legacy EHR import |
| **Phase 2 and Phase 3 behaviour** | Tables only, by design |
| **Staged export for large agencies** | The synchronous export refuses above `MAX_EXPORT_ROWS` rather than risking the instance. An agency past that ceiling needs a job writing to object storage |
| **Tracing** | No distributed tracing on the EVV and scheduling paths. Metrics and alerting answer *that* a clock-in was slow; nothing answers *why* |
| **A real pager** | Alert rules, routing, and local delivery are built and tested. The receivers are placeholders, so an alert reaches a log line in a container. This is the remaining gap between the system and the 99.9% NFR |
| **Infrastructure-as-code** | No Terraform, no deployed environment |
| **Localization beyond English and Spanish** | Both apps are fully EN/ES, which is what the PRD requires at MVP. A third language is a dictionary; nothing in the mechanism assumes two |

## Compliance and security posture

| Item | Status |
|---|---|
| Healthcare-compliance counsel review | **Not performed.** Required before Phase 1 launch |
| BAAs with subprocessors | **None.** No PHI-touching vendor is integrated |
| AI hiring bias audit | **Runnable and self-logging. Never run on real outcomes.** `python -m careos.scripts.run_bias_audit` performs one, records it to the compliance log, and exits non-zero on adverse impact so it can gate a release. Requires demographic labels supplied separately, plus employment-counsel review |
| Incident-response plan | **Not written.** Required before Phase 1 launch |
| SOC 2 | **Not started.** Several underlying controls exist — access management, audit logging, encryption. No evidence collection |
| Penetration test | **Not performed** |
| Brute-force protection | **Built and tested.** 10 login attempts per minute per account and address, 30 per address across accounts, counted before the password is checked. Account lockout is not implemented: the limiter slows an attacker rather than stopping one, and a lockout policy needs a decision about the denial-of-service it enables |
| EVV abuse detection | **Detection only.** Volume per caregiver is counted and logged above a ceiling no human reaches. It is not surfaced in the exception queue. Device fingerprinting and geo-velocity are not built; the app does not send a device identity |
| Offboarding | **Built and tested.** Terminating a caregiver disables the account rather than only revoking sessions. Disabling and enabling are on the Users screen, both audited. A disabled account is refused at login and at refresh |
| MFA | **Built and enforced** for owner/admin, clinical supervisor, and billing/RCM. Production refuses to boot with the requirement off |

## Suggested next steps

Ordered by what blocks a first real agency, not by effort. Everything above this line is built
and verified. Everything below is a decision, a credential, or a signature.

### Before a single real agency can be onboarded

| # | Item | What it needs |
|---|---|---|
| 1 | **Deploy the stack** | Terraform for AWS staging and production is written (`infra/`) and validated in CI; nothing has been applied. Needs an AWS account with a signed BAA, the state bucket and lock table, a validated ACM certificate, and the `careos_app` / `careos_auth` roles created against the fresh instance. The first real `plan` is where quotas and name collisions surface |
| 2 | **Provision the identity provider** | `08_Security_Architecture.md` Section 1 calls for managed OIDC. The local password path exists so the system runs before that, and `app_user.auth_provider_id` is the seam. MFA moves to the provider with the rest of authentication. Do not build further onto the local path |
| 3 | **First real EVV integration, one state, through the vendor's sandbox** | The assumption most likely to be wrong and the cheapest to test. Adapter layer, field maps, and transmission worker are built; the field maps are provisional and the state assignments are `UNVERIFIED`. A wrong map surfaces as a rejected claim months later, not as a test failure |
| 4 | **Wire the pager to a real destination** | Rules, routing, inhibitions, and local delivery are tested end to end. The receivers are placeholders. A PagerDuty routing key or a Slack webhook makes this a config change. Until then nothing meets the 99.9% NFR |
| 5 | **Compliance counsel review, incident-response plan, BAAs** | `06_Compliance_and_Regulatory_Requirements.md` Section 9 requires the first before Phase 1 launch. The second is unwritten. The third is not yet needed only because no PHI-touching vendor is integrated, which changes the moment item 3 happens |
| 6 | **Run the bias audit on real outcomes** | Before the ranking model influences a hire. The shadow period that makes this possible is built — `agency.ranking_display_enabled` defaults to false, the scorer runs and persists, and no score, factor, or model-derived ordering reaches a screen until a passing `ai_hiring_bias_audit` is on file. What is missing is a first cohort, voluntary demographic labels held separately, and employment-counsel review |

### Highest-value engineering

| # | Item | Note |
|---|---|---|
| 7 | **Real-device testing for the caregiver app** | And the native-packaging decision with it. Offline clock-in is verified in Chromium at a phone viewport against a real API with the network cut. That is not iOS Safari, a real GPS chip, and a tunnel. iOS web push and background sync depend on packaging, so decide once |
| 8 | **Telephony (IVR) clock-in** | Accepted by the API, modelled end to end, no phone system. For agencies where a large share of the workforce has no smartphone, this is a blocker rather than a gap |
| 9 | **Tracing on the clock-in and EVV paths** | Metrics answer *that* a clock-in was slow. Nothing answers *why*. Instrumentation rather than infrastructure; the collector can come later |
| 10 | **Staged export for large agencies** | The synchronous export refuses above `MAX_EXPORT_ROWS` with a 413. An agency past that ceiling cannot get its data out, which is a portability commitment with a size limit. Needs the object-storage bucket the `*_s3_key` columns anticipate |
| 11 | **A QR code on the MFA enrolment screen** | The secret and `otpauth://` URI are text, which every authenticator accepts. Typing a 32-character secret into a phone is where people give up |
| 12 | **Extend MFA to schedulers** | `08_Security_Architecture.md` Section 1 asks for it next. One line in `MFA_ELIGIBLE_ROLES` and one in `MFA_REQUIRED_ROLES`. Caregivers stay excluded until the caregiver app can ask for a code |
| 13 | **A real routing provider** | `RoutingAdapter` and its registry exist; only the haversine approximation is implemented. Adequate for ranking candidates against each other, not for quoting travel time or paying it on a timesheet |
| 14 | **Job-board integration, and a background-check vendor** | Behind the adapter interfaces `07_Integration_Specifications.md` Section 1 requires. Screening is no longer manual-only: `careos.integrations.screening` has the interface, a registry that raises rather than defaulting, async result handling, a re-screening job, and a flagged-while-scheduled compliance exception. What is left is one adapter class for a chosen vendor, a contract, and a BAA |

### Deliberately not next

**Hosted-LLM inference.** Ranking is a deterministic weighted scorer behind a `Scorer` protocol.
`03_Technical_Architecture.md` Section 5 names that as the intended first step and warns against
building past it. An LLM slots in behind the same interface and the same fair-hiring allowlist
once there is real outcome data to evaluate against.

**Phase 2 and Phase 3 behaviour.** The tables ship unused by design, so visits recorded today can
be traced onto a claim line later without a backfill. Building the behaviour before Phase 1 has a
customer means guessing at requirements twice.

### A process note

Every defect fixed in the last four increments was found by running the feature, not by reading
it and not by adding tests to green code. In each case the suite was passing and the code read
correctly. Stand the feature up, use it as a person would, then write the test from what
happened. It is cheap, and its hit rate is better than review.
