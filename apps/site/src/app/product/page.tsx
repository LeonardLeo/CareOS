import type { Metadata } from "next";
import Link from "next/link";

import { CoverageBoard } from "@/components/coverage-board";
import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
import { partnerMailto } from "@/content/site";

export const metadata: Metadata = {
  title: "Product",
  description:
    "Recruiting, credentialing, EVV-compliant scheduling, and an offline-first caregiver app — what CareOS does today, and what it deliberately does not do yet.",
};

/**
 * The product page.
 *
 * Organised by the four jobs an agency actually does, not by our module names. An agency
 * owner does not have a "credentialing module" problem; they have a caregiver whose CPR card
 * expired and a visit on Thursday.
 *
 * The closing section says what is not built. A feature list with no edges is one a buyer
 * assumes is padded, and every item on it becomes a support ticket the week after go-live.
 */

const CAPABILITIES = [
  {
    eyebrow: "Hiring",
    title: "From applicant to first visit in under 72 hours",
    body: "Applicants arrive from any board into one pipeline and one shape. Credential checks, exclusion screening, and e-signature run in parallel rather than in sequence, because the sequence is what makes onboarding take three weeks.",
    points: [
      "One normalised pipeline regardless of source",
      "Explainable ranking against the shifts actually open",
      "OIG and GSA exclusion screening, ordered and tracked to a verdict",
      "Recurring re-screening, because clearance is not check-once",
      "Credential expiry surfaced at 60, 30, and 7 days",
    ],
  },
  {
    eyebrow: "Scheduling",
    title: "A board that knows who is allowed to work",
    body: "Assignment is a gate, not a suggestion. A caregiver whose certification lapses before the visit's service date, or whose exclusion check has not cleared, cannot be put on a Medicaid-billed shift — the system refuses rather than warns.",
    points: [
      "Hard gates on exclusion status, credential expiry, and employment state",
      "Gap detection over unfilled visits, most urgent first",
      "Ranked suggestions with the reasoning shown, never a bare number",
      "Drive-time-aware matching, honest about being an estimate",
      "Overtime headroom as a warning, not a block",
    ],
  },
  {
    eyebrow: "In the field",
    title: "A caregiver app that works with no signal",
    body: "The highest-stakes surface in the product. Everything a caregiver needs is one screen, and the clock-in has to work in a basement apartment with no bars — because that is where the work happens.",
    points: [
      "Today's visits, with the address and the authorised tasks",
      "EVV clock-in and clock-out captured on the device",
      "An outbox that replays when the phone finds a network",
      "Never lost, never sent twice",
      "Cached client data wiped the moment access is revoked",
    ],
  },
  {
    eyebrow: "Compliance",
    title: "The state hears about the visit, and you hear about it first",
    body: "EVV transmission, acknowledgement, and reconciliation. A visit is not compliant when it is submitted; it is compliant when it is acknowledged, and the difference is where unbilled revenue hides.",
    points: [
      "Per-state adapters behind one interface",
      "No production transmission until a vendor's sandbox has validated the map",
      "Exponential backoff, then escalation to a human",
      "Nightly reconciliation of delivered visits against acknowledgements",
      "Every divergence lands in the exception queue with a remedy attached",
    ],
  },
];

const NOT_YET = [
  ["Ambient documentation", "Phase 2. The tables exist; the behaviour does not."],
  ["Claims and remittance", "Phase 3. Same — modelled now so today's visits can reach a claim later without a backfill."],
  ["Telephony clock-in", "Accepted by the API and modelled end to end, with no phone system attached yet. For agencies where much of the workforce has no smartphone this is a blocker, and we will say so rather than sell around it."],
  ["A native mobile app", "The caregiver app is an installable web app today. Packaging it natively is a decision waiting on real-device testing, not an oversight."],
  ["Multi-state EVV", "One state first, validated properly. Each additional state is a new adapter and a new sandbox cycle."],
];

export default function ProductPage() {
  return (
    <>
      <PageHero
        eyebrow="Product"
        title="Everything between a job posting and a paid visit."
        lede="Phase 1 is the workforce engine: find people, clear them to work, put them on the right shift, and prove to the state that the visit happened."
      />

      <section className="section section--tight">
        <div className="shell">
          <Reveal>
            <CoverageBoard />
          </Reveal>
        </div>
      </section>

      {CAPABILITIES.map((capability, index) => (
        <section
          key={capability.title}
          className={`section${index % 2 === 1 ? " section--sunken" : ""}`}
        >
          <div className="shell">
            <div className="split">
              <Reveal className="split__aside">
                <p className="eyebrow">{capability.eyebrow}</p>
                <h2 className="display d2" style={{ marginTop: "var(--s4)" }}>
                  {capability.title}
                </h2>
              </Reveal>
              <Reveal delay={80}>
                <p className="lede">{capability.body}</p>
                <ul className="ticks" style={{ marginTop: "var(--s5)", fontSize: "1rem" }}>
                  {capability.points.map((point) => (
                    <li key={point}>
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </Reveal>
            </div>
          </div>
        </section>
      ))}

      <section className="section section--ink">
        <div className="shell">
          <Reveal>
            <p className="eyebrow">What is not built</p>
            <h2 className="display d2" style={{ marginTop: "var(--s4)", maxWidth: "20ch" }}>
              The list with edges on it.
            </h2>
            <p className="lede" style={{ marginTop: "var(--s4)" }}>
              A capability list with no boundary is one a buyer assumes is padded — and every
              item on it becomes a support ticket the week after go-live.
            </p>
          </Reveal>

          <dl className="rows" style={{ marginTop: "var(--s6)", borderTopColor: "currentColor" }}>
            {NOT_YET.map(([term, detail], index) => (
              <Reveal key={term} className="row" delay={index * 55}>
                <dt className="row__term">{term}</dt>
                <dd
                  className="row__detail"
                  style={{ color: "color-mix(in srgb, var(--paper) 72%, transparent)" }}
                >
                  {detail}
                </dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </section>

      <section className="section">
        <div className="shell shell--narrow" style={{ textAlign: "center" }}>
          <Reveal>
            <h2 className="display d2" style={{ marginInline: "auto", maxWidth: "20ch" }}>
              Want it pointed at your agency?
            </h2>
            <p className="lede" style={{ marginInline: "auto", marginTop: "var(--s4)" }}>
              Tell us which state you bill in and what breaks most often. That is enough for a
              first conversation.
            </p>
            <div style={{ marginTop: "var(--s6)" }}>
              <Link className="btn btn--accent" href="/contact/">
                Start a conversation <span className="arrow">→</span>
              </Link>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
