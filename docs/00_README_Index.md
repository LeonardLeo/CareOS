# CareOS — Build Documentation Suite

**Contents:** the document set for building CareOS, an AI-native operating system for
home-based care agencies, across all three phases (Workforce Engine → Documentation and
Compliance → Revenue Engine).

**Written for:** a team picking the build up cold. The set records the decisions already made so
they do not have to be re-derived.

**Read first:** `12_Engineering_Handoff_Guide.md`. It explains how the set fits together and
gives a first-week checklist for verifying actual project state against these documents.

## Document map

| # | Document | Covers |
|---|---|---|
| 00 | `00_README_Index.md` | This file |
| 01 | `01_Product_Vision_and_Executive_Summary.md` | Problem, market context, three-phase vision, success metrics |
| 02 | `02_Product_Requirements_Document.md` | Full feature spec: epics, user stories, acceptance criteria, NFRs — all three phases |
| 03 | `03_Technical_Architecture.md` | System architecture, tech stack, service boundaries, AI/ML architecture |
| 04 | `04_Data_Model_and_Schema.md` | Database schema, ERD, all entities including forward-designed Phase 3 tables |
| 05 | `05_API_Specification.md` | REST API endpoints, conventions, webhooks, versioning |
| 06 | `06_Compliance_and_Regulatory_Requirements.md` | EVV, HIPAA, CMS PPS, Medicaid variance, fair-hiring law, consent law, SOC 2 |
| 07 | `07_Integration_Specifications.md` | EVV aggregators, background-check vendors, job boards, STT, EHR import, clearinghouse, payroll |
| 08 | `08_Security_Architecture.md` | IAM, multi-tenant isolation, encryption, audit logging, incident response |
| 09 | `09_UX_Design_and_User_Flows.md` | Personas, design principles, core user flows, key screens |
| 10 | `10_Roadmap_Milestones_Team_Plan.md` | Phase gates, milestone-by-milestone plan, hiring plan, risk register |
| 11 | `11_GTM_and_Pricing_Strategy.md` | ICP, positioning, pricing model, go-to-market motion by stage |
| 12 | `12_Engineering_Handoff_Guide.md` | How to pick this project up cold — read this first |

Build state is tracked separately, in `BUILD_STATUS.md`. The documents above describe the
intended product; that file records what exists.

## Scope covered

The full product arc, not only the MVP:

- **Phase 1 — AI Workforce Engine:** recruiting, credentialing, EVV-compliant scheduling.
- **Phase 2 — Ambient Documentation and Compliance Copilot:** point-of-care documentation,
  compliance flagging, family portal.
- **Phase 3 — Revenue Engine:** eligibility, claims, remittance, denial management, payroll
  integration, multi-agency rollups.

The data model, architecture, and API spec are designed from Phase 1 to accommodate Phase 3, so
later phases extend the system rather than requiring a rebuild. See
`03_Technical_Architecture.md` Section 1 and `04_Data_Model_and_Schema.md` Section 8.

## Caveat

This set is a starting blueprint, based on market research and general domain knowledge about
home-based care operations, EVV, HIPAA, and healthcare billing as of mid-2026.

It does not replace:

- Healthcare-compliance counsel review, required before each phase launch
  (`06_Compliance_and_Regulatory_Requirements.md` Section 9).
- A certified medical billing and coding consultant, required before Phase 3 launch.
- Validation with real agency customers (Stage 0 in `10_Roadmap_Milestones_Team_Plan.md`).

Every assumption here is a hypothesis to test, not a settled fact.

Time-sensitive specifics go stale: regulations, vendor landscapes (EVV aggregators in
particular, which vary by state and change), and competitor positioning. Re-verify them rather
than treating this set as current.
