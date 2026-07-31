# CareOS — Phase 1 Launch Plan

**Document owner:** Engineering
**Status:** Living plan — update as each gate closes
**Audience:** Whoever is executing the run-up to a first real agency

---

## 0. What this document is

The fourteen items in `BUILD_STATUS.md` under *Suggested next steps*, sequenced into phases with
owners, verification, and exit criteria.

**The organising constraint:** six of the fourteen need something this repository cannot hold —
a cloud account, a vendor contract, a signature. Those have lead times measured in weeks. The
phases below run the work that needs those things in parallel with the work that does not, so
that engineering is never idle waiting for a countersignature and counsel is never the thing
discovered late.

**Two columns throughout.** *Ours* is work in this repository. *Yours* is work only the business
can do: opening accounts, signing agreements, engaging counsel, choosing vendors. A phase closes
when both columns close.

## 1. Three corrections to the ordering in BUILD_STATUS

The list in `BUILD_STATUS.md` is ordered by dependency. Three items are in the wrong place once
lead time and feasibility are accounted for.

**Item 5 (compliance counsel) is listed fifth and must start first.** Engaging healthcare
counsel, scheduling a review, and acting on findings is measured in weeks. Every other item is
measured in days of work. Counsel is the longest pole and is currently not planted. It moves to
Phase 0, day 1, in parallel with everything else.

**Item 6 (bias audit on real outcomes) cannot be done before a real agency, which is where the
list puts it.** The audit needs hiring outcomes. Outcomes need the ranking model to have
influenced hiring. So "audit before the model influences a hire" and "audit needs outcomes from
the model influencing hires" are in direct conflict.

The resolution is a shadow period. The scorer runs and logs, and the admin app does not display
its output, for the first cohort of hires. That produces outcomes with no adverse-impact risk,
because nothing the model said reached a decision-maker. The audit then runs on real data before
ranking is switched on.

The flag this needs now exists — `agency.ranking_display_enabled`, defaulting to false. What
remains in Phase 4 is the part only a real agency can supply: a first cohort, voluntary
demographic labels held separately, and a counsel review of the audit output.

**Item 14 (background-check integration) is listed last and is a hard blocker for most
agencies.** `assert_assignable` refuses a caregiver for publicly-funded work unless
`exclusion_check_status` is `cleared`, and before this the only thing that set it was an
administrator calling the endpoint by hand after checking the OIG and GSA sites themselves.
That is workable for a design partner with twenty caregivers and not workable at all beyond it.
It moves up to Phase 3.

The adapter layer, the async lifecycle, the re-screening job, and the flagged-while-scheduled
exception are now built against a loopback vendor. What remains is the vendor: a contract, a
BAA, and one adapter class behind the interface.

The other eleven items stay in relative order.

## 2. Phase 0 — Start the clocks (week 1, everything in parallel)

Nothing here is engineering-blocked. Everything here blocks something later.

| # | Item | Ours | Yours |
|---|---|---|---|
| 5a | Compliance counsel | Prepare the review pack: this document set, the RLS and audit-log design, the data-flow diagram, the subprocessor list | Engage a healthcare-compliance attorney. Book the review. Expect weeks, not days |
| 5b | Incident-response plan | Draft it against `08_Security_Architecture.md` Section 6: detection, triage, escalation, customer notification, post-incident review | Name the on-call owner and the notification decision-maker. Those are roles, not code |
| 1a | Cloud account — **AWS**, decided | Terraform for both environments is written and in `infra/`. Nothing has been applied | Open the account. Request the AWS BAA — required before PHI touches any service, and it is a form with a turnaround. Create the state bucket, the lock table, and the deploy role |
| 3a | EVV sandbox — **New York**, decided | Confirm the current NY aggregator assignment against DOH's published list. The reference row says HHAeXchange and is marked `UNVERIFIED`, which is where it stays until someone reads the source | Apply for aggregator sandbox credentials. Vendors gate these on a signed agreement; assume weeks |
| 14a | Background-check vendor | Nothing yet | Choose a vendor with an OIG/GSA exclusion product and a BAA. Start procurement |
| 6a | Design partner | Nothing yet | Sign the first agency. Everything in Phases 4 and 5 is calibrated on a real workforce |

