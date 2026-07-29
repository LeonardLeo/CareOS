# CareOS — Compliance & Regulatory Requirements

**Document owner:** Compliance/Legal advisor (engage one before Phase 1 launch) + Product
**Status:** Foundational constraints — treat every requirement below as a hard gate, not a backlog item
**Audience:** Everyone building or selling CareOS

> **Important note for the incoming team:** this document summarizes regulatory domains CareOS must address, based on research current as of mid-2026. Regulations, state EVV vendor assignments, and payer rules change. **Engage qualified healthcare-compliance counsel and a certified coding/billing consultant before finalizing Phase 1 launch and before every subsequent phase**, particularly before Phase 3 (claims/billing) goes live. This document is a starting map, not a substitute for that review.

---

## 1. Electronic Visit Verification (EVV)

- **Legal basis:** Section 12006 of the 21st Century Cures Act mandates EVV for Medicaid-funded personal care services (implemented) and home health care services (implemented) in every state.
- **Required data elements (all six must be captured for every EVV-eligible visit):**
  1. Type of service performed
  2. Individual receiving the service
  3. Date of the service
  4. Location of service delivery
  5. Individual providing the service
  6. Time the service begins and ends
- **State model variance:** states choose one of several EVV models — e.g., a state-mandated vendor/aggregator, a state-provided open system, or allowing agencies to use their own EVV system that feeds a state-designated aggregator. **This means CareOS's EVV transmission layer must be built as a per-state adapter, not a single integration** (see `03_Technical_Architecture.md` Section 4 and `07_Integration_Specifications.md`). Common aggregators/vendors referenced in the market include Sandata, HHAeXchange, and Tellus, alongside state-proprietary systems — confirm the current vendor per state before building each adapter, as states periodically change vendors.
- **Product implication:** Epic 1.4.3 in the PRD is a hard compliance requirement, not a differentiator feature — visits without valid EVV data can result in claim denial or payment recoupment for Medicaid-funded services.

## 2. HIPAA (Health Insurance Portability and Accountability Act)

- **Applicability:** CareOS handles Protected Health Information (PHI) starting in Phase 1 (client names/addresses tied to care schedules, caregiver health-related credential data) and CareOS itself, or the agencies using it, will generally be a HIPAA Business Associate / Covered Entity depending on the specific service arrangement — confirm classification with counsel.
- **Privacy Rule requirements:** minimum-necessary access to PHI (enforced via RBAC — see `08_Security_Architecture.md`), client rights to access/amend their records (relevant to the family portal in Phase 2), and restrictions on PHI disclosure (relevant to the redaction logic in family-portal Epic 2.4.1).
- **Security Rule requirements:** encryption at rest and in transit, access controls and unique user identification, audit controls (the `audit_log` table in the data model), and a documented risk-analysis process.
- **Business Associate Agreements (BAAs):** required with every subprocessor that touches PHI — this includes the speech-to-text vendor (ambient documentation), background-check vendors (which touch identity data but generally not clinical PHI — confirm scope), cloud infrastructure provider, and any analytics/logging vendor that could incidentally capture PHI in logs. **Audit all third-party vendors in `07_Integration_Specifications.md` for BAA availability before integrating.**
- **Breach notification:** have an incident-response plan ready before launch (see `08_Security_Architecture.md`), since HIPAA breach notification timelines are short.

## 3. CMS Home Health Prospective Payment System (PPS) and related billing rules

- Home health agencies billing Medicare are subject to the CMS Home Health PPS, which determines payment based on 30-day care periods, patient case-mix (via the OASIS assessment), and specific documentation/coding requirements.
- OASIS (Outcome and Assessment Information Set) data collection is a distinct clinical-assessment requirement for Medicare-certified home health agencies — CareOS's care-plan and documentation modules (Phase 2) should be designed to accommodate OASIS-relevant data capture if the agency serves Medicare-certified home health clients, even though full OASIS submission tooling may be a Phase 3+ scope decision to make explicitly with the team at that time.
- PPS rules and payment rates are updated via an annual CMS final rule — **the compliance-rules engine (Epic 2.2, Phase 2) must be configurable per current rule year, not hardcoded**, since payment models and documentation requirements shift annually.

