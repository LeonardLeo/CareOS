# CareOS — Build Status

**Purpose:** the honest answer to "where is this actually?", assessed against the milestone
table in `10_Roadmap_Milestones_Team_Plan.md`. `12_Engineering_Handoff_Guide.md` Section 3
warns an incoming team not to assume any documented milestone was completed — this file
exists so that verification starts from a real inventory rather than from the roadmap's
intentions.

**Keep this current.** Drift between this file and the code is a bug
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
| Tests | 394 API tests against real PostgreSQL and real Redis instances, 19 sync-engine unit tests, 10 browser end-to-end tests including genuinely-offline clock-in |
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
- **Account disablement, and the defect that motivated it.** Revoking sessions and disabling an
  account are two operations, and until this increment only the first existed. Termination
  called it and stopped there — so a terminated caregiver, whose sessions had just been cut off,
  could sign in again a second later with the password they still knew and receive a fresh
  token. The feature returned 200 and wrote an audit row saying access was removed. **Verified
  before fixing**: the test written against the old code answered 200 where it asserted 401.
  - `disable_user` closes both doors in one transaction: `status` stops the login path issuing
    tokens and the refresh path renewing them, and the revocation watermark kills the tokens
    already out. Either half alone leaves a hole — status only, and a disabled account keeps
    working for the life of its access token; watermark only, and that is the defect above.
  - Enabling does **not** clear the watermark. The obvious shortcut would resurrect every token
    issued before the disablement, including the one on the phone that was handed back.
  - Refused for your own account (unrecoverable without support; revoking your own sessions is
    the reversible thing you probably wanted) and for the agency's last enabled owner/admin. The
    second guard is unreachable through today's routes — anyone else with permission to disable
    is themselves an enabled owner/admin, so the count is never zero — and is held at the
    service boundary rather than through a route where the test would pass for the wrong reason.
  - A reason is required, stored on the row, and audited. On the row as well as in the log
    because "why can this person not sign in?" is asked by whoever is looking at the user list.
  - **`ACCOUNT_INACTIVE` is its own error code.** A disabled user typing the correct password
    was told "invalid email or password", which sends them to reset a password that was never
    the problem. Both apps now say the account was disabled. This discloses nothing: the
    password is verified *first*, so only somebody holding valid credentials ever sees it, and a
    wrong password or an unknown address still returns the same indistinguishable
    `AUTHENTICATION_REQUIRED`.
  - Verified in a real browser end to end: disable from the Users screen, the row shows the
    reason, the target is refused at sign-in with the disabled message in both English and
    Spanish, a wrong password still gets the generic one, enable restores sign-in, and the
    owner's own row offers no disable button.
- **Data export** (`POST /agencies/{id}/export`). `06_Compliance_and_Regulatory_Requirements.md`
  Section 8 asks for export tooling as a first-class feature "not an afterthought", and the
  PRD's non-functional table makes it a portability requirement.
  - **Completeness is derived from the schema**, not from a list someone maintains. A table
    added later is exported automatically; a table left out must be named with a reason, and a
    test asserts the two sets cover every tenant table. A curated list goes stale invisibly —
    the export succeeds and the agency discovers the gap after migrating.
  - **Encrypted columns are exported decrypted**, under the name without the `_encrypted`
    suffix. Ciphertext keyed to a secret the agency does not hold is not portability. The
    archive is therefore a plaintext PHI extract, which is why it is owner-admin only —
    deliberately not the auditor, whose tenant-wide read access is not a licence to walk out
    with the whole data set — and why every export is audited with per-table row counts.
  - **Reads go through the tenant session**, so RLS decides the contents rather than a
    `WHERE agency_id = ...` clause that one refactor could drop. Verified by building the
    export on a privileged session instead and watching seven tests fail, the isolation one
    included.
  - Refuses above `MAX_EXPORT_ROWS` with a 413 naming the limit. Streaming was considered and
    rejected: a body generated after the status code is sent cannot report a mid-stream
    failure, which is precisely the defect removed from the write path one increment earlier.
  - The isolation test initially passed for the wrong reason — it searched the *compressed*
    archive bytes, where no plaintext appears, so "another agency's data is absent" could not
    fail. Caught only because the paired positive assertion failed the same way. It now
    searches every decompressed member.
