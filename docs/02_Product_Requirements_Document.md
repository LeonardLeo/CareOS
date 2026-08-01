# CareOS — Product Requirements Document (PRD)

**Document owner:** Product
**Status:** Living document — update as scope is refined during build
**Audience:** Product managers, engineers, designers, QA

---

## 0. How to read this PRD

**Structure:** Phase → Epic → User Story → Acceptance Criteria.

**Priorities:** P0 = must-have for that phase's launch. P1 = important follow-on. P2 = backlog.

**Section 4** holds non-functional requirements that apply across all phases. Out-of-scope items
are stated per epic.

---

## 1. Phase 1 — AI Workforce Engine (MVP)

**Phase goal:** an agency can source, hire, and schedule caregivers faster than today, with EVV
compliance built in from day one.

### Epic 1.1 — Agency & User Management (Foundation)

Build first. Everything else depends on it.

- **US-1.1.1 (P0):** As an agency owner, I can create an agency account, defining agency name,
  tax ID, service states and counties, service lines (home care / home health / hospice), and
  payer types accepted (Medicaid waiver, Medicare Advantage, private pay).
  - AC: Agency record created with a unique tenant ID. All subsequent data is scoped to that
    tenant ID at the database level.
  - AC: The onboarding wizard captures states of operation, which determine the applicable EVV
    aggregators and compliance rules (`06_Compliance_and_Regulatory_Requirements.md`).
- **US-1.1.2 (P0):** As an agency admin, I can invite and manage users with roles: Owner/Admin,
  Scheduler/Coordinator, Clinical Supervisor (RN), Caregiver, Billing/RCM (Phase 3),
  Read-only/Auditor.
  - AC: RBAC enforced on every API endpoint (`08_Security_Architecture.md`).
- **US-1.1.3 (P1):** As a regional operator, I can manage multiple agency locations under one
  parent organization with rolled-up reporting.
  - Out of scope for MVP: franchise billing and royalty features.

### Epic 1.2 — Caregiver Recruiting & Sourcing

- **US-1.2.1 (P0):** As a scheduler, I can post an open caregiver role that syndicates to job
  boards (Indeed, ZipRecruiter via API or feed) and captures applicants into a single pipeline.
  - AC: Applicant record captures name, contact info, availability, certifications claimed, and
    resume or file upload.
- **US-1.2.2 (P0):** As a scheduler, I see AI ranking of applicants based on certification
  match, geographic proximity to open cases, availability overlap with open shifts, and past
  performance signals where available.
  - AC: Ranking output is explainable. Each applicant shows the top three factors driving the
    score, not a single number.
  - AC: Protected-class attributes (race, national origin, age, disability, familial status,
    religion) are not scoring inputs. A bias audit is completed before the feature ships
    (`06_Compliance_and_Regulatory_Requirements.md`, employment and fair-hiring law).
- **US-1.2.3 (P1):** As a scheduler, I can set up automated screening (a conversational AI
  phone or text screen) to pre-qualify applicants before human review.
- **US-1.2.4 (P1):** As an agency owner, I can see a recruiting funnel dashboard (applied →
  screened → hired → onboarded → active) with conversion rates and time-in-stage.

### Epic 1.3 — Onboarding & Credentialing

- **US-1.3.1 (P0):** As a new hire, I complete onboarding paperwork (I-9, W-4, state tax forms,
  direct deposit, employee handbook e-signature) digitally on mobile or web before day one.
- **US-1.3.2 (P0):** As a scheduler, I can trigger parallel automated third-party checks:
  criminal background check, sex-offender registry, exclusion list (OIG/GSA, required for
  Medicaid and Medicare billing eligibility), license and certification verification (CNA, HHA,
  RN as applicable), and TB and health screening document capture.
  - AC: Checks integrate with named vendors via API. Vendor list and data contracts are in
    `07_Integration_Specifications.md`.
  - AC: A caregiver cannot be scheduled for a Medicaid-billed visit until the exclusion-list
    check clears. This is a system gate, not a warning.
- **US-1.3.3 (P0):** As an agency admin, I have a credentialing dashboard showing every
  caregiver's document and certification status with expiration dates, and automated renewal
  reminders at 60, 30, and 7 days before expiry.
- **US-1.3.4 (P1):** As a caregiver, I receive a milestone-based onboarding checklist in the
  mobile app showing what remains before I can start working.

### Epic 1.4 — Scheduling & EVV

- **US-1.4.1 (P0):** As a scheduler, I can create a care plan's recurring visit schedule
  (frequency, duration, required tasks) for a client and assign caregivers to shifts.
- **US-1.4.2 (P0):** As a scheduler, I get AI-recommended caregiver-to-shift matches optimized
  for certification match, drive time between consecutive visits, caregiver preference and
  availability, continuity of care, and overtime and labor-law thresholds.