## 4. Medicaid variance by state

- Medicaid is administered at the state level; personal care/home-based service definitions, prior-authorization rules, billing codes, and rate structures vary significantly by state and even by specific Medicaid waiver program within a state.
- **Product implication:** the `payer_service_code_ref` and `authorization` entities in the data model must support per-state, per-payer-contract configuration rather than a single global rule set. Do not assume any billing rule discovered for one state's Medicaid program generalizes to another.

## 5. Employment and fair-hiring law

- The AI-driven applicant ranking feature (PRD Epic 1.2) must not use or proxy for protected-class attributes (race, color, national origin, sex, age, disability, religion, familial status, and additional state-specific protected classes).
- Several states and localities have specific AI-in-hiring disclosure or audit requirements (e.g., requirements to disclose AI use in hiring decisions, or to conduct periodic bias audits of automated employment decision tools). **Confirm current requirements in every state CareOS operates before Epic 1.2.2 ships**, and build the bias-audit process referenced in `03_Technical_Architecture.md` Section 8 as a recurring compliance task, not a one-time check.
- Wage-and-hour compliance: overtime rules, and in some jurisdictions specific home-care worker pay requirements (e.g., travel-time compensation between visits, minimum-wage parity rules for home-care workers) must be reflected in the scheduling and (Phase 3) payroll-integration logic.

## 6. State consent laws for ambient/audio documentation

- Two-party (all-party) consent states require the consent of all parties to a recorded conversation, not just the caregiver — this directly affects Epic 2.1.1 (ambient documentation). CareOS must capture and log explicit client/family consent before ambient audio processing begins in any two-party consent state, and should default to requiring explicit consent capture everywhere as a conservative baseline regardless of state, given the vulnerability of the client population and reputational risk of getting this wrong.
- Retention of raw audio recordings should be minimized by default (transcripts, not audio, as the durable record) with any extended retention as an explicit, consented, per-agency configuration — see the `ambient_session_metadata` table in the data model.

## 7. SOC 2 Type II

- Not a legal requirement but a de facto sales requirement for mid-market and larger agency customers, and directly relevant to demonstrating the security controls HIPAA also requires.
- Recommended timeline: begin evidence collection and control implementation from Phase 1 launch (the controls — access management, change management, logging — should already exist for HIPAA reasons); pursue formal Type I audit around the Phase 2 launch window and Type II (which requires a review period, typically 6–12 months of control operation) as Phase 3 approaches, aligning certification completion with the point CareOS is asking agencies to trust it with billing/financial data.

## 8. Data portability and retention

- Clinical/care records are often subject to state-specific minimum retention periods (commonly multi-year, varying by state and by whether the client is a minor) — confirm per-state requirements before finalizing any data-deletion/archival policy.
- Agencies must be able to export their data (PRD NFR table) — build export tooling as a first-class feature, not an afterthought, both as a compliance safeguard and a competitive/trust signal against lock-in concerns.

## 9. Compliance ownership and review cadence (recommendation for the team)

| Trigger | Required review |
|---|---|
| Before Phase 1 launch | Healthcare compliance counsel review of EVV/HIPAA implementation; confirm BAAs with all Phase 1 vendors |
| Before Phase 2 launch | Consent-law review of ambient documentation flow, state by state, for each new state of operation |
| Before Phase 3 launch | Certified medical billing/coding consultant review of claims-generation logic; confirm clearinghouse and payer-specific requirements per state and contract |
| Annually | Re-review CMS PPS final rule changes and state EVV vendor changes; re-run AI hiring bias audit |
| Whenever entering a new state | Full re-check of EVV model/vendor, Medicaid program rules, consent law, and wage/hour rules for that state before selling there |
