# CareOS — UX Design Guidelines & Core User Flows

**Document owner:** Design
**Status:** Foundational — principles apply across all phases; flows expand as phases ship
**Audience:** Designers, frontend/mobile engineers, product

---

## 1. Personas

| Persona | Primary surface | Key characteristics |
|---|---|---|
| **Agency Owner/Admin** | Web admin app | Runs the business; cares about fill rate, turnover, compliance exposure, and (Phase 3) cash. Time-poor; wants dashboards, not data entry. |
| **Scheduler/Coordinator** | Web admin app (scheduling board) | Highest-frequency power user in Phase 1; juggling live shift gaps under time pressure. Needs speed and clarity over aesthetics. |
| **Clinical Supervisor (RN)** | Web admin app + mobile review | Reviews/signs documentation (Phase 2), builds care plans; needs efficient review workflows, not just data entry. |
| **Caregiver** | Mobile app | Highest-volume user by headcount; wide range of tech familiarity, sometimes limited English proficiency, frequently in low-connectivity environments (clients' homes). This persona's experience quality directly drives retention — the core business problem CareOS exists to solve. |
| **Billing/RCM staff** | Web admin app (Phase 3) | Detail-oriented, exception-driven work (denial management); needs strong filtering/search and clear claim-status visibility. |
| **Client/Family member** | Family portal (Phase 2+) | Occasional, anxious user checking on a loved one's care; needs reassurance and clarity, not operational complexity. |

## 2. Design principles

1. **Caregiver-app-first mindset.** Every design decision for the mobile app should be stress-tested against: "does this work one-handed, outdoors, with spotty signal, for someone who may not be a confident smartphone user?" This is the highest-stakes surface in the product.
2. **Offline is not an edge case.** Design explicit UI states for "offline — will sync" rather than pretending connectivity is always present (see `03_Technical_Architecture.md`, Section 1, principle 4).
3. **Exceptions over data entry.** For power users (schedulers, billing staff), default views should surface what needs attention (open shifts, compliance flags, denied claims) rather than requiring them to hunt through complete lists.
4. **Explainable AI, always visible.** Any AI-generated suggestion (candidate ranking, caregiver-shift match, compliance flag) shows its reasoning inline, never as an unexplained score (ties to PRD US-1.2.2 and the bias-audit requirement).
5. **Human sign-off is a visible, unskippable step, not a formality.** Ambient documentation and AI-generated content always show a clear, distinct review-and-sign UI state — never auto-finalize.
6. **Accessibility and multilingual support are baseline, not a later localization pass.** Minimum English + Spanish at MVP for the caregiver app; design components with localization in mind (no hardcoded string concatenation, text expansion allowances in layout).

## 3. Core user flows

### Flow A — Scheduler fills an open shift (Phase 1, highest-frequency flow)
1. Scheduler sees a gap alert (caregiver called out, or a new client visit is unassigned).
2. Scheduler opens the visit; sees AI-ranked suggested caregivers with visible reasoning (certification match, drive time, availability).
3. Scheduler taps to offer the shift to the top suggestion (or broadcasts to multiple qualified caregivers).
4. Caregiver receives a push notification; accepts or declines from the mobile app in one tap.
5. Scheduler sees the shift move from "open" to "assigned" in real time on the scheduling board.

### Flow B — Caregiver completes a visit (Phase 1 → Phase 2 expansion)
1. Caregiver opens the app, sees today's schedule, taps into the next visit.
2. Caregiver clocks in (GPS-based; falls back to telephony/manual-exception flow if no signal — this fallback must be just as usable, not a degraded afterthought).
3. (Phase 2) Caregiver completes documentation via ambient/voice capture or a simplified checklist, reviews the AI-drafted note, edits if needed, and signs.
4. Caregiver clocks out; if offline, sees a clear "will sync when connected" state rather than an error.

### Flow C — New hire onboarding (Phase 1)
1. Applicant applies via a job posting; sees clear, mobile-friendly application flow.
2. Once hired, new caregiver receives a milestone checklist (paperwork → background check → credentials → first shift) with progress visibility — reduces anxiety and agency follow-up burden.
3. Agency admin sees the same pipeline from their side, with automated nudges rather than manual chasing.

### Flow D — Supervisor reviews documentation (Phase 2)
1. Supervisor sees a queue of visit notes needing review, prioritized by compliance-flag severity.
2. Supervisor opens a flagged note, sees the specific flag (e.g., "vitals field missing," "narrative doesn't match logged tasks") inline next to the relevant content.
3. Supervisor approves, requests caregiver correction, or edits directly (with a clear audit trail of the change).

### Flow E — Billing staff manages a denial (Phase 3)
1. Denied claim appears in the denial queue with AI-suggested root cause and correction path.
2. Billing staff reviews the suggestion against the underlying visit/EVV/documentation data (linked directly, not requiring a manual cross-reference).
3. Billing staff corrects and resubmits, or escalates if the denial requires an authorization change.

### Flow F — Family member checks on care (Phase 2+)
1. Family member logs into the portal, sees upcoming/confirmed visits and assigned caregiver.
2. Family member sees an appropriately summarized (not raw clinical narrative) update after a visit, with an option to message the care team.

## 4. Key screens inventory (for design/eng sprint planning)

**Caregiver mobile app:** Login/onboarding checklist → Today's schedule → Visit detail/clock-in → Documentation capture → Visit history/pay visibility → Shift marketplace (pick up open shifts) → Messages.

**Agency admin web app:** Dashboard (fill rate, turnover, compliance score) → Scheduling board → Applicant pipeline → Credentialing dashboard → Client/care-plan management → (Phase 2) Documentation review queue → (Phase 2) Compliance rules config → (Phase 3) Claims dashboard → (Phase 3) Denial queue → (Phase 3) AR aging/payer-mix reports.

**Family portal (Phase 2+):** Upcoming visits → Care summary view → Messaging.

## 5. Handoff note for the incoming design team

If picking this up mid-build, prioritize a design-system pass (shared components, typography, color, spacing tokens) before adding new screens if one doesn't already exist — the number of distinct surfaces (mobile app, admin web app, family portal) makes an inconsistent, un-systemized UI expensive to unwind later. See `frontend-design` guidance in the engineering skill set for implementation-level design-token conventions if building in React.
