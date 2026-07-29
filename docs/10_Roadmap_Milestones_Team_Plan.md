# CareOS — Roadmap, Milestones & Team Plan

**Document owner:** Product + Engineering leadership
**Status:** Living plan — update actuals as the build progresses; this is the primary "where are we" reference for a new team
**Audience:** Leadership, incoming team, investors

---

## 1. Phase gates and success thresholds

These are the go/no-go thresholds from the market research and PRD — use them to judge whether to proceed, pause, or pivot at each stage, regardless of which team is executing.

| Stage | Timeframe (from kickoff) | Deliverable | Threshold to proceed to next stage |
|---|---|---|---|
| **Stage 0 — Validate the wedge** | Months 0–3 | 30+ agency owner/COO interviews; design-partner LOIs | 20+ agencies confirm willingness to pay for a workforce-first product; 3+ signed design-partner LOIs |
| **Stage 1 — Ship AI Workforce Engine (Phase 1 MVP)** | Months 3–9 | Recruiting, onboarding, EVV-compliant scheduling live with design partners | Time-to-first-visit ≤ 3 days for design partners; measurable turnover reduction; ~$1M ARR / 20–40 agencies |
| **Stage 2 — Add Documentation + Compliance Copilot (Phase 2)** | Months 9–18 | Ambient documentation, compliance copilot live | Net revenue retention > 110% from documentation upsell; measurable after-hours charting reduction |
| **Stage 3 — Launch Revenue Engine (Phase 3)** | Months 18–30 | Multi-payer claims + denial prevention live | RCM module attach rate > 30% of base; ARPU expansion trend established |

## 2. Detailed milestone breakdown — Phase 1 (Months 0–9)

