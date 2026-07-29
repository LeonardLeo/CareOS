# CareOS — Go-to-Market & Pricing Strategy

**Document owner:** GTM/Sales leadership
**Status:** Directional — refine with real design-partner feedback starting Stage 0
**Audience:** Sales, marketing, leadership

---

## 1. Ideal customer profile (ICP)

- **Primary:** independent and regional home-based care agencies (home care, home health, hospice), roughly $2M–$50M annual revenue.
- **Signals of fit:** currently on a legacy EHR-style platform (Homecare Homebase, WellSky, MatrixCare, Alora, myEZCare, CareSmartz360, ShiftCare) or spreadsheets; visibly struggling with caregiver turnover/fill rate (e.g., actively recruiting, turning down cases); operating in one or more states with EVV enforcement already active.
- **Buyer:** owner/administrator or COO. **Champion:** scheduling coordinator or staffing manager (feels the pain daily; PRD's highest-frequency user).
- **Secondary (later expansion):** franchise/regional multi-location operators — valuable but requires the multi-agency rollup features (Phase 3, Epic 3.5) to be genuinely ready.

## 2. Positioning

**Category:** not "another EHR" — CareOS positions as the AI-native workforce and operations platform for home-based care, complementary to (or eventually replacing) legacy systems of record.

**Core message:** "Your business isn't limited by demand — it's limited by staffing. CareOS fixes the staffing problem first, then the documentation and billing problems that come from having a fully staffed, well-run agency."

**Differentiation vs. legacy incumbents:** legacy systems were built around the EHR/clinical record; CareOS is built around the workforce, with AI-native recruiting, matching, and gap-filling as the wedge — a genuinely different starting point, not a feature-parity play.

## 3. Pricing model

Follow the "services-as-software" outcome-aligned pricing pattern referenced in the original market research, rather than a pure per-seat license — this prices against the value agencies actually feel (turnover cost, lost revenue from turned-down cases) rather than software-budget comparisons.

| Phase | Pricing unit | Rationale |
|---|---|---|
| Phase 1 (Workforce Engine) | Per caregiver hired/retained (e.g., a base platform fee + a per-active-caregiver component, with retention-linked pricing elements under exploration) | Ties price directly to the ~$2,600-per-replacement cost the agency is trying to avoid |
| Phase 2 (Documentation + Compliance) | Per scheduled visit, layered onto the Phase 1 base | Ties price to volume of the workflow being automated |
| Phase 3 (Revenue Engine) | Per clean claim / percentage-of-collections component, or hybrid | Mirrors outcome-based pricing patterns seen in adjacent AI-native categories (e.g., per-resolution pricing in customer support AI); aligns CareOS's incentive with the agency actually getting paid |

**Recommendation:** finalize exact pricing mechanics with the first 3–5 design partners (Stage 0/1) rather than fixing pricing before any customer conversation — the specific per-unit rate should come out of willingness-to-pay discovery, not be assumed from this document.

## 4. Go-to-market motion by stage

### Stage 0 — Design partner acquisition (Months 0–3)
- Direct outreach to agency owners via industry associations, home-care conferences/trade shows, and warm referrals.
- Offer meaningfully discounted or free early access in exchange for deep product feedback and case-study rights — the goal is validated learning and reference customers, not revenue, at this stage.
- Target: 3–5 signed design-partner LOIs (ties to Stage 0 threshold in the roadmap).

### Stage 1 — Phase 1 launch and initial scaling (Months 3–9)
- **Primary channel:** direct sales to independent/regional agencies, supported by the design-partner case studies from Stage 0.
- **Secondary channel:** presence at home-care industry trade shows and conferences (the offline-buyer pattern that worked for comparable vertical-AI companies in adjacent trades categories).
- **Sales cycle expectation:** healthcare-adjacent B2B sales cycles are typically longer than generic SMB SaaS — plan for multi-month cycles involving both the owner/admin buyer and the scheduler champion.
- Target: ~$1M ARR / 20–40 agencies (Stage 1 threshold).

### Stage 2 — Phase 2 expansion (Months 9–18)
- **Primary motion:** upsell existing Phase 1 customers into documentation/compliance features — this is a warm, low-CAC expansion motion, not new-logo acquisition.
- Begin building category authority (content, case studies on turnover reduction and compliance outcomes) to support new-logo acquisition in parallel.

### Stage 3 — Phase 3 expansion and franchise/regional push (Months 18–30)
- **Primary motion:** upsell existing base into the Revenue Engine (highest-ARPU expansion point).
- **New motion:** begin targeting regional/franchise operators directly, now that multi-agency rollup features exist.
- Consider a dedicated enterprise/franchise sales function separate from the core SMB/mid-market motion at this stage.

## 5. Marketing and category-building

- **Content strategy:** lead with the turnover/staffing crisis data (this document's numbers are drawn from the original market research — see the vision document) rather than generic "AI for healthcare" messaging; agencies respond to their specific, felt pain.
- **Trust signals:** SOC 2 progress (per `08_Security_Architecture.md` timeline), HIPAA compliance posture, and state-specific EVV certification/compliance should be prominently featured in sales collateral as they come online — this is a compliance-anxious buyer category.
- **Proof points:** prioritize quantified case studies (time-to-first-visit reduction, turnover reduction, fill-rate improvement) from design partners over generic testimonials.

## 6. Competitive positioning notes

- Do not position directly against legacy incumbents as "cheaper" — position as "a different layer" (workforce-first, AI-native) that can coexist with or eventually replace their system of record. Agencies are often contractually or operationally locked into an existing EHR-style system; a coexistence/migration story reduces switching friction.
- Watch for new entrants (per the roadmap's risk register) — if a well-funded competitor enters the same wedge, consider narrowing initial GTM focus to a defensible sub-vertical (e.g., hospice-specific or pediatric home health workforce needs) rather than competing head-on for the broadest possible ICP.

## 7. Metrics to track from day one

- CAC and sales-cycle length by segment (independent vs. regional agency).
- Net revenue retention, broken out by phase-driven upsell (Phase 1 → 2 → 3 expansion) vs. new-logo growth — this validates the "compounding platform" thesis behind the three-phase roadmap.
- Time-to-value for new customers (time from signed contract to first measurable fill-rate/turnover improvement) — this is both a product-quality and a sales-reference metric.