**Exit criteria:** counsel engaged with a date, cloud account open with a BAA in flight, EVV
sandbox application submitted, background-check vendor selected, incident-response plan drafted
and owned.

**Failure mode this phase exists to prevent:** discovering in month three that counsel needs six
weeks and the EVV vendor needs a signed agreement before they will issue sandbox credentials.

## 3. Phase 1 — Make it deployable (item 1)

The local compose file is the only thing that has run this system end to end. Everything after
this phase assumes an environment.

**Built** (`infra/`, and `infra/README.md` for how to run it):

- Terraform for staging and production on AWS. Three subnet tiers, with the database and cache
  in a tier that has no route to a NAT gateway at all. RDS Postgres and ElastiCache Redis,
  both encrypted at rest with a customer-managed key and refusing plaintext connections at the
  server. Redis as a replication group rather than a single node, because the shared rate
  limiter is a hard dependency in production. ECS Fargate, an ALB terminating TLS 1.2+, and
  Secrets Manager — with the application secrets created empty and populated out of band, so a
  `terraform apply` never holds the JWT signing key.
- Migrations as their own ECS task that no service runs. The deploy pipeline runs it to
  completion, then rolls. Two API containers racing `alembic upgrade head` is the specific
  failure this shape prevents.
- The worker as its own service. Per-(job, agency) advisory locks make replica count a
  capacity decision.
- Boot gates set as task environment: `CAREOS_MFA_REQUIRED`, `CAREOS_RATE_LIMIT_BACKEND=redis`,
  a metrics token, and a non-loopback screening adapter. Production refuses to start without
  them, so the failure is at deploy time rather than months later.
- A CI job that formats, wiring-checks, and `terraform validate`s both environments — plus an
  assertion that staging sets `evv_use_sandbox = true` and production sets it false. Runtime
  guards catch production pointed at a sandbox; nothing catches staging pointed at a real
  aggregator, and a transmission from staging is a real filing about a real visit.

**Still ours:**
- A smoke test that runs against a deployed environment and exercises the golden path: create an
  agency, invite a user, create a client and care plan, generate visits, clock in, clock out,
  confirm the EVV record reaches the loopback adapter.
- A deployment runbook, including rollback.

**Yours:** run `terraform apply`. Provide the domain and certificate. Set the secrets.

**Verification.** The smoke test passes against staging. `CAREOS_MFA_REQUIRED`,
`CAREOS_RATE_LIMIT_BACKEND=redis`, and `CAREOS_METRICS_TOKEN` are set, because production refuses
to boot without them and that refusal should be observed once, deliberately, rather than
discovered during a deploy.

**Honest limit.** None of this has been applied to an AWS account. It is formatted,
wiring-checked, and validated against real provider schemas in CI — and the first `terraform
plan` against a live account will still surface things none of that can: a service quota, a
name collision, an argument the schema accepts and the service rejects. Budget a day.

**Exit criteria:** staging reachable over TLS, smoke test green, one deliberate rollback
rehearsed.

## 4. Phase 2 — Identity (item 2)

`08_Security_Architecture.md` Section 1 calls for managed OIDC. The local Argon2 path exists so
the system runs before that. `app_user.auth_provider_id` is the seam.

**Ours:**

- OIDC discovery, JWKS fetching with key rotation, authorization-code flow with PKCE, token
  exchange, and refresh.
- Claim-to-role mapping, with an explicit table rather than string matching on group names.
- Migration path: an existing local account links to a provider subject on first federated
  sign-in, matched by verified email. Accounts with no match are refused rather than created,
  so a provider misconfiguration cannot mint users.
- MFA moves to the provider. The local TOTP implementation is deleted, not left dormant. Its
  recovery codes and secrets are dropped in the same migration.
- The local password path is removed behind a flag first, then deleted.

**Yours:** choose and configure the provider. Decide whether caregivers authenticate through it
too, or stay on a separate path — this is a real decision, because a caregiver workforce with
high turnover and low technical familiarity is a different identity problem from an office
admin.

