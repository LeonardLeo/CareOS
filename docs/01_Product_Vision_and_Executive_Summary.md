# CareOS — Product Vision & Executive Summary

**Document owner:** Product
**Status:** Foundational — read this first
**Last updated:** 2026-07-29
**Audience:** Founders, incoming engineering/product/design teams, investors, new hires

---

## 1. One-paragraph pitch

CareOS is an AI-native operating system for home-based care agencies (home care, home health, and hospice). It replaces the workforce, documentation, and billing workflows currently split across legacy EHR-style systems of record, spreadsheets, and phone calls with a single AI-driven platform. CareOS launches with a workforce wedge (AI-assisted caregiver recruiting, onboarding, and EVV-compliant scheduling), expands into ambient point-of-care documentation and compliance monitoring, and matures into a full multi-payer revenue-cycle engine — becoming the system of action (not just record) for the agency.

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

**Bottom line:** agencies are losing revenue every week because they cannot staff the cases they already have, and the software they use today was built to document care after the fact, not to run the business of finding, keeping, and deploying caregivers.

## 3. Why this, why now

1. **AI capability unlock.** Ambient documentation, voice agents, and reliable structured-data extraction from unstructured clinical notes are only production-viable as of 2025–2026 (see Abridge's healthcare deployment scale as an existence proof in adjacent clinical settings).
2. **No AI-native category leader.** Incumbents (Homecare Homebase, WellSky, MatrixCare, Alora, myEZCare, CareSmartz360, ShiftCare) are EHR-first systems of record. None has shipped an AI-native workforce layer at scale.
3. **Regulatory complexity is a moat.** EVV mandates (state-by-state aggregators), the CMS Home Health PPS rule, and Medicaid waiver/Medicare Advantage/private-pay billing variance are exactly the kind of compliance surface that keeps thin AI wrappers out and rewards a funded, patient team.
4. **Demographic demand is not cyclical.** This is a multi-decade tailwind, not a trend that reverses in a downturn.

## 4. Product phases (the full arc — not just the MVP)

CareOS is built in three layers that compound on the same data model. Each phase is a real, sellable product on its own; each subsequent phase increases switching cost and ARPU.

### Phase 1 — AI Workforce Engine (MVP → v1.0)
**Goal:** become indispensable for solving the staffing crisis.
- AI-assisted candidate sourcing, screening, and ranking
- Sub-72-hour onboarding: parallel credential verification (background checks, license/certification checks, TB tests, I-9/W-4), e-signature workflows
- EVV-compliant, drive-time-optimized scheduling
- Real-time shift-gap detection and AI-driven gap-filling / shift-swap marketplace
- Caregiver mobile app: schedule, clock-in/out (EVV), messaging, pay/hours visibility
- Agency admin web app: roster, scheduling board, applicant pipeline, compliance dashboard

### Phase 2 — Ambient Documentation + Compliance Copilot (v1.x → v2.0)
**Goal:** eliminate after-hours charting and reduce audit/denial risk.
- Ambient/voice point-of-care documentation (visit notes, vitals, ADLs) with clinician/caregiver review-and-sign
- Structured extraction into care-plan and billing-relevant fields
- Compliance copilot: flags documentation gaps, survey-readiness issues, and PPS-rule risk before submission
- Care-plan management and task/ADL tracking tied to the schedule
- Family/client portal (visibility into visit confirmation, care notes with appropriate redaction)

### Phase 3 — Revenue Engine (v2.x → v3.0 "full product")
**Goal:** become the system of record for cash, not just care.
- EVV-verified visit data flows directly into claim generation (837 EDI) across Medicaid waiver, Medicare Advantage, and private-pay payers
- Eligibility verification (270/271 EDI), claim scrubbing, and denial prevention
- Remittance processing (835 EDI), AR aging, and payer-mix analytics
- Caregiver payroll integration and pay-parity/overtime compliance
- Multi-agency / multi-location rollups for regional and franchise operators
- Open API / marketplace for third-party clinical and financial integrations

## 5. Who we serve

- **Primary buyer:** owners/administrators of independent and regional home-based care agencies, roughly $2M–$50M in annual revenue, currently on a legacy EHR-style platform or spreadsheets.
- **Primary daily users:** scheduling coordinators/staffing managers, caregivers (field staff), clinical supervisors (RNs), billing/RCM staff.
- **Secondary stakeholders:** clients and their families (portal), payers/Medicaid programs (compliance and claims interfaces), franchise/regional operators (rollup reporting).

## 6. Success metrics by phase

| Phase | Primary metric | Target (design-partner cohort) |
|---|---|---|
| Phase 1 | Time-to-first-visit for a new hire | ≤ 3 days |
| Phase 1 | Reduction in turned-down cases | Measurable decrease within 90 days of go-live |
| Phase 2 | After-hours charting time per caregiver | Reduction vs. baseline; target near-elimination |
| Phase 2 | Net revenue retention from documentation upsell | > 110% |
| Phase 3 | Clean-claim rate | Improvement vs. agency's pre-CareOS baseline |
| Phase 3 | RCM module attach rate | > 30% of active base |

## 7. Non-negotiable constraints (apply to every phase)

- **HIPAA compliance** is mandatory from day one — even Phase 1 touches PHI (schedules reference client names/addresses, caregiver health/credential data).
- **Multi-tenant data isolation** must be architected in from the first schema, not retrofitted.
- **EVV compliance** is a hard requirement for any agency serving Medicaid clients — this is not optional scope.
- **Offline-first mobile design** — caregivers frequently work in homes with poor connectivity; clock-in/out and documentation must queue and sync.
- **Accessibility and low-literacy design** — the caregiver workforce has wide variance in tech familiarity and, in many markets, English proficiency.

## 8. How to use this document set

This is document 1 of 12. If you are a new team picking this up, read in this order:
1. This document (vision)
2. `02_Product_Requirements_Document.md` (what to build)
3. `03_Technical_Architecture.md` and `04_Data_Model_and_Schema.md` (how it's built)
4. `06_Compliance_and_Regulatory_Requirements.md` (constraints you cannot violate)
5. Everything else, as needed for your role

See `00_README_Index.md` for the full document map and current build status.
