# CareOS — Product Requirements Document (PRD)

**Document owner:** Product
**Status:** Living document — update as scope is refined during build
**Audience:** Product managers, engineers, designers, QA

---

## 0. How to read this PRD

Requirements are organized by **Phase → Epic → User Story → Acceptance Criteria**. Every story includes a priority (P0 = must-have for that phase's launch, P1 = important follow-on, P2 = nice-to-have/backlog). Non-functional requirements (NFRs) that apply across all phases are in Section 4. Out-of-scope items are called out explicitly per epic to prevent scope creep.

---

## 1. Phase 1 — AI Workforce Engine (MVP)

**Phase goal:** an agency can source, hire, and schedule caregivers faster than today, with EVV compliance built in from day one.

### Epic 1.1 — Agency & User Management (Foundation)
*This epic underlies everything else — build first.*

- **US-1.1.1 (P0):** As an agency owner, I can create an agency account, defining agency name, tax ID, service states/counties, service lines (home care / home health / hospice), and payer types accepted (Medicaid waiver, Medicare Advantage, private pay).
  - AC: Agency record created with a unique tenant ID; all subsequent data is scoped to this tenant ID at the database level.
  - AC: Agency onboarding wizard captures state(s) of operation to determine which EVV aggregator(s) and compliance rules apply (see `06_Compliance_and_Regulatory_Requirements.md`).
- **US-1.1.2 (P0):** As an agency admin, I can invite and manage users with roles: Owner/Admin, Scheduler/Coordinator, Clinical Supervisor (RN), Caregiver, Billing/RCM (Phase 3), Read-only/Auditor.
  - AC: Role-based access control (RBAC) enforced on every API endpoint (see `07_Security_Architecture.md`).
- **US-1.1.3 (P1):** As a regional operator, I can manage multiple agency locations under one parent organization with rolled-up reporting.
  - Out of scope for MVP: franchise billing/royalty features.

### Epic 1.2 — Caregiver Recruiting & Sourcing
- **US-1.2.1 (P0):** As a scheduler, I can post an open caregiver role that syndicates to job boards (Indeed, ZipRecruiter via API/feed) and captures applicants into a single pipeline.
  - AC: Applicant record captures name, contact info, availability, certifications claimed, and resume/file upload.
- **US-1.2.2 (P0):** As a scheduler, I see AI-generated ranking/scoring of applicants based on certification match, geographic proximity to open cases, availability overlap with open shifts, and (if available) past performance signals.
  - AC: Ranking model output is explainable — each applicant shows the top 3 factors driving their score, not just a black-box number.
  - AC: Model must not use protected-class attributes (race, national origin, age, disability, familial status, religion) as scoring inputs; a bias-audit checklist is completed before this feature ships (see `06_Compliance_and_Regulatory_Requirements.md`, Section on Employment/Fair-Hiring Law).
- **US-1.2.3 (P1):** As a scheduler, I can set up automated screening (e.g., a conversational AI phone/text screen) to pre-qualify applicants before human review.
- **US-1.2.4 (P1):** As an agency owner, I can see a recruiting funnel dashboard (applied → screened → hired → onboarded → active) with conversion rates and time-in-stage.

### Epic 1.3 — Onboarding & Credentialing
- **US-1.3.1 (P0):** As a new hire, I complete onboarding paperwork (I-9, W-4, state tax forms, direct deposit, employee handbook e-signature) digitally on mobile or web before day one.
- **US-1.3.2 (P0):** As a scheduler, I can trigger parallel, automated third-party checks: criminal background check, sex-offender registry check, exclusion list check (OIG/GSA — required for Medicaid/Medicare billing eligibility), and license/certification verification (CNA, HHA, RN as applicable), and TB/health screening document capture.
  - AC: All checks integrate with named vendors via API (see `05_Integration_Specifications.md` for vendor list and required data contracts).
  - AC: A caregiver cannot be scheduled for a Medicaid-billed visit until the exclusion-list check has cleared — this is a hard system gate, not a warning.
- **US-1.3.3 (P0):** As an agency admin, I have a credentialing dashboard showing every caregiver's document/certification status and expiration dates, with automated renewal reminders (e.g., 60/30/7 days before expiry).
- **US-1.3.4 (P1):** As a caregiver, I receive a structured, milestone-based onboarding checklist in the mobile app so I know exactly what's left before I can start working.

### Epic 1.4 — Scheduling & EVV
- **US-1.4.1 (P0):** As a scheduler, I can create a care plan's recurring visit schedule (frequency, duration, required tasks) for a client and assign caregivers to shifts.
- **US-1.4.2 (P0):** As a scheduler, I get AI-recommended caregiver-to-shift matches optimized for: certification match, drive time between consecutive visits, caregiver preference/availability, continuity of care (same caregiver where possible), and overtime/labor-law thresholds.
- **US-1.4.3 (P0):** As a caregiver, I clock in and out of a visit via the mobile app using an EVV-compliant method (GPS + timestamp, and telephony fallback for no-smartphone/no-signal cases), capturing the six federally required EVV data elements: type of service, individual receiving service, date of service, location of service delivery, individual providing service, and time service begins/ends.
  - AC: EVV records transmit to the correct state aggregator (Sandata, HHAeXchange, Tellus, or state-proprietary system depending on state — see `05_Integration_Specifications.md`) in the required format and cadence.
  - AC: Offline clock-in/out is supported and syncs when connectivity returns, with a clear "pending sync" state visible to the caregiver.
- **US-1.4.4 (P0):** As a scheduler, when a caregiver calls out or a shift is unfilled, I get real-time gap alerts and AI-ranked suggestions for replacement caregivers, with one-tap offer/broadcast to qualified, available staff.
- **US-1.4.5 (P1):** As a caregiver, I can view my schedule, request time off, and pick up open shifts via a shift marketplace within policy constraints set by the agency.
- **US-1.4.6 (P1):** As an agency admin, I get alerts on EVV compliance exceptions (missed clock-in/out, visits outside geofence, visits not matching authorized service) before they become billing/audit problems.

### Epic 1.5 — Core Reporting (Phase 1)
- **US-1.5.1 (P0):** As an agency owner, I see a dashboard of: open shifts, fill rate, turnover rate (rolling 30/90-day), average time-to-hire, and EVV compliance rate.
- Out of scope for Phase 1: financial/RCM reporting (Phase 3), clinical outcome reporting (Phase 2).

---

## 2. Phase 2 — Ambient Documentation + Compliance Copilot

**Phase goal:** eliminate after-hours charting, improve documentation quality, and reduce audit/denial risk — while deepening the data asset that will power Phase 3 billing.

### Epic 2.1 — Ambient Point-of-Care Documentation
- **US-2.1.1 (P0):** As a caregiver, I can dictate or have an ambient-listening session during a visit that generates a structured visit note (tasks/ADLs completed, vitals if applicable, observations) for my review and e-signature — I am never required to file a note I have not reviewed.
  - AC: All ambient audio processing discloses to the client/family that recording/transcription is occurring, per state consent laws (two-party consent states require explicit verbal or written consent — see `06_Compliance_and_Regulatory_Requirements.md`).
  - AC: Raw audio is not retained beyond the minimum period needed for transcription QA unless the agency opts into extended retention with appropriate consent; transcripts, not raw audio, are the durable record by default.
- **US-2.1.2 (P0):** As a clinical supervisor (RN), I review and co-sign visit notes that require clinical oversight, with AI-flagged items needing attention (missed required task, abnormal vital, inconsistent statement).
- **US-2.1.3 (P1):** As a caregiver with low smartphone literacy, I can complete documentation via a simplified, icon-forward flow or voice-only flow as an alternative to typing.

### Epic 2.2 — Compliance Copilot
- **US-2.2.1 (P0):** As an agency admin, before a visit note or claim-relevant documentation is finalized, the system flags: missing required fields for the applicable payer/service type, internal inconsistencies (e.g., time of service note doesn't match EVV clock times), and survey-readiness gaps (based on state survey/audit checklists).
- **US-2.2.2 (P1):** As an agency admin, I receive a rolling "audit-readiness score" summarizing documentation completeness and compliance exception trends across the agency.
- **US-2.2.3 (P1):** As a compliance officer, I can configure agency-specific documentation rules (e.g., additional required fields for a specific payer contract) without engineering involvement (a rules-configuration UI, not hardcoded logic).

### Epic 2.3 — Care Plan & Task Management
- **US-2.3.1 (P0):** As a clinical supervisor, I can build and update a client's care plan (authorized tasks/ADLs, frequency, special instructions), which flows automatically into the caregiver's in-visit task checklist.
- **US-2.3.2 (P1):** As a clinical supervisor, I track care-plan-linked outcomes (e.g., task completion trends, missed-task patterns) to flag clients who may need a care-plan review.

### Epic 2.4 — Family/Client Portal
- **US-2.4.1 (P1):** As a client's family member, I can see upcoming/confirmed visits, which caregiver is assigned, and appropriately-redacted visit summaries (no free-text clinical notes without supervisor approval for release).
- **US-2.4.2 (P2):** As a family member, I can message the care team through the portal.

---

## 3. Phase 3 — Revenue Engine ("full product")

**Phase goal:** CareOS becomes the system agencies use to get paid, closing the loop from verified visit to clean claim to reconciled cash.

### Epic 3.1 — Eligibility & Authorization
- **US-3.1.1 (P0):** As billing staff, I can run real-time eligibility checks (X12 270/271 transactions) against Medicaid, Medicare Advantage, and commercial payers before scheduling a new client's recurring visits.
- **US-3.1.2 (P0):** As billing staff, I can track service authorizations (units/hours approved, date ranges) per client per payer, with alerts before authorization exhaustion or expiration.

### Epic 3.2 — Claims Generation & Submission
- **US-3.2.1 (P0):** As billing staff, I can generate clean claims (X12 837) automatically from EVV-verified visit data and care-plan/authorization data, reducing manual claim entry.
- **US-3.2.2 (P0):** As billing staff, before submission, the system runs a claim-scrubbing pass flagging likely denial triggers (mismatched units, expired authorization, missing modifiers, EVV-claim mismatch) — this reuses the Phase 2 compliance-copilot engine against claims data.
- **US-3.2.3 (P0):** As billing staff, I can submit claims electronically to clearinghouses/payers and track claim status (submitted, accepted, rejected, paid, denied).

### Epic 3.3 — Remittance & Denial Management
- **US-3.3.1 (P0):** As billing staff, remittance advice (X12 835) is ingested automatically and reconciled against submitted claims, updating AR status.
- **US-3.3.2 (P0):** As billing staff, denied claims are routed into a denial-management queue with AI-suggested correction/resubmission steps and root-cause categorization.
- **US-3.3.3 (P1):** As an agency owner, I see AR aging, denial-rate trends by payer, and payer-mix profitability analytics.

### Epic 3.4 — Payroll & Pay Compliance
- **US-3.4.1 (P0):** As billing/HR staff, caregiver hours from EVV-verified visits flow into payroll processing (native or via integration with a payroll provider), correctly applying overtime and any applicable pay-parity rules.
- **US-3.4.2 (P1):** As an agency owner, I can model the cost/margin impact of scheduling decisions (overtime exposure, travel-time compensation requirements where applicable) before they happen.

### Epic 3.5 — Multi-Agency / Franchise Rollups
- **US-3.5.1 (P1):** As a regional/franchise operator, I see consolidated financial and operational dashboards across all locations with drill-down.
- **US-3.5.2 (P2):** As a franchisor, I can benchmark locations against anonymized peer/network performance.

### Epic 3.6 — Open API & Ecosystem
- **US-3.6.1 (P2):** As a third-party vendor (e.g., a specialized clinical assessment tool), I can integrate with CareOS via a documented, versioned public API.

---

## 4. Cross-cutting Non-Functional Requirements (apply to all phases)

| Category | Requirement |
|---|---|
| **Availability** | 99.9% uptime target for core scheduling/EVV clock-in functions (these are business-critical and legally time-sensitive) |
| **Multi-tenancy** | Strict logical (minimum) or physical (preferred for larger accounts) data isolation per agency tenant from schema design onward |
| **Offline support** | Caregiver mobile app must support offline clock-in/out and documentation queuing with sync-on-reconnect |
| **HIPAA** | All PHI encrypted at rest and in transit; audit logging on all PHI access; BAAs required with every subprocessor touching PHI |
| **EVV compliance** | Must support the six federal EVV data elements and transmit to state-designated aggregators in required formats |
| **Localization/accessibility** | UI must support low-literacy and multilingual caregiver populations (minimum: English + Spanish at MVP; expand based on target markets) |
| **Auditability** | Every clinical, scheduling, and billing action must be attributable (user, timestamp, before/after state) and immutable/append-only in the audit trail |
| **Performance** | Scheduling board and clock-in actions must respond in < 2 seconds under normal load; AI ranking suggestions in < 5 seconds |
| **Data portability** | Agencies must be able to export their full data set (clients, caregivers, visits, claims) in a standard format — this is both an ethical commitment and, in some states, a regulatory expectation for care records |

## 5. Explicit non-goals (all phases, current roadmap horizon)

- Building a consumer-facing caregiver marketplace (agencies remain the employer of record).
- Direct-to-consumer client acquisition/booking (CareOS serves agencies, not individual families sourcing care independently) — may be revisited post-Phase 3.
- Clinical decision support / diagnosis (CareOS documents and manages care; it does not practice medicine).
- International markets (US-only for the roadmap horizon in this document set; EVV and billing infrastructure are US-specific).

## 6. Dependencies between phases

- Phase 2's compliance copilot reuses the rules engine first built for Phase 1's EVV-exception alerting (Epic 1.4.6) — build that rules engine generically, not as a one-off feature.
- Phase 3's claims generation depends entirely on Phase 1 EVV data and Phase 2 documentation being structured and complete — **do not treat Phase 3 as a bolt-on; the Phase 1/2 data model must be designed with Phase 3 fields in mind from the start** (see `03_Technical_Architecture.md` and `04_Data_Model_and_Schema.md`, which include Phase 3 entities even though they're not built until later).