- **US-1.4.3 (P0):** As a caregiver, I clock in and out of a visit via the mobile app using an
  EVV-compliant method: GPS and timestamp, with telephony fallback where there is no smartphone
  or no signal. The six federally required EVV data elements are captured: type of service,
  individual receiving service, date of service, location of service delivery, individual
  providing service, and time service begins and ends.
  - AC: EVV records transmit to the correct state aggregator in the required format and cadence.
    Aggregators are Sandata, HHAeXchange, Tellus, or a state-proprietary system depending on
    state (`07_Integration_Specifications.md`).
  - AC: Offline clock-in and clock-out are supported and sync when connectivity returns. The
    caregiver sees a "pending sync" state.
- **US-1.4.4 (P0):** As a scheduler, when a caregiver calls out or a shift is unfilled, I get
  real-time gap alerts and AI-ranked replacement suggestions, with one-tap offer or broadcast to
  qualified available staff.
- **US-1.4.5 (P1):** As a caregiver, I can view my schedule, request time off, and pick up open
  shifts in a shift marketplace, within policy constraints set by the agency.
- **US-1.4.6 (P1):** As an agency admin, I get alerts on EVV compliance exceptions before they
  become billing or audit problems. Exceptions: missed clock-in or clock-out, visits outside the
  geofence, visits not matching authorized service.

### Epic 1.5 — Core Reporting (Phase 1)

- **US-1.5.1 (P0):** As an agency owner, I see a dashboard of open shifts, fill rate, turnover
  rate (rolling 30 and 90 day), average time-to-hire, and EVV compliance rate.
- Out of scope for Phase 1: financial and RCM reporting (Phase 3), clinical outcome reporting
  (Phase 2).

---

## 2. Phase 2 — Ambient Documentation + Compliance Copilot

**Phase goal:** eliminate after-hours charting, improve documentation quality, and reduce audit
and denial risk, while deepening the data asset that powers Phase 3 billing.

### Epic 2.1 — Ambient Point-of-Care Documentation

- **US-2.1.1 (P0):** As a caregiver, I can dictate or run an ambient-listening session during a
  visit that generates a structured visit note for my review and e-signature. The note covers
  tasks and ADLs completed, vitals where applicable, and observations. No note is filed that I
  have not reviewed.
  - AC: Ambient audio processing discloses to the client and family that recording and
    transcription are occurring, per state consent law. Two-party consent states require
    explicit verbal or written consent (`06_Compliance_and_Regulatory_Requirements.md`).
  - AC: Raw audio is not retained beyond the minimum needed for transcription QA, unless the
    agency opts into extended retention with appropriate consent. Transcripts are the durable
    record by default.
- **US-2.1.2 (P0):** As a clinical supervisor (RN), I review and co-sign visit notes requiring
  clinical oversight, with AI-flagged items needing attention: missed required task, abnormal
  vital, inconsistent statement.
- **US-2.1.3 (P1):** As a caregiver with low smartphone literacy, I can complete documentation
  through a simplified icon-forward flow or a voice-only flow instead of typing.

### Epic 2.2 — Compliance Copilot

- **US-2.2.1 (P0):** As an agency admin, before a visit note or claim-relevant documentation is
  finalized, the system flags missing required fields for the applicable payer and service type,
  internal inconsistencies (time of service not matching EVV clock times), and survey-readiness
  gaps based on state survey and audit checklists.
- **US-2.2.2 (P1):** As an agency admin, I receive a rolling audit-readiness score summarizing
  documentation completeness and compliance exception trends across the agency.
- **US-2.2.3 (P1):** As a compliance officer, I can configure agency-specific documentation
  rules without engineering involvement. Example: additional required fields for a specific
  payer contract. This is a rules-configuration UI, not hardcoded logic.

### Epic 2.3 — Care Plan & Task Management

- **US-2.3.1 (P0):** As a clinical supervisor, I can build and update a client's care plan
  (authorized tasks and ADLs, frequency, special instructions), which flows into the caregiver's
  in-visit task checklist.
- **US-2.3.2 (P1):** As a clinical supervisor, I track care-plan-linked outcomes such as task
  completion trends and missed-task patterns, to flag clients who may need a care-plan review.

### Epic 2.4 — Family/Client Portal

- **US-2.4.1 (P1):** As a client's family member, I can see upcoming and confirmed visits, the
  assigned caregiver, and redacted visit summaries. Free-text clinical notes are not released
  without supervisor approval.
- **US-2.4.2 (P2):** As a family member, I can message the care team through the portal.

---

## 3. Phase 3 — Revenue Engine

**Phase goal:** CareOS becomes the system agencies use to get paid, closing the loop from
verified visit to clean claim to reconciled cash.

### Epic 3.1 — Eligibility & Authorization

