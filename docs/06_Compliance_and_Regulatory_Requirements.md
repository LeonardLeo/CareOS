# CareOS — Compliance & Regulatory Requirements

**Document owner:** Compliance/Legal advisor (engage one before Phase 1 launch) + Product
**Status:** Foundational constraints. Every requirement below is a hard gate.
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
- **State model variance:** states choose one of several EVV models. A state-mandated vendor or
  aggregator, a state-provided open system, or agencies using their own EVV system feeding a
  state-designated aggregator.
  - **Consequence: the EVV transmission layer is a per-state adapter, not one integration.**
    See `03_Technical_Architecture.md` Section 4 and `07_Integration_Specifications.md`.
  - Aggregators named in the market: Sandata, HHAeXchange, Tellus, plus state-proprietary
    systems. States change vendors periodically. Confirm the current vendor per state before
    building each adapter.
- **Product implication:** US-1.4.3 in the PRD is a compliance requirement, not a
  differentiator. Visits without valid EVV data can bring claim denial or payment recoupment on
  Medicaid-funded services.

## 2. HIPAA (Health Insurance Portability and Accountability Act)

- **Applicability:** CareOS handles PHI from Phase 1: client names and addresses tied to care
  schedules, caregiver health-related credential data. CareOS, or the agencies using it, is
  generally a HIPAA Business Associate or Covered Entity depending on the service arrangement.
  Confirm the classification with counsel.
- **Privacy Rule requirements:** minimum-necessary access to PHI, enforced via RBAC
  (`08_Security_Architecture.md`). Client rights to access and amend records, which the Phase 2
  family portal must support. Restrictions on PHI disclosure, which drive the redaction logic in
  US-2.4.1.
- **Security Rule requirements:** encryption at rest and in transit, access controls and unique user identification, audit controls (the `audit_log` table in the data model), and a documented risk-analysis process.
- **Business Associate Agreements:** required with every subprocessor touching PHI. That
  includes the speech-to-text vendor, background-check vendors (identity data, generally not
  clinical PHI — confirm scope), the cloud infrastructure provider, and any analytics or logging
  vendor that could capture PHI incidentally.
  - **Audit every vendor in `07_Integration_Specifications.md` for BAA availability before
    integrating.**
- **Breach notification:** have an incident-response plan ready before launch (see `08_Security_Architecture.md`), since HIPAA breach notification timelines are short.

## 3. CMS Home Health Prospective Payment System (PPS) and related billing rules

- Home health agencies billing Medicare are subject to the CMS Home Health PPS, which determines payment based on 30-day care periods, patient case-mix (via the OASIS assessment), and specific documentation/coding requirements.
- OASIS (Outcome and Assessment Information Set) collection is a separate clinical-assessment
  requirement for Medicare-certified home health agencies. The Phase 2 care-plan and
  documentation modules accommodate OASIS-relevant capture where the agency serves those
  clients. Full OASIS submission tooling is a Phase 3+ scope decision, to be made explicitly.
- PPS rules and payment rates update through an annual CMS final rule. Payment models and
  documentation requirements shift each year, so **the compliance-rules engine (Epic 2.2) is
  configurable per rule year rather than hardcoded**.

## 4. Medicaid variance by state

- Medicaid is administered at the state level; personal care/home-based service definitions, prior-authorization rules, billing codes, and rate structures vary significantly by state and even by specific Medicaid waiver program within a state.
- **Product implication:** the `payer_service_code_ref` and `authorization` entities in the data model must support per-state, per-payer-contract configuration rather than a single global rule set. Do not assume any billing rule discovered for one state's Medicaid program generalizes to another.

## 5. Employment and fair-hiring law

- The AI-driven applicant ranking feature (PRD Epic 1.2) must not use or proxy for protected-class attributes (race, color, national origin, sex, age, disability, religion, familial status, and additional state-specific protected classes).
- Several states and localities have specific AI-in-hiring disclosure or audit requirements (e.g., requirements to disclose AI use in hiring decisions, or to conduct periodic bias audits of automated employment decision tools). **Confirm current requirements in every state CareOS operates before Epic 1.2.2 ships**, and build the bias-audit process referenced in `03_Technical_Architecture.md` Section 8 as a recurring compliance task, not a one-time check.
- Wage-and-hour compliance: overtime rules, and in some jurisdictions specific home-care worker pay requirements (e.g., travel-time compensation between visits, minimum-wage parity rules for home-care workers) must be reflected in the scheduling and (Phase 3) payroll-integration logic.

## 6. State consent laws for ambient/audio documentation

- Two-party (all-party) consent states require consent from everyone in a recorded
  conversation, not the caregiver alone. This governs US-2.1.1.
  - CareOS captures and logs explicit client and family consent before ambient audio processing
    begins in any two-party state.
  - The default everywhere is explicit consent capture, whatever the state requires. The client
    population is vulnerable and the reputational cost of getting this wrong is high.
- Raw audio retention is minimised by default: transcripts are the durable record. Extended
  retention is an explicit, consented, per-agency configuration. See `ambient_session_metadata`
  in the data model.

## 7. SOC 2 Type II

- Not a legal requirement but a de facto sales requirement for mid-market and larger agency customers, and directly relevant to demonstrating the security controls HIPAA also requires.
- Recommended timeline:
  - Evidence collection and control implementation from Phase 1 launch. The controls — access
    management, change management, logging — already exist for HIPAA reasons.
  - Formal Type I audit around the Phase 2 launch window.
  - Type II as Phase 3 approaches. It requires a review period, typically 6–12 months of control
    operation, so completion lands where CareOS begins asking agencies to trust it with billing
    and financial data.

## 8. Data portability and retention

- Clinical and care records carry state-specific minimum retention periods, commonly
  multi-year, varying by state and by whether the client is a minor. Confirm per-state
  requirements before finalising any deletion or archival policy.
- Agencies must be able to export their data (PRD Section 4). Export tooling is a first-class
  feature: a compliance safeguard, and a trust signal against lock-in concerns.

## 9. Compliance ownership and review cadence (recommendation for the team)

| Trigger | Required review |
|---|---|
| Before Phase 1 launch | Healthcare compliance counsel review of EVV/HIPAA implementation; confirm BAAs with all Phase 1 vendors |
| Before Phase 2 launch | Consent-law review of ambient documentation flow, state by state, for each new state of operation |
| Before Phase 3 launch | Certified medical billing/coding consultant review of claims-generation logic; confirm clearinghouse and payer-specific requirements per state and contract |
| Annually | Re-review CMS PPS final rule changes and state EVV vendor changes; re-run AI hiring bias audit |
| Whenever entering a new state | Full re-check of EVV model/vendor, Medicaid program rules, consent law, and wage/hour rules for that state before selling there |