- **Metrics** (`GET /metrics`, Prometheus exposition). Built because this system is full of
  things that degrade rather than break, and degradation left no outward trace:
  - **`careos_rate_limit_degraded`** is the one that justified the increment. A limiter that
    has lost Redis keeps answering every request while the cluster enforces N x the published
    ceiling; nothing in a response says so.
  - **`careos_evv_anomalous_volume_total`.** Section 9 asks for abuse detection *in place of*
    throttling on clock-in, so nothing is ever refused and the counter is the entire response.
    A counter nobody collects is not detection.
  - **`careos_evv_escalations_total`** — records that exhausted their retries and now need a
    person. Counted apart from rejections because the two need different humans: a rejection
    is a data problem for the agency, an escalation is an unattended compliance liability.
  - **`careos_request_commit_failures_total`**, **`careos_sessions_rejected_total{reason}`**
    (revoked sessions separated from ordinary bad tokens), and request counts and durations by
    route template and status.
  - **No label carries a tenant or a person.** Metrics outlive logs, are exported to systems
    with looser access control than the database, and land on dashboards many people can see.
    A test walks every registered collector and fails on a forbidden label, so a metric added
    later cannot quietly reintroduce one. Route *templates* rather than paths, for the same
    reason and because the concrete path is one time series per visit.
  - Gated by `CAREOS_METRICS_TOKEN` as a bearer token, compared in constant time; production
    refuses to boot without one. The route is `public()` in the RBAC sense because a collector
    has no agency and fits no role — inventing one would put a login in the monitoring path.
    That required the request middleware to skip JWT decoding for this path, since `authenticate`
    would otherwise reject a collector's non-JWT token before the endpoint could check it.
  - Verified against a live server rather than only in tests: the gauge read 0 with Redis up,
    1 after killing it mid-traffic, and 0 again once it returned.
  - **Deployment constraint:** one worker per container, scaled with replicas. The registry is
    in process memory, so several uvicorn workers behind one port would each keep their own
    counters and a scrape would hit whichever answered, undercounting by about the worker count
    with nothing to show for it. One process per container is the normal pattern and is right
    here — each replica is its own scrape target and the collector sums them — but it is the
    same shape of mistake as in-process rate-limit buckets, so it is recorded rather than
    assumed.
- **Alerting** (`ops/prometheus/alerts.yml`, `ops/alertmanager/alertmanager.yml`). Eleven rules
  across availability, compliance, security, and latency, in two severities — `page` means
  someone is being harmed now, `ticket` means someone looks today. Anything else would be a
  dashboard.
  - **The rules are unit-tested with `promtool test rules`, in CI.** The negative cases are the
    reason: a clock-in answering 409 "already clocked in" or 422 "compliance gate" must not
    page, because that is the system working correctly, and a rule that fires on ordinary
    traffic is how people learn to ignore a pager. Likewise an alert on a counter's *value*
    rather than its increase would fire forever after the first EVV escalation. Each test is
    named after the mistake it prevents, and each was verified by making that mistake and
    watching the test fail — matching 4xx, dropping the `tier="auth"` filter, alerting on the
    raw counter.
  - **A separate test asserts every metric named in a rule is one the API exports.** `promtool`
    cannot: its unit tests run against series written by hand in the same change, so a metric
    renamed in code leaves a rule that parses, tests green, and never fires. That test reads
    the shipped rule file rather than a fixture, and was checked by renaming a metric.
  - Alertmanager routing is validated *and* exercised — `amtool check-config` accepts a file
    that sends every page to the ticket receiver, so CI additionally asserts where each
    severity actually lands. Verified by misrouting `page` and watching only the second check
    catch it.
  - `make up` runs Prometheus, Alertmanager, and a sink container, so the local stack covers
    the whole path rather than stopping at "the rule is pending". The last hop is the one most
    likely to be broken and the only one configuration review cannot check.
  - **The receivers are placeholders**, and that is the honest limit of this: alerts reach a
    log line, not a person. See "Not started".
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

**Localization.** `02_Product_Requirements_Document.md` requires English and Spanish
at MVP.

- **The mechanism is complete and the shell is translated.** Dictionary with named-token
  interpolation and `Intl.PluralRules` for one/other variants — never a bare count dropped into
  a fixed sentence, which is how "1 credenciales vencidas" happens. Locale resolved on the
  *server* from a cookie, falling back to a properly parsed `Accept-Language` (quality values
  honoured, region subtags dropped, `q=0` treated as refusal), so the first paint is in the
  right language instead of flashing English and correcting itself. `<html lang>` follows the
  rendered language, which is what decides the voice a screen reader uses.
- **Locale parity is enforced by the compiler.** The Spanish dictionary is typed
  `Record<StringKey, string>` against the English one, so a key added to English and forgotten
  in Spanish fails `tsc` — which CI already runs. Verified by deleting a key and watching the
  build fail, rather than trusting the annotation.