| Milestone | Target month | Key deliverables |
|---|---|---|
| M0 — Foundation | Month 1 | Tenant/agency data model live (`04_Data_Model_and_Schema.md` Section 3); auth/RBAC; CI/CD pipeline; staging environment |
| M1 — Recruiting alpha | Month 3 | Job posting + applicant pipeline; manual (non-AI) ranking as a placeholder; first design-partner agencies onboarded as tenants |
| M2 — Onboarding & credentialing | Month 5 | Digital onboarding paperwork; background-check vendor integration live (at least one state's exclusion-list check); credentialing dashboard |
| M3 — Scheduling & EVV core | Month 7 | Care plan + visit generation; caregiver mobile clock-in/out; EVV transmission live for at least one state's aggregator |
| M4 — AI ranking + gap-fill | Month 8 | Candidate/shift AI ranking live with explainability; real-time gap alerts and replacement suggestions |
| M5 — Phase 1 GA with design partners | Month 9 | Full Epic 1.1–1.5 feature set live; core reporting dashboard; Stage 1 threshold metrics being tracked |

## 3. Detailed milestone breakdown — Phase 2 (Months 9–18)

| Milestone | Target month | Key deliverables |
|---|---|---|
| M6 — Compliance rules engine generalized | Month 10 | Refactor/extend the Phase 1 EVV-exception rules engine into the general-purpose compliance-rules engine (PRD Section 6 dependency) |
| M7 — Ambient documentation alpha | Month 13 | STT vendor integrated; consent-capture flow; draft visit-note generation; caregiver review/sign flow |
| M8 — Supervisor review + compliance flags | Month 15 | Supervisor co-sign flow; compliance flags surfaced inline; audit-readiness score |
| M9 — Family portal | Month 17 | Read-mostly family portal with redaction logic |
| M10 — Phase 2 GA | Month 18 | Full Epic 2.1–2.4 feature set live; Stage 2 threshold metrics being tracked |

## 4. Detailed milestone breakdown — Phase 3 (Months 18–30)

| Milestone | Target month | Key deliverables |
|---|---|---|
| M11 — Eligibility & authorization | Month 20 | X12 270/271 integration; authorization tracking with exhaustion alerts |
| M12 — Claims generation & scrubbing | Month 23 | X12 837 generation from EVV + documentation data; claim-scrubbing engine reusing compliance-rules infrastructure |
| M13 — Remittance & denial management | Month 26 | X12 835 ingestion; denial queue with AI-suggested corrections |
| M14 — Payroll integration | Month 28 | Hours-to-payroll bridging with overtime/pay-parity handling |
| M15 — Phase 3 GA | Month 30 | Full Epic 3.1–3.6 core feature set live (multi-agency rollups and open API can extend beyond this window as P1/P2 backlog); Stage 3 threshold metrics being tracked |

## 5. Team/hiring plan by phase

| Phase | Recommended roles to have in place | Notes |
|---|---|---|
| Stage 0 / Phase 1 start | Founding PM, 1 design lead, 3–5 backend/full-stack engineers, 1 mobile engineer, 1 AI/ML engineer, 1 healthcare-compliance advisor (fractional/consulting), 1 founding sales/GTM lead | Compliance advisor engagement should start immediately, not after a compliance question arises |
| Phase 1 → Phase 2 transition | Add: 1–2 additional mobile/backend engineers, 1 dedicated QA/compliance-testing engineer, 1 clinical advisor (RN background) to guide documentation/care-plan design, 1 customer success lead for design partners | Clinical advisor input is critical before Epic 2.1/2.3 design finalizes |
| Phase 2 → Phase 3 transition | Add: 1 security lead (dedicated, not fractional, given SOC 2 Type II and billing-data sensitivity), 1–2 backend engineers with EDI/healthcare-billing experience, 1 certified medical billing/coding consultant (fractional), expand sales/GTM team | EDI/X12 experience is a specific, somewhat scarce skill — start this hire early in the transition, not at Phase 3 kickoff |
| Ongoing, all phases | 1 dedicated "EVV integration owner" engineer (per `07_Integration_Specifications.md`), regular (at least annual) compliance counsel review | These are maintenance functions, not one-time project roles |

## 6. Budget/resourcing considerations (high-level; refine with finance)

- **Vendor/integration costs** scale with the number of states served (each new state may mean a new EVV aggregator relationship, and Medicaid program-specific configuration) — factor state-expansion sequencing into the budget, not just headcount.
- **Compliance/legal spend** should be treated as a continuous line item (counsel review at every phase gate, per `06_Compliance_and_Regulatory_Requirements.md` Section 9), not a one-time setup cost.
- **AI/ML inference costs** (hosted LLM API usage for ranking, ambient-doc extraction) scale with visit volume — model this explicitly before Phase 2 GA, since ambient documentation runs on every visit, unlike the lower-volume recruiting-ranking calls in Phase 1.

## 7. Risk register (top-level; see architecture and compliance docs for detail)

| Risk | Phase most exposed | Mitigation reference |
|---|---|---|
| State EVV aggregator fragmentation slows multi-state expansion | Phase 1 | `03_Technical_Architecture.md` Section 8; `07_Integration_Specifications.md` Section 2 |
| AI hiring-ranking bias/legal exposure | Phase 1 | `06_Compliance_and_Regulatory_Requirements.md` Section 5 |
| Ambient documentation consent/liability issues | Phase 2 | `06_Compliance_and_Regulatory_Requirements.md` Section 6 |
| EDI/billing complexity underestimated | Phase 3 | `07_Integration_Specifications.md` Section 7; engage certified billing consultant early |
| A well-funded competitor enters the AI-native home-care workforce space | Any | Revisit GTM sequencing and consider narrowing to a sub-vertical (e.g., hospice or pediatric home health) per the original market-research recommendation |

## 8. How to use this document if you're a new team taking over mid-build

1. Check which milestone (M0–M15) was most recently completed against the actual state of the codebase — do not assume the milestone table reflects reality; verify against `11_Engineering_Handoff_Guide.md`'s repo/status-check guidance.
2. Confirm which Stage threshold metrics are currently being tracked and what the actual numbers are before deciding whether to proceed to the next stage — the thresholds in Section 1 are decision gates, not just historical targets.
3. Re-validate the risk register against current market conditions (a competitor may have entered; regulations may have shifted) before continuing execution unchanged.
