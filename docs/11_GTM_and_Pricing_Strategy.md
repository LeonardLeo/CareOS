# CareOS — Go-to-Market & Pricing Strategy

**Document owner:** GTM/Sales leadership
**Status:** Directional — refine with real design-partner feedback starting Stage 0
**Audience:** Sales, marketing, leadership

---

## 1. Ideal customer profile (ICP)

- **Primary:** independent and regional home-based care agencies (home care, home health, hospice), roughly $2M–$50M annual revenue.
- **Signals of fit:** currently on a legacy EHR-style platform (Homecare Homebase, WellSky, MatrixCare, Alora, myEZCare, CareSmartz360, ShiftCare) or spreadsheets; visibly struggling with caregiver turnover/fill rate (e.g., actively recruiting, turning down cases); operating in one or more states with EVV enforcement already active.
- **Buyer:** owner/administrator or COO. **Champion:** scheduling coordinator or staffing manager (feels the pain daily; PRD's highest-frequency user).
- **Secondary, later expansion:** franchise and regional multi-location operators. Valuable, and gated on the multi-agency rollup features in Phase 3, Epic 3.5 being ready.

## 2. Positioning

**Category:** the AI-native workforce and operations platform for home-based care. Not another EHR. It complements a legacy system of record, and can eventually replace one.

**Core message:** "Your business isn't limited by demand. It's limited by staffing. CareOS fixes staffing first, then the documentation and billing problems that come with a fully staffed agency."

**Differentiation vs. legacy incumbents:** legacy systems are built around the clinical record. CareOS is built around the workforce, with AI-native recruiting, matching, and gap-filling as the wedge. A different starting point, not a feature-parity play.

## 3. Pricing model

Outcome-aligned "services-as-software" pricing, from the original market research, rather than a per-seat license. It prices against costs agencies feel directly: turnover, and revenue lost to turned-down cases. A per-seat license invites a software-budget comparison instead.

| Phase | Pricing unit | Rationale |
|---|---|---|
| Phase 1 (Workforce Engine) | Per caregiver hired/retained (e.g., a base platform fee + a per-active-caregiver component, with retention-linked pricing elements under exploration) | Ties price directly to the ~$2,600-per-replacement cost the agency is trying to avoid |
| Phase 2 (Documentation + Compliance) | Per scheduled visit, layered onto the Phase 1 base | Ties price to volume of the workflow being automated |
| Phase 3 (Revenue Engine) | Per clean claim / percentage-of-collections component, or hybrid | Mirrors outcome-based pricing patterns seen in adjacent AI-native categories (e.g., per-resolution pricing in customer support AI); aligns CareOS's incentive with the agency actually getting paid |

**Recommendation:** set exact pricing mechanics with the first three to five design partners, in Stage 0 or 1. The per-unit rate comes out of willingness-to-pay discovery. Do not take it from this document.

## 4. Go-to-market motion by stage

### Stage 0 — Design partner acquisition (Months 0–3)
- Direct outreach to agency owners via industry associations, home-care conferences/trade shows, and warm referrals.
- Offer discounted or free early access in exchange for deep product feedback and case-study rights. The goal at this stage is validated learning and reference customers, not revenue.
- Target: 3–5 signed design-partner LOIs (ties to Stage 0 threshold in the roadmap).

### Stage 1 — Phase 1 launch and initial scaling (Months 3–9)
- **Primary channel:** direct sales to independent/regional agencies, supported by the design-partner case studies from Stage 0.
- **Secondary channel:** presence at home-care industry trade shows and conferences (the offline-buyer pattern that worked for comparable vertical-AI companies in adjacent trades categories).
- **Sales cycle expectation:** longer than generic SMB SaaS. Plan for multi-month cycles involving both the owner/admin buyer and the scheduler champion.
- Target: ~$1M ARR / 20–40 agencies (Stage 1 threshold).

### Stage 2 — Phase 2 expansion (Months 9–18)
- **Primary motion:** upsell existing Phase 1 customers into documentation and compliance features. A warm, low-CAC expansion motion rather than new-logo acquisition.
- Begin building category authority (content, case studies on turnover reduction and compliance outcomes) to support new-logo acquisition in parallel.

### Stage 3 — Phase 3 expansion and franchise/regional push (Months 18–30)
- **Primary motion:** upsell existing base into the Revenue Engine (highest-ARPU expansion point).
- **New motion:** begin targeting regional/franchise operators directly, now that multi-agency rollup features exist.
- Consider a dedicated enterprise/franchise sales function separate from the core SMB/mid-market motion at this stage.

## 5. Marketing and category-building

- **Content strategy:** lead with the turnover and staffing data rather than generic "AI for healthcare" messaging. Agencies respond to pain they feel specifically. The numbers are in `01_Product_Vision_and_Executive_Summary.md` Section 2.
- **Trust signals:** SOC 2 progress (`08_Security_Architecture.md` Section 9), HIPAA posture, and state-specific EVV certification belong in sales collateral as they come online. This buyer is compliance-anxious.
- **Proof points:** prioritize quantified case studies (time-to-first-visit reduction, turnover reduction, fill-rate improvement) from design partners over generic testimonials.

## 6. Competitive positioning notes

- Do not position against legacy incumbents as "cheaper". Position as a different layer: workforce-first and AI-native, able to coexist with their system of record or eventually replace it. Agencies are often contractually or operationally locked into an existing EHR-style system, and a coexistence story reduces switching friction.
- Watch for new entrants, per the roadmap's risk register. If a well-funded competitor enters the same wedge, narrow GTM focus to a defensible sub-vertical such as hospice-specific or pediatric home health workforce needs, rather than competing head-on for the broadest ICP.

## 7. Metrics to track from day one

- CAC and sales-cycle length by segment (independent vs. regional agency).
- Net revenue retention, split between phase-driven upsell (Phase 1 → 2 → 3) and new-logo growth. This is the test of the compounding-platform thesis behind the three-phase roadmap.
- Time-to-value: signed contract to first measurable fill-rate or turnover improvement. Both a product-quality metric and a sales-reference one.