- **All ten screens are translated.** 307 keys, both dictionaries complete.
  `npm run i18n:check` reports **zero** untranslated user-facing literals, down from the 200 it
  found at the start; it is the measure of done rather than a claim, and is deliberately noisy
  in one direction — anything it flags that is genuinely not user-facing goes in an `ALLOWED`
  list with a reason, so the exceptions are readable rather than a rule that quietly stops
  matching. Only three Spanish entries are byte-identical to their English: `CareOS`,
  `Auditor`, and `Medicare Advantage`, each legitimately the same word.
- **Verified against a running server, not only by inspection.** `Accept-Language: es-MX`
  renders Spanish with `<html lang="es">`; `es;q=0.9, en;q=1.0` correctly stays English, which
  is the case a first-tag-wins parser gets wrong; and the cookie overrides the header.
- Shared chart components take the translator as a prop rather than importing a global,
  because they render inside pages that resolve the locale per request.
- The switcher is a form POST rather than client-side state, matching sign-out beside it: the
  app ships no client bundle for its pages, and a control that silently does nothing without
  hydration is worse than a plainer one. Its `returnTo` is restricted to same-origin paths and
  rejects protocol-relative `//host` — an open redirect on an authenticated app is a phishing
  primitive, and that value comes from a form field.
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

### Outbound webhooks
`05_API_Specification.md` Section 7, built as a transactional outbox with a delivery worker.
Owner-admin registers a URL; events are queued in the transaction that caused them and sent
afterwards, signed with HMAC-SHA256 over a signed timestamp so a captured delivery cannot be
replayed past the published 300-second window. Five events are defined; three have producers
today (`evv.transmission_acknowledged`, `evv.transmission_rejected`, and
`credential.expiring_soon` via the credential job). **`background_check.completed` and
`claim.status_changed` are defined but never fire** — the first needs a screening vendor, the
second is Phase 3 — and that is stated here because a subscriber who sees them in the enum has
no other way to know.

Three properties are enforced rather than documented: payloads carry no PHI-shaped field at any
depth (`assert_payload_carries_no_phi` raises at enqueue, so a producer that tries fails its own
request); the SSRF check is repeated immediately before the connection rather than only at
subscription time, and redirects are not followed; and a subscription that has failed twenty
times in a row is disabled with a reason in words. See README → *Outbound webhooks* for why each
of those is a boundary rather than a nicety.

`credential.expiring_soon` is the one producer driven by the calendar rather than by a change,
so it carries deduplication: `enqueue(..., dedupe_on=...)` suppresses a repeat to a subscription
that already holds a matching delivery, keyed on the credential and the horizon but *not* on the
day count. Without it a daily job re-announces every expiring credential every day. Both halves
are pinned by mutation — removing the dedupe check fails two tests, dropping the horizon from
the key fails the one asserting that 30 days and 7 days are different events, and adding
`caregiver_name` to the payload (it sits right there on the dashboard row) fails four.

Delivery is driven by `careos.workers.runner`, which is its own process and its own container
(see *Background workers* below). Before that existed, this whole section described code that
ran only in tests.

### Multi-factor authentication
`08_Security_Architecture.md` Section 1 requires MFA for owner/admin, clinical supervisor, and
billing/RCM. `app_user.mfa_enrolled` had existed since the foundation migration with nothing
setting it or reading it — a column describing an intention.

- **TOTP against RFC 6238**, written rather than depended on, and checked against the published
  test vectors so what is verified is interoperability with real authenticator apps rather than
  self-consistency. SHA-1 on purpose: the RFC permits SHA-256 and no app implements it.
- **Single-use codes**, enforced by storing the last accepted counter. Applies across enrolment
  and login, which is why confirming enrolment returns a session instead of asking the user to
  sign in again with a code they have just spent.
- **Ten recovery codes**, hashed with the password hasher and single-use. Without them a lost
  phone locks the agency's only owner/admin out of the agency.
- **The secret is encrypted at rest** with the same field key as DOB and tax ID.
- **Enforcement is central**, in `requires()`, with exactly two `mfa_exempt` routes — the
  enrolment pair, which an unenrolled user must be able to reach. `/auth/refresh` re-derives
  the state from the user rather than trusting the presented token; without that a pending
  session could be laundered into a full one through an endpoint that never asks for a code.
  That bypass is pinned by its own test, and by mutation.