- **US-3.1.1 (P0):** As billing staff, I can run real-time eligibility checks (X12 270/271)
  against Medicaid, Medicare Advantage, and commercial payers before scheduling a new client's
  recurring visits.
- **US-3.1.2 (P0):** As billing staff, I can track service authorizations (units or hours
  approved, date ranges) per client per payer, with alerts before authorization exhaustion or
  expiration.

### Epic 3.2 — Claims Generation & Submission

- **US-3.2.1 (P0):** As billing staff, I can generate clean claims (X12 837) automatically from
  EVV-verified visit data plus care-plan and authorization data.
- **US-3.2.2 (P0):** As billing staff, before submission the system runs a claim-scrubbing pass
  flagging likely denial triggers: mismatched units, expired authorization, missing modifiers,
  EVV-claim mismatch. This reuses the Phase 2 compliance-copilot engine against claims data.
- **US-3.2.3 (P0):** As billing staff, I can submit claims electronically to clearinghouses and
  payers, and track claim status: submitted, accepted, rejected, paid, denied.

### Epic 3.3 — Remittance & Denial Management

- **US-3.3.1 (P0):** As billing staff, remittance advice (X12 835) is ingested automatically and
  reconciled against submitted claims, updating AR status.
- **US-3.3.2 (P0):** As billing staff, denied claims route into a denial-management queue with
  AI-suggested correction and resubmission steps, and root-cause categorization.
- **US-3.3.3 (P1):** As an agency owner, I see AR aging, denial-rate trends by payer, and
  payer-mix profitability analytics.

### Epic 3.4 — Payroll & Pay Compliance

- **US-3.4.1 (P0):** As billing or HR staff, caregiver hours from EVV-verified visits flow into
  payroll processing, native or via a payroll provider, correctly applying overtime and any
  applicable pay-parity rules.
- **US-3.4.2 (P1):** As an agency owner, I can model the cost and margin impact of scheduling
  decisions (overtime exposure, travel-time compensation where applicable) before they happen.

### Epic 3.5 — Multi-Agency / Franchise Rollups

- **US-3.5.1 (P1):** As a regional or franchise operator, I see consolidated financial and
  operational dashboards across all locations, with drill-down.
- **US-3.5.2 (P2):** As a franchisor, I can benchmark locations against anonymized peer and
  network performance.

### Epic 3.6 — Open API & Ecosystem

- **US-3.6.1 (P2):** As a third-party vendor (a specialized clinical assessment tool, say), I
  can integrate with CareOS via a documented, versioned public API.

---

## 4. Cross-cutting Non-Functional Requirements

These apply to all phases.

| Category | Requirement |
|---|---|
| **Availability** | 99.9% uptime target for core scheduling and EVV clock-in functions. Both are business-critical and legally time-sensitive |
| **Multi-tenancy** | Strict logical isolation per agency tenant at minimum, physical isolation preferred for larger accounts, from schema design onward |
| **Offline support** | Caregiver mobile app supports offline clock-in/out and documentation queuing, with sync on reconnect |
| **HIPAA** | PHI encrypted at rest and in transit; audit logging on all PHI access; BAAs with every subprocessor touching PHI |
| **EVV compliance** | Supports the six federal EVV data elements and transmits to state-designated aggregators in required formats |
| **Localization/accessibility** | UI supports low-literacy and multilingual caregiver populations. English and Spanish at MVP; expand by target market |
| **Auditability** | Every clinical, scheduling, and billing action is attributable (user, timestamp, before/after state) and append-only in the audit trail |
| **Performance** | Scheduling board and clock-in respond in under 2 seconds under normal load; AI ranking suggestions in under 5 seconds |
| **Data portability** | Agencies can export their full data set — clients, caregivers, visits, claims — in a standard format. An ethical commitment, and in some states a regulatory expectation for care records |

## 5. Explicit non-goals

Current roadmap horizon, all phases.

| Non-goal | Note |
|---|---|
| Consumer-facing caregiver marketplace | Agencies remain the employer of record |
| Direct-to-consumer client acquisition and booking | CareOS serves agencies, not families sourcing care independently. May be revisited post-Phase 3 |
| Clinical decision support and diagnosis | CareOS documents and manages care; it does not practice medicine |
| International markets | US-only for this roadmap horizon. EVV and billing infrastructure are US-specific |

## 6. Dependencies between phases

**Phase 2 → Phase 1.** The compliance copilot reuses the rules engine first built for Phase 1
EVV-exception alerting (US-1.4.6). Build that rules engine generically rather than as a one-off.

**Phase 3 → Phases 1 and 2.** Claims generation depends on Phase 1 EVV data and Phase 2
documentation being structured and complete. The Phase 1 and 2 data model must carry Phase 3
fields from the start. `03_Technical_Architecture.md` and `04_Data_Model_and_Schema.md` include
Phase 3 entities for this reason, though they are not built until later.