**Verification.** A local mock OIDC provider in the test suite, plus one end-to-end sign-in
against the real provider in staging. The mock is what makes the flow testable in CI; the real
sign-in is what proves the mock is not lying.

**Watch for:** deleting the local path while the caregiver app still depends on it. Sequence the
caregiver decision before the deletion, not after.

**Exit criteria:** every admin-app role signs in through the provider in staging; the local
password column is dropped; MFA enforcement is the provider's.

## 5. Phase 3 — The compliance surface (items 3, 14, 5)

The two integrations that decide whether an agency can legally bill for the work this system
schedules, plus the reviews that decide whether it can operate at all.

### 5.1 EVV, one state, through the sandbox (item 3)

The highest-risk item in the whole plan. A wrong field map does not fail a test. It surfaces as
a rejected claim months later, after the visits are delivered and the caregivers are paid.

**Ours:**

- Confirm the field map for the launch state's aggregator against current vendor documentation.
  The maps are structurally correct and their contents are provisional.
- Transmit a full set of shaped records to the sandbox: a normal visit, a manual exception, a
  telephony capture, a visit crossing midnight, a cancelled visit, a visit with a corrected
  clock-out.
- Record every request and response as fixtures, and add a conformance test that replays them.
  That is what stops the next change to the adapter silently breaking a map nobody re-checks.
- Build the reconciliation control: a periodic comparison of records transmitted against
  acknowledgements received, surfaced as a compliance exception when they diverge. Without it,
  a silently rejected batch is invisible until a payer says so.
- Set `sandbox_validated` for that state, and only that state.

**Yours:** sandbox credentials, and a person at the aggregator who will answer a question about
a rejection code.

**Verification.** Every shaped record is acknowledged by the sandbox. The reconciliation control
reports zero divergence over a week of synthetic traffic.

**Exit criteria:** one state marked `sandbox_validated`, conformance fixtures committed,
reconciliation running.

### 5.2 Background check and exclusion screening (item 14)

`assert_assignable` refuses a caregiver for publicly-funded work unless
`exclusion_check_status` is `cleared`. The machinery that sets it now exists; the vendor does
not.

**Built:**

- `careos.integrations.screening` — the adapter interface `07_Integration_Specifications.md`
  Section 1 requires, a registry that raises rather than defaulting, and a loopback adapter
  refused outside local and test.
- Asynchronous handling through `ScreeningRequest`: ordered, outstanding, resolved. Ordering
  clears nobody. A pending or unreadable result changes nothing, so every failure mode leaves a
  caregiver unassignable rather than cleared.
- Two worker jobs — polling for verdicts every five minutes, ordering re-screens daily against
  `exclusion_checked_at` and `CAREOS_SCREENING_RECHECK_INTERVAL_DAYS`.
- `background_check.completed`, which was in the published webhook contract with no producer.
- A critical compliance exception when a flagged caregiver still holds future visits. It does
  not unassign them: emptying five slots silently leaves five clients with nobody arriving.

**Still to do:** one adapter class for the chosen vendor, and a conformance run against their
sandbox. The status-mapping function refuses any status not explicitly mapped, so that run is
where a vendor's real vocabulary gets discovered rather than guessed.

**Yours:** the vendor contract, and a signed BAA before any identity data moves.

**Verification.** A flagged result blocks assignment in a test that goes through the real
adapter against the vendor's sandbox.

### 5.3 Counsel, BAAs, incident response (item 5)

**Ours:** the review pack from Phase 0, updated with whatever Phases 1 to 3 changed. Act on
findings.

**Yours:** the review itself. A signed BAA with each of: the cloud provider, the EVV aggregator,
the background-check vendor. The incident-response plan approved and its on-call owner named.

**Exit criteria:** written counsel sign-off for Phase 1 scope. Every PHI-touching subprocessor
has a countersigned BAA. The subprocessor list is published where an agency customer can see it.

## 6. Phase 4 — Operability and the shadow period (items 4, 9, 6)

### 6.1 A real pager (item 4)

**Ours:** replace the placeholder receivers with the real integration; add a synthetic alert that
fires weekly and is expected to page, so the path is proven continuously rather than at setup.

