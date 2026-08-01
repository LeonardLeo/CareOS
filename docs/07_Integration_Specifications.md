# CareOS — Integration Specifications

**Document owner:** Engineering
**Status:** Directional — confirm current vendor terms/APIs before contracting; vendor landscape shifts
**Audience:** Engineers building integration adapters, partnerships/procurement

---

## 1. Integration architecture principle

Every external integration sits behind an internal adapter interface for its category: EVV,
background check, job board, clearinghouse, payroll, EHR import.

A vendor's API shape does not reach core domain logic. That constraint is what makes adding a
state's EVV aggregator, or swapping a vendor, a new adapter implementation rather than a change
to core logic. See `03_Technical_Architecture.md` Section 8.

## 2. EVV Aggregators (Phase 1 — critical path)

| Integration point | Detail |
|---|---|
| Purpose | Transmit the six required EVV data elements per visit to the state-designated system |
| Pattern | Per-state adapter implementing a common `EVVTransmissionAdapter` interface: `submit(visit_evv_payload) -> TransmissionResult` |
| Known aggregator/vendor names in the market (confirm current per-state assignment before building) | Sandata, HHAeXchange, Tellus, and various state-proprietary systems |
| Data format | Varies by aggregator — commonly HTTPS API with JSON or a state-specific batch file format; some states still support batch/file-based submission as a fallback |
| Sandbox/testing | Every aggregator integration must be validated against that vendor's test/sandbox environment before any production visit data is transmitted — never test EVV transmission logic against production endpoints |
| Failure handling | Failed transmissions must retry with backoff and surface to the agency admin dashboard (US-1.4.6); a visit is not "compliant" until transmission is acknowledged, not merely submitted |
| Ownership recommendation | Assign one engineer as the "EVV integration owner" who tracks vendor API changes and state reassignments — this is a moving target requiring ongoing maintenance, not a one-time build |

## 3. Background Check & Credentialing Vendors (Phase 1)

| Integration point | Detail |
|---|---|
| Purpose | Criminal background check, sex-offender registry check, OIG/GSA exclusion-list check, license/certification verification |
| Pattern | Common `ScreeningAdapter` interface: `initiate(caregiver_id, check_types[]) -> ScreeningRequestId`, plus a webhook receiver for async results |
| Vendor evaluation criteria | API-first (not just a web portal), documented SLA for turnaround time, BAA availability if any PHI-adjacent data is touched, coverage of all target states |
| Exclusion-list check | This must run against the current OIG List of Excluded Individuals/Entities (LEIE) and the GSA System for Award Management (SAM) exclusion list — required before a caregiver can be scheduled for Medicaid/Medicare-billed visits (hard gate, PRD US-1.3.2) |
| Recurring re-checks | Exclusion status and license expirations are not "check once" — schedule recurring re-verification (e.g., monthly exclusion re-checks are a common industry practice; confirm current best practice with compliance counsel) |

## 4. Job Boards / Recruiting Sources (Phase 1)

| Integration point | Detail |
|---|---|
| Purpose | Syndicate job postings, ingest applicants into a single pipeline |
| Common integration pattern | Job board APIs or feed-based (XML/JSON feed) posting; applicant data typically returned via webhook or polling |
| Vendors to evaluate | Indeed, ZipRecruiter, and home-care-specific job boards/staffing marketplaces |
| Data mapping | Normalize inbound applicant schema (name, contact, resume, claimed certifications) into the internal `applicant_profile` model regardless of source |

## 5. Speech-to-Text / Ambient Documentation Vendor (Phase 2)

| Integration point | Detail |
|---|---|
| Purpose | Convert ambient/dictated audio into transcript for structured extraction |
| Evaluation criteria | Medical/clinical vocabulary accuracy, BAA availability (mandatory — this vendor touches PHI directly), on-device or streaming options for offline-adjacent use cases, data retention controls matching CareOS's configurable retention policy |
| Pattern | `TranscriptionAdapter`: `transcribe(audio_stream_or_file, consent_metadata) -> Transcript`; consent metadata must be validated as present before the adapter is invoked, not just before the UI shows the recording button (defense in depth) |

## 6. Legacy EHR Import (Phase 1, for migration; ongoing as needed)

| Integration point | Detail |
|---|---|
| Purpose | Let a new agency customer migrate existing client, caregiver, and care-plan data from their prior system (Homecare Homebase, WellSky, MatrixCare, Alora, myEZCare, CareSmartz360, ShiftCare, etc.) |
| Pattern | Most legacy systems support CSV/Excel export or, in some cases, a documented API; build a generalized import pipeline with per-vendor field-mapping templates rather than fully custom code per vendor |
| Data quality handling | Expect messy/incomplete legacy data (missing credentials, stale schedules) — the import tool should flag records needing manual review rather than silently accepting bad data into a compliance-sensitive system |

## 7. Claims Clearinghouse & Payers (Phase 3)

| Integration point | Detail |
|---|---|
| Purpose | Submit X12 837 claims, receive X12 835 remittance, run X12 270/271 eligibility checks |
| Pattern | Integrate via a clearinghouse (rather than direct-to-payer for most payers) to normalize the many payer-specific connection requirements; `ClearinghouseAdapter` interface handling the EDI transaction types |
| EDI standard | X12 5010 transaction sets: 837 (claim), 835 (remittance), 270/271 (eligibility inquiry/response), 276/277 (claim status inquiry/response, recommended for the denial-management workflow) |
| Vendor evaluation criteria | Coverage of target-state Medicaid programs and Medicare Advantage plans, existing home-based-care client base (evidence of payer-specific format handling already solved), turnaround SLA |

## 8. Payroll Provider (Phase 3)

| Integration point | Detail |
|---|---|
| Purpose | Push EVV-verified, approved hours into payroll processing with correct overtime and pay-parity handling |
| Pattern | `PayrollAdapter`: `submit_hours(caregiver_id, pay_period, hours_breakdown) -> PayrollSubmissionResult` |
| Build vs. integrate decision | Integrating with an existing payroll provider (rather than building native payroll) is strongly recommended for the initial Phase 3 build — payroll tax compliance is its own deep regulatory domain outside CareOS's core value proposition |

## 9. Integration vendor tracking table (fill in during build)

| Category | Vendor selected | Contract status | BAA on file? | Sandbox validated? | Adapter owner |
|---|---|---|---|---|---|
| EVV (per state) | | | | | |
| Background check | | | | | |
| Job boards | | | | | |
| Speech-to-text | | | | | |
| Clearinghouse | | | | | |
| Payroll | | | | | |

Once vendor selection begins, the project-tracking tool holds the live status. This table is the
starting checklist.
