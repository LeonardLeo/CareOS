# CareOS — Build Documentation Suite

**Purpose:** this is the complete document set for building CareOS, an AI-native operating system for home-based care agencies, from initial validation through the full three-phase product (Workforce Engine → Documentation/Compliance → Revenue Engine). It is written so that **if the build stops and a new team picks it up at any point, they can get oriented and continue without re-deriving decisions from scratch.**

**Start here if you're new:** read `12_Engineering_Handoff_Guide.md` first — it explains how to use this whole set and gives a first-week checklist for verifying actual project state against these documents.

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

## Scope covered

This set intentionally documents **the full product arc, not just the MVP**:
- **Phase 1 — AI Workforce Engine:** recruiting, credentialing, EVV-compliant scheduling.
- **Phase 2 — Ambient Documentation + Compliance Copilot:** point-of-care documentation, compliance flagging, family portal.
- **Phase 3 — Revenue Engine:** eligibility, claims, remittance, denial management, payroll integration, multi-agency rollups.

The data model, architecture, and API spec are deliberately designed from Phase 1 to accommodate Phase 3 (see `03_Technical_Architecture.md` Section 1 and `04_Data_Model_and_Schema.md` Section 8) so later phases extend the system rather than requiring a rebuild.

## Important caveat

This document set is a comprehensive starting blueprint based on market research and general domain knowledge about home-based care operations, EVV, HIPAA, and healthcare billing as of mid-2026. It is **not a substitute for**:
- Qualified healthcare-compliance counsel review (required before each phase launch — see `06_Compliance_and_Regulatory_Requirements.md` Section 9).
- A certified medical billing/coding consultant review before Phase 3 launch.
- Direct validation with real agency customers (Stage 0 in `10_Roadmap_Milestones_Team_Plan.md`) — treat every assumption in this set as a hypothesis to validate, not a settled fact.

Regulations, vendor landscapes (especially EVV aggregators, which change by state), and competitive dynamics will move over time. Whoever is building should re-verify time-sensitive specifics (vendor names, exact regulatory text, current competitor positioning) rather than treating this document set as permanently current.