**Yours:** the PagerDuty routing key or Slack webhook, and a rota with names in it.

**Verification.** A deliberate page reaches a human phone. Then the weekly synthetic keeps
proving it.

**Note.** Until this closes, the 99.9% availability NFR in
`02_Product_Requirements_Document.md` Section 4 is met by nothing. Alerts currently reach a log
line in a container.

### 6.2 Tracing (item 9)

**Ours:** OpenTelemetry spans on the clock-in and EVV transmission paths, propagated through the
worker. Metrics answer whether a clock-in was slow; nothing answers why.

**Yours:** a collector endpoint. The instrumentation lands first and can sit idle.

**Verification.** A slow clock-in in staging produces a trace that names the slow span.

### 6.3 Bias-audit shadow period (item 6)

Per Section 1 of this document, the audit cannot precede outcomes.

**Built:** `agency.ranking_display_enabled`, defaulting to false so a new agency is in the
shadow period by construction rather than by remembering. While it is off the scorer still runs
and still persists — the audit needs those rows — and the API returns a null score, no factors,
no model version, and the applicant list in application order. Ordering is part of what is
withheld: the top of a list is a recommendation whether or not it carries a number. Every
ranking run writes `ranking_displayed` into its audit row, so the shadow period is evidenced at
the moment it was true rather than asserted afterwards from a config value.

Ending it is one endpoint, owner/admin only, and it refuses unless a passing
`ai_hiring_bias_audit` review is on file. An inconclusive audit does not count: the usual reason
a fairness audit is inconclusive is too small a sample, and "we could not tell" is not the same
finding as "we looked and it was fine". There is no endpoint to turn display back off — the flag
records the point at which an audited model began influencing hiring, and un-setting it would
leave the trail claiming a shadow period that was not one.

**Yours:** demographic labels collected separately and voluntarily, held apart from the
applicant record. Employment counsel reviews the audit output before ranking is displayed.

**Verification.** `python -m careos.scripts.run_bias_audit` runs on the first cohort's real
outcomes and records to the compliance log. Run today against a sixteen-applicant demo agency it
returns `inconclusive` — no hires yet, and groups below `min_group_size`. That is the correct
answer and it is also the shape of the risk: a first cohort may simply be too small to audit,
in which case the shadow period extends rather than the threshold moving.

**Exit criteria:** ranking display enabled for one agency, with a dated audit behind it.

## 7. Phase 5 — Reach every caregiver (items 7, 8, 11, 12)

Phase 1 GA is not reachable while part of the workforce cannot clock in.

### 7.1 Real devices and the packaging decision (item 7)

Offline clock-in is verified in Chromium at a phone viewport against a real API with the network
cut. That is stronger than unexecuted code and weaker than a real device.

**Ours:** a device test matrix — iOS Safari, Android Chrome, one low-end Android — covering
install, offline clock-in, background return, and sync after a genuinely bad connection.

**The decision to make once:** iOS delivers web push only to a home-screen-installed PWA, and
background sync is not available at all. Three options, in increasing cost:

| Option | Gets | Costs |
|---|---|---|
| Stay a PWA | Nothing new. Install friction on iOS, no background sync | Zero |
| Wrap in Capacitor | Push, background sync, store distribution. `src/lib` is already free of React and DOM imports, so the outbox and sync engine move unchanged | Days, plus store accounts and review cycles |
| Rewrite in React Native | The same, plus native performance nobody has asked for | Weeks, and the offline path would need re-verifying from scratch |

Capacitor is the recommendation on the evidence: the portable layer was built for exactly this
move, and the rewrite buys nothing the wrap does not.

**Yours:** devices, an Apple developer account, a Play account.

### 7.2 Telephony clock-in (item 8)

`capture_method: telephony` is accepted by the API and modelled end to end. No phone system is
attached. A caregiver without a smartphone cannot clock in at all.

**Ours:** the IVR call flow — inbound number, caregiver identification, visit selection,
clock-in and clock-out confirmation — behind a provider adapter, with a fake for tests. Caller-ID
matching against the caregiver record, and a spoken confirmation code, because caller ID is
trivially spoofed and this writes an EVV record.