- **Caregivers cannot enrol.** A guard, not a policy: the caregiver app has no field for a
  code, so enrolling would lock them out of the phone they clock in with, discovered at a
  client's door. Extending to schedulers — which Section 1 asks for next — is one line.
- `CAREOS_MFA_REQUIRED` gates enforcement and **production refuses to boot without it**. Off by
  default because turning it on makes every existing privileged session an enrolment prompt.
- **Verified in a real browser** with enforcement on: sign in, land on the enrolment screen,
  enrol from the secret shown, reach the rest of the app on the session confirming hands back,
  then sign out and back in with a code — including the prompt that asks for one instead of
  claiming the password was wrong.

**Three defects found after the first version shipped, all by exercising it rather than reading
it.** Recorded because each one was invisible to a passing test suite:

1. **A stolen session could replace the second factor.** `POST /auth/mfa/enroll` needed only a
   token: an attacker with a session enrolled their own authenticator, received ten fresh
   recovery codes, and left the real owner locked out by a device they had never seen. That is
   MFA defeated by the exact thing it exists to survive. Re-enrolment now requires proving the
   factor in force — a TOTP code or a recovery code, spent the same way a login spends one —
   and a recovery code is accepted so that a lost phone still leads somewhere.
2. **The enrolment screen re-minted the secret on every render.** The page called the enrolment
   endpoint directly, and that endpoint replaces the stored secret by design, so a refresh —
   or the redirect after one mistyped code — silently invalidated the secret the user had just
   scanned. One typo became an authenticator that could never produce an accepted code. The
   secret is now minted once by a POST and held in an httpOnly cookie until confirmed.
3. **Every ordinary sign-in wrote a "login failed" audit row.** An enrolled user's first
   request cannot carry a code, and that was being recorded as a failed attempt — one per
   person per day, burying the rows an investigation would be looking for. A *wrong* code is
   still recorded, because that is somebody guessing at the second factor while holding the
   first.

**No QR code.** The enrolment screen shows the secret and the `otpauth://` URI as text, which
every authenticator accepts by manual entry and every password manager accepts by paste.
Rendering a QR needs an encoder this app does not have; it is a real usability gap, not a
solved one.

### Background workers
`python -m careos.workers.runner`, its own container in the local stack. This closed the largest
gap in the system: EVV transmission, webhook delivery, and the credential-expiry announcer were
all written, tested, and green in CI while **nothing called any of them**, so a deployment would
have queued EVV records that were never transmitted and webhook deliveries that were never sent.

- **No broker.** Three coroutines taking an `agency_id`; what was missing was a loop, a clock,
  and a way not to do it twice. The durable queue is already in Postgres — that is what the
  outbox pattern put there — so Celery would add a datastore to operate and a failure mode this
  system does not otherwise have.
- **Advisory lock per (job, agency)**, so replicas divide the tenants and no two work the same
  agency at once. `SKIP LOCKED` inside the workers stops duplicate sends; the lock is what makes
  the read-then-write credential announcer safe, since two workers can otherwise both read "no
  notice yet" before either writes. Scaling is a capacity decision, not a correctness one.
- **Per-agency isolation.** Each job is wrapped per agency per tick: an exception is counted and
  logged, a hang is abandoned after `JOB_TIMEOUT_SECONDS`, and the loop continues. One agency's
  misconfigured adapter must not stop four hundred others.
- **Its own metrics port, behind the same bearer token as the API's.** A worker reporting
  through the API's endpoint would go silent in exactly the case the alerts exist for — API
  healthy, worker dead. `CareOSWorkerDown` covers the process being gone and
  `CareOSEvvTransmissionStalled` covers the harder case: a process that answers every scrape
  while its pass is wedged. Both have promtool unit tests, including the negative one that
  matters — `skipped_locked` is the *normal* outcome once there are two replicas, and a rule
  counting it would page on a healthy deployment.
- **SIGTERM stops between agencies**, so a delivery is not cut mid-flight; measured at ~2s.

**Verified by running it**, not only by testing it: a real receiver on localhost, a real
queued event, the runner started as a process, and a signed delivery arriving with nothing
else driving it. That run also caught a defect no test could — the runner registered only the
models it names, so a webhook delivery's foreign key to `agency` would have raised
`NoReferencedTableError` on the first write in a deployment while every test passed. Fixed by
importing the model registry, and pinned by a subprocess test.

### Schema
All tables from `04_Data_Model_and_Schema.md` exist, in the documented migration order —
including the Phase 2 and Phase 3 tables, which ship unused so that visits recorded today can
be traced onto a claim line later without a backfill.

