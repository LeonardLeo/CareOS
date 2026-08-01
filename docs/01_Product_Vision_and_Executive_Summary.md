# CareOS — Product Vision & Executive Summary

**Document owner:** Product
**Status:** Foundational — read this first
**Last updated:** 2026-07-29
**Audience:** Founders, incoming engineering/product/design teams, investors, new hires

---

## 1. One-paragraph pitch

CareOS is an operating system for home-based care agencies: home care, home health, hospice.

- **Replaces:** legacy EHR-style systems of record, spreadsheets, phone coordination.
- **Phase 1:** caregiver recruiting, onboarding, EVV-compliant scheduling.
- **Phase 2:** ambient point-of-care documentation and compliance monitoring.
- **Phase 3:** multi-payer revenue cycle.

The target position is the system agencies act in, not the one they file records into.

## 2. The problem, in numbers

| Problem | Data point |
|---|---|
| Caregiver turnover | 79.2% in 2023, easing to ~75% in 2024 (Activated Insights Benchmarking Report) |
| Cost per caregiver replaced | ~$2,600 (~$171,600/year per average agency) |
| Applicant-to-hire conversion | Only 12.8% of applicants were hired in 2023 |
| Cases turned down for staffing | 63.3% of agencies turned down cases in 2023 |
| Where agencies say AI helps most | Scheduling/workforce (58%), back-office (53%), documentation (47%) |
| Demographic tailwind | 10,000 Americans turn 65 daily (Pew); 75% of adults 50+ want to age in place (AARP) |
| Market size | ~$173.6B US home-care providers market (2026); ~$458B global |

Two facts drive the rest of this document. Agencies lose revenue weekly on cases they already
have and cannot staff. The software they run on was built to document care after the fact.

## 3. Why this, why now

1. **AI capability.** Ambient documentation, voice agents, and structured extraction from
   unstructured clinical notes reached production viability in 2025–2026. Abridge's deployment
   scale in adjacent clinical settings is the existence proof.
2. **No AI-native category leader.** Homecare Homebase, WellSky, MatrixCare, Alora, myEZCare,
   CareSmartz360, and ShiftCare are EHR-first systems of record. None has shipped an AI-native
   workforce layer at scale.
3. **Regulatory complexity as a moat.** EVV mandates with state-by-state aggregators, the CMS
   Home Health PPS rule, and billing variance across Medicaid waiver, Medicare Advantage, and
   private pay. The surface is wide enough to exclude thin AI wrappers and to reward a funded
   team with patience.
4. **Non-cyclical demand.** The demographic trend runs for decades and does not reverse in a
   downturn.

## 4. Product phases

Three layers on one data model. Each phase is sellable alone. Each subsequent phase raises
switching cost and ARPU.

### Phase 1 — AI Workforce Engine (MVP → v1.0)

**Goal:** solve the staffing crisis.

- AI-assisted candidate sourcing, screening, and ranking
- Sub-72-hour onboarding: parallel credential verification (background checks,
  license/certification checks, TB tests, I-9/W-4), e-signature workflows
- EVV-compliant, drive-time-optimized scheduling
- Real-time shift-gap detection, AI-driven gap-filling, shift-swap marketplace
- Caregiver mobile app: schedule, clock-in/out (EVV), messaging, pay and hours visibility
- Agency admin web app: roster, scheduling board, applicant pipeline, compliance dashboard

### Phase 2 — Ambient Documentation + Compliance Copilot (v1.x → v2.0)

**Goal:** eliminate after-hours charting; reduce audit and denial risk.

- Ambient and voice point-of-care documentation (visit notes, vitals, ADLs) with
  clinician/caregiver review-and-sign
- Structured extraction into care-plan and billing-relevant fields
- Compliance copilot: flags documentation gaps, survey-readiness issues, and PPS-rule risk
  before submission
- Care-plan management and task/ADL tracking tied to the schedule
- Family and client portal: visit confirmation, care notes with appropriate redaction

### Phase 3 — Revenue Engine (v2.x → v3.0)

**Goal:** system of record for cash, not only care.

- EVV-verified visit data into claim generation (837 EDI) across Medicaid waiver, Medicare
  Advantage, and private pay
- Eligibility verification (270/271 EDI), claim scrubbing, denial prevention
- Remittance processing (835 EDI), AR aging, payer-mix analytics
- Caregiver payroll integration, pay-parity and overtime compliance
- Multi-agency and multi-location rollups for regional and franchise operators
- Open API and marketplace for third-party clinical and financial integrations

## 5. Who we serve

- **Primary buyer:** owners and administrators of independent and regional home-based care
  agencies, roughly $2M–$50M annual revenue, currently on a legacy EHR-style platform or
  spreadsheets.
- **Primary daily users:** scheduling coordinators and staffing managers, caregivers, clinical
  supervisors (RNs), billing and RCM staff.
- **Secondary stakeholders:** clients and families (portal), payers and Medicaid programs
  (compliance and claims interfaces), franchise and regional operators (rollup reporting).

## 6. Success metrics by phase

| Phase | Primary metric | Target (design-partner cohort) |
|---|---|---|
| Phase 1 | Time-to-first-visit for a new hire | ≤ 3 days |
| Phase 1 | Reduction in turned-down cases | Measurable decrease within 90 days of go-live |
| Phase 2 | After-hours charting time per caregiver | Reduction vs. baseline; target near-elimination |
| Phase 2 | Net revenue retention from documentation upsell | > 110% |
| Phase 3 | Clean-claim rate | Improvement vs. agency's pre-CareOS baseline |
| Phase 3 | RCM module attach rate | > 30% of active base |

## 7. Non-negotiable constraints

These apply to every phase.

| Constraint | Detail |
|---|---|
| HIPAA compliance from day one | Phase 1 already touches PHI: schedules reference client names and addresses, caregiver health and credential data |
| Multi-tenant data isolation | Architected into the first schema, never retrofitted |
| EVV compliance | Hard requirement for any agency serving Medicaid clients; not optional scope |
| Offline-first mobile | Caregivers work in homes with poor connectivity; clock-in/out and documentation queue and sync |
| Accessibility and low-literacy design | The caregiver workforce varies widely in tech familiarity and, in many markets, English proficiency |

## 8. How to use this document set

Document 1 of 14. Reading order for a new team:

1. This document — vision
2. `02_Product_Requirements_Document.md` — what to build
3. `03_Technical_Architecture.md` and `04_Data_Model_and_Schema.md` — how it is built
4. `06_Compliance_and_Regulatory_Requirements.md` — constraints that cannot be violated
5. The rest, by role

`00_README_Index.md` has the full map. `BUILD_STATUS.md` has what currently exists, and
`13_Phase_1_Launch_Plan.md` has the sequence from one to the other.