**Yours:** the telephony provider account and a number per service area.

**Decide first:** ask the design partner what share of their workforce has no usable smartphone.
If it is material, this moves ahead of 7.1. For some agencies it is most of the field staff.

### 7.3 QR code on MFA enrolment (item 11)

**Ours:** an encoder in the admin app, rendering the `otpauth://` URI inline as SVG. The secret
and URI stay visible as text for password managers and for anyone who cannot scan.

**Verification.** A real authenticator app pairs from the rendered code. A QR that encodes the
wrong bytes pairs nothing and produces codes that never match, so this is verified by scanning,
not by inspecting the SVG.

### 7.4 MFA for schedulers (item 12)

**Ours:** one line in `MFA_REQUIRED_ROLES`, per `08_Security_Architecture.md` Section 1.
Caregivers stay out of `MFA_ELIGIBLE_ROLES` until the caregiver app has a field for a code —
enrolling one today locks them out of the phone they clock in with.

**Sequence:** after Phase 2, if identity has moved to the provider, this is the provider's
policy setting instead of a code change. Do not do it twice.

## 8. Phase 6 — Scale and fidelity (items 10, 13)

Neither blocks a first agency. Both block a tenth.

### 8.1 Staged export (item 10)

The synchronous export refuses above `MAX_EXPORT_ROWS` with a 413 rather than risking the
instance. An agency past that ceiling cannot get its data out, which is a portability commitment
with a size limit on it.

**Ours:** a job that writes to object storage and returns a signed URL, reusing the schema-derived
table list so completeness stays automatic. The `*_s3_key` columns already anticipate the bucket.

**Defer until:** an agency is actually near the ceiling. Measure before building.

### 8.2 A real routing provider (item 13)

`RoutingAdapter` and its registry exist. Only the haversine approximation is implemented, marked
`is_estimate` throughout. Adequate for ranking candidates against each other; not adequate for
quoting travel time to a caregiver or paying it on a timesheet.

**Ours:** one adapter class, plus a cache. Drive-time lookups are the kind of call that is
cheap once and expensive at scheduling-board scale, so the cache is part of the work rather than
a follow-up.

**Yours:** choose the provider and accept the per-call cost.

**Trigger:** the first time travel time is quoted to a caregiver or paid. Not before.

## 9. Sequencing summary

| Phase | Items | Gated on | Parallel with |
|---|---|---|---|
| 0 — Start the clocks | 5a, 1a, 3a, 14a, 6a | Nothing | Everything |
| 1 — Deployable | 1 | Cloud account | Phase 0 lead times |
| 2 — Identity | 2 | Phase 1 | Phase 3 procurement |
| 3 — Compliance surface | 3, 14, 5 | Sandbox and vendor credentials | Phase 2 |
| 4 — Operability and shadow | 4, 9, 6 | Phase 1; design partner for 6 | Phase 5 |
| 5 — Every caregiver | 7, 8, 11, 12 | Devices, telephony account | Phase 4 |
| 6 — Scale | 10, 13 | Measured need | — |

**Critical path to a first agency:** Phase 0 → Phase 1 → Phase 3 → counsel sign-off. Phases 2, 4,
and 5 matter and are not on that path, except 5.2 where the design partner's workforce requires
it.

## 10. What would make this plan wrong

Stated so that the plan can be checked against reality rather than followed off a cliff.

| Assumption | If it is wrong |
|---|---|
| One EVV state is representative | Each additional state is a new adapter and a new sandbox cycle. Multi-state at launch turns Phase 3 from weeks into a quarter |
| The design partner tolerates a shadow period on ranking | If they were sold on AI ranking, withholding it is a product conversation, not a config flag. Have it before Phase 4 |
| Counsel finds nothing structural | A finding against the multi-tenancy model or the audit-log design is a schema change, not a document change. This is why counsel starts in Phase 0 |
| The caregiver workforce has smartphones | If not, 7.2 moves to Phase 3 and becomes a launch blocker |
| Nobody needs Phase 2 and Phase 3 product scope yet | The tables exist; the behaviour does not. A design partner expecting billing is not a Phase 1 customer |