## What is deliberately stubbed

These are honest placeholders, not oversights:

| Area | State | What it needs |
|---|---|---|
| **Authentication** | Local Argon2 password hashing, with TOTP MFA built and enforced | `08_Security_Architecture.md` Section 1 calls for a managed OIDC provider. `app_user.auth_provider_id` is the seam; the password path is deleted when the IdP lands, and MFA moves to the provider with it |
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
- **Staged export for very large agencies.** The synchronous export refuses above
  `MAX_EXPORT_ROWS` rather than risking the instance. An agency past that ceiling needs a job
  that writes to object storage — the `*_s3_key` columns exist and nothing writes them.
- **Tracing** — no distributed tracing on the EVV/scheduling critical paths. Metrics and
  alerting now exist (see below); tracing is what would answer *why* a clock-in was slow
  rather than *that* it was.
- **A real pager.** The alert rules and routing are built and tested, and the local stack
  delivers end to end — but the receivers are placeholders. Wiring `page` to PagerDuty or
  Slack needs credentials this repository should not hold, so today an alert reaches a log
  line in a container. That is not being on call, and it is the one remaining gap between
  this system and the 99.9% NFR.
- **Infrastructure-as-code** — no Terraform, no deployed environment.
- **Localization beyond English and Spanish.** Both apps are now fully EN/ES, which is what
  the PRD requires at MVP. A third language is a dictionary away; nothing in the mechanism
  assumes two.

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
| Offboarding | **Built and tested, and a real hole closed.** Terminating a caregiver now *disables* their account rather than only revoking its sessions — until this increment a terminated caregiver could sign straight back in with the password they still knew, so the offboarding wrote a record saying access was removed while it was not. Disabling and enabling are on the Users screen, both audited, and a disabled account is refused at login and at refresh |

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

### And a second one it uncovered: middleware-built responses had no CORS headers

Checking that the new `COMMIT_FAILED` response was actually usable by the caregiver app found
that it was not — and neither was anything else the middleware answers by itself.
`CORSMiddleware` was registered *before* `request_context`, and Starlette runs the most
recently added middleware first, so `request_context` sat outside it. Every response it built
without calling the router — a 429, an authentication failure, and now a failed commit — went
out with no `Access-Control-Allow-Origin` at all, and a browser blocks such a response
entirely. The caregiver app saw a network error rather than a 429, and could not read the
`Retry-After` that the previous increment had just gone to the trouble of exposing.

Fixed by registering CORS last, which puts it outermost. Pinned by a test that asserts on the
*refusal* rather than on a 200 — the 200 path was never broken and would have kept passing.

**And the same ordering was quietly defeating the clock-in exemption.** A cross-origin POST
carrying `Authorization` and `Idempotency-Key` is preceded by an `OPTIONS` preflight. That
preflight matches no declared route method, so it resolved to the standard tier — and once an
agency's budget was spent it came back 429. A browser that cannot complete a preflight never
sends the request at all, so Section 9's one hard rule was defeatable through its own preflight
for every browser client, and the caregiver app is one. The endpoint was exempt; the permission
to call it was not.

With CORS outermost, preflights are answered before the limiter runs. Verified both ways
against the two revisions rather than reasoned about: 429 before, 200 after. A first attempt to
check this compared a revision against itself — the working tree was already clean — and
reported no difference, which is worth recording as the reason the comparison is now pinned in
a test rather than done by hand.

## Suggested next steps

1. **Run the caregiver app on real devices.** It is verified in Chromium at a phone viewport
   against a real API, which is a much stronger position than unexecuted code but is not the
   same as iOS Safari, a real GPS chip, and a genuinely bad connection. Decide native
   packaging at the same time, since iOS push and background sync depend on it.
2. **A real destination for the pages.** The rules, the routing, and the local delivery path
   are built and tested; the receivers are placeholders, so an alert currently reaches a log
   line rather than a person. This needs a PagerDuty routing key or a Slack webhook and is
   otherwise a config change.
3. **First real EVV integration** for one state, end to end through that vendor's sandbox.
   This is the assumption most likely to be wrong, and the cheapest time to find out is now.
4. **Engage compliance counsel**, and run the bias audit on real outcomes before the ranking
   model influences actual hiring. The tooling exists; the audit does not.
5. **Register a real routing provider.** The `RoutingAdapter` interface and registry
   exist; only the haversine approximation is implemented. This is now a one-class change.
6. **Job-board and background-check integrations**, behind the adapter interfaces
   `07_Integration_Specifications.md` Section 1 requires.
