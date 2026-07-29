# CareOS — Engineering Handoff & Continuity Guide

**Document owner:** Engineering leadership
**Status:** Foundational — this is the document a brand-new team reads first to get productive fast
**Audience:** Any engineer or engineering leader picking up the CareOS build, whether continuing an existing team or starting fresh

---

## 1. Purpose of this document

The explicit goal behind this entire document set is that **if the build stops today and a different team picks it up tomorrow, they can get oriented and keep building without re-deriving decisions from scratch.** This guide is the entry point for that continuity: it explains how the other 11 documents fit together, what a new team should check first, and how to keep the project handoff-ready going forward (in case it needs to change hands again).

## 2. Reading order for a new team

1. `01_Product_Vision_and_Executive_Summary.md` — what we're building and why, in full (not just the current phase).
2. `02_Product_Requirements_Document.md` — the complete feature scope across all three phases.
3. `03_Technical_Architecture.md` and `04_Data_Model_and_Schema.md` — how the system is built, including forward-looking Phase 3 structure already in the schema.
4. `06_Compliance_and_Regulatory_Requirements.md` — the constraints that override normal engineering trade-off decisions. Read this before touching EVV, documentation, or billing code.
5. `10_Roadmap_Milestones_Team_Plan.md` — where the project is supposed to be, milestone by milestone; compare against reality (Section 4 below).
6. The remaining documents (`05`, `07`, `08`, `09`, `11`) as needed by role.

## 3. First-week checklist for an incoming team

1. **Assess actual state vs. documented state.** Compare the current codebase and infrastructure against `10_Roadmap_Milestones_Team_Plan.md`'s milestone table. Do not assume any milestone marked as a target has actually been completed — verify:
   - Which modules from `03_Technical_Architecture.md` Section 4 exist and are functioning.
   - Which tables from `04_Data_Model_and_Schema.md` exist in the actual database, and whether migrations match the documented schema.
   - Which API endpoints from `05_API_Specification.md` are implemented vs. still planned.
   - Which integrations from `07_Integration_Specifications.md` have signed vendor contracts, working sandbox connections, or live production connections (check the vendor-tracking table in that document — it should have been kept current; if not, treat it as unreliable and re-verify directly).
2. **Verify compliance status, not just code status.** Confirm with the outgoing team or available records: has healthcare-compliance counsel reviewed the current implementation? Are BAAs actually signed with every vendor touching PHI? Has an AI hiring bias audit been run if Epic 1.2.2 is live? Treat any "we think so" answer as "no" until confirmed in writing.
3. **Run the full automated test suite**, including the multi-tenant isolation tests referenced in `03_Technical_Architecture.md` Section 8 and `08_Security_Architecture.md` Section 2 — these are the tests most likely to have been skipped under time pressure, and the ones most costly to have skipped.
4. **Identify undocumented decisions.** Any place where the actual code diverges from this document set represents either (a) a deliberate, undocumented decision that should now be written down, or (b) drift that should be reconciled. Update this document set as you find these — see Section 5.

## 4. Repository and environment conventions (recommended if not already established)

- **Repo structure:** a monorepo containing the modular-monolith backend (organized by domain module per `03_Technical_Architecture.md` Section 4), the mobile app, the web admin app, and the family portal, with shared libraries (design system, API client types) in a `packages/` or `libs/` directory — this keeps the "modular monolith first" architecture principle visible in the folder structure itself, not just in theory.
- **Environments:** local (Docker Compose), staging (sandboxed external integrations only — never production EVV/clearinghouse endpoints), production. See `03_Technical_Architecture.md` Section 7.
- **CI required checks:** lint, type-check, unit tests, multi-tenant isolation tests, dependency/security scan, migration-safety check (no destructive migration without two-person sign-off, given compliance sensitivity of the data).
- **Environment variables / secrets:** managed via a dedicated secrets manager, never committed to source control (see `08_Security_Architecture.md` Section 5).
- **Documentation-as-code:** keep this document set in the same repository (e.g., a `/docs` directory) so it version-controls alongside the code it describes, rather than living in a separate, easily-forgotten tool.

## 5. Keeping this document set current (so the NEXT handoff, if any, is just as smooth)

This is the most important habit for whichever team is executing: **treat drift between these documents and reality as a bug.** Specifically:
- When a phase's scope changes (a feature is cut, added, or reprioritized), update `02_Product_Requirements_Document.md` and `10_Roadmap_Milestones_Team_Plan.md` in the same work cycle — not "later."
- When an architectural decision changes (e.g., extracting a service from the modular monolith, switching an AI/ML vendor), update `03_Technical_Architecture.md` and the relevant integration entry in `07_Integration_Specifications.md`.
- When a new state is entered, update the EVV/compliance status in `06_Compliance_and_Regulatory_Requirements.md` and the vendor-tracking table in `07_Integration_Specifications.md` — these are exactly the details a future incoming team will need and will not be able to reconstruct from code alone.
- When a compliance review happens (per the cadence in `06_Compliance_and_Regulatory_Requirements.md` Section 9), log the outcome and date somewhere durable (this document set, or a linked compliance log) — "we did a review once" is not useful to a future team without knowing when and what was reviewed.

## 6. What "done" looks like for the full product (not just MVP)

The build is feature-complete against this document set when:
- All P0 user stories across Epics 1.1–1.5, 2.1–2.4, and 3.1–3.6 in `02_Product_Requirements_Document.md` are implemented and tested.
- All NFRs in `02_Product_Requirements_Document.md` Section 4 are met and verified (not just assumed).
- SOC 2 Type II is complete (per `08_Security_Architecture.md` Section 9).
- All integrations in `07_Integration_Specifications.md` have moved from sandbox to production status for at least the initially targeted states.
- The Stage 3 threshold metrics in `10_Roadmap_Milestones_Team_Plan.md` are being met in production, not just projected.

Reaching this state does not mean the roadmap stops — Epic 3.5 (multi-agency/franchise rollups) and 3.6 (open API/ecosystem) are explicitly P1/P2 and can extend beyond the Stage 3 window as the next planning cycle's scope, using the same document-update discipline described above.

## 7. Document index

| # | Document | Primary audience |
|---|---|---|
| 01 | Product Vision and Executive Summary | Everyone |
| 02 | Product Requirements Document | Product, engineering, design, QA |
| 03 | Technical Architecture | Engineering |
| 04 | Data Model and Schema | Engineering |
| 05 | API Specification | Engineering |
| 06 | Compliance and Regulatory Requirements | Everyone, especially compliance/legal and engineering |
| 07 | Integration Specifications | Engineering, partnerships/procurement |
| 08 | Security Architecture | Engineering, security/compliance reviewers |
| 09 | UX Design and User Flows | Design, frontend/mobile engineering |
| 10 | Roadmap, Milestones and Team Plan | Leadership, incoming team, investors |
| 11 | GTM and Pricing Strategy | Sales, marketing, leadership |
| 12 | This document — Engineering Handoff Guide | Any incoming engineering team or leader |
