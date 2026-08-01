import Link from "next/link";

import { CoverageBoard } from "@/components/coverage-board";
import { Figures } from "@/components/figures";
import { Reveal } from "@/components/reveal";
import { SIGN_IN_URL, partnerMailto } from "@/content/site";

/**
 * The page people are sent to before they have an account.
 *
 * It opens on the customer's problem rather than on our software, because an agency owner
 * arriving here has an unfilled shift on Thursday and no idea what an "AI-native workforce
 * layer" is. The product only earns a mention once the page has said something true about
 * their week.
 *
 * What it deliberately does not claim: nothing about customers, results, or scale. There are
 * none. A pre-launch landing page that invents social proof is the first thing a design
 * partner catches, and that credibility does not come back.
 */

const PHASES = [
  {
    tag: "Phase 1 — building now",
    now: true,
    title: "AI Workforce Engine",
    body: "Solve the staffing crisis first. Every other problem an agency has is downstream of a shift nobody is covering.",
    items: [
      "Applicant sourcing, screening, and explainable ranking",
      "Sub-72-hour onboarding with parallel credential verification",
      "EVV-compliant, drive-time-aware scheduling",
      "Real-time gap detection and assisted gap filling",
      "Offline-first caregiver app with EVV clock-in and clock-out",
    ],
  },
  {
    tag: "Phase 2",
    now: false,
    title: "Ambient documentation",
    body: "End after-hours charting, and catch a documentation gap before it becomes a denial.",
    items: [
      "Voice and ambient point-of-care notes, reviewed and signed",
      "Structured extraction into care-plan and billing fields",
      "Compliance copilot for survey readiness and PPS-rule risk",
      "Family and client portal",
    ],
  },
  {
    tag: "Phase 3",
    now: false,
    title: "Revenue engine",
    body: "Become the system of record for cash, not only for care.",
    items: [
      "EVV-verified visits into claims across Medicaid, MA, and private pay",
      "Eligibility checks, claim scrubbing, denial prevention",
      "Remittance, AR aging, payer-mix analytics",
      "Payroll integration and multi-location rollups",
    ],
  },
];

const DAY = [
  {
    term: "6:04am — a caregiver calls out",
    detail:
      "The shift starts at eight. Today that means a coordinator working the phones from memory. In CareOS it is a ranked list of who can actually take it — cleared to work, credentials current, close enough to arrive, not already on another visit.",
  },
  {
    term: "8:12am — a clock-in with no signal",
    detail:
      "The caregiver is in a basement apartment with no bars. The clock-in is recorded on the device and sent when the phone finds a network. Nothing is lost, and nothing is transmitted twice.",
  },
  {
    term: "2:30pm — a certification lapses next week",
    detail:
      "Nobody has to notice. The assignment gate checks credentials against the visit's service date, so a caregiver whose certification expires before a shift three weeks out cannot be scheduled for it.",
  },
  {
    term: "Overnight — the state gets the visit",
    detail:
      "EVV transmission, acknowledgement, and reconciliation. A visit that was delivered but never acknowledged surfaces as a compliance exception the next morning rather than as a denied claim in ninety days.",
  },
];

export default function Home() {
  return (
    <>
      <section className="hero ruled">
        <div className="shell">
          <Reveal>
            <p className="hero__mark eyebrow">
              <span className="hero__pip" aria-hidden="true" />
              Home care · Home health · Hospice
            </p>
            <h1 className="display d1">
              The shift you cannot fill is revenue you have <em>already lost</em>.
            </h1>
            <p className="lede" style={{ marginTop: "var(--s5)" }}>
              Agencies turn down work every week for want of a caregiver, while the software
              they run on was built to document care after the fact. CareOS is the layer that
              fills the shift — recruiting, credentialing, and EVV-compliant scheduling in one
              system.
            </p>
            <div className="hero__actions">
              <a className="btn btn--accent" href={partnerMailto()}>
                Become a design partner <span className="arrow">→</span>
              </a>
              <Link className="btn btn--ghost" href="/product/">
                See what we build
              </Link>
            </div>
            <p className="hero__note">
              In active development. We are looking for a small number of agencies to build
              with, not to sell to.
            </p>
          </Reveal>

          <Reveal delay={140} className="stack-5" >
            <div style={{ marginTop: "var(--s7)" }}>
              <CoverageBoard />
            </div>
          </Reveal>
        </div>
      </section>

      <section className="section section--sunken" id="problem">
        <div className="shell">
          <div className="split">
            <Reveal className="split__aside">
              <p className="eyebrow">The problem, in numbers</p>
              <h2 className="display d2" style={{ marginTop: "var(--s4)" }}>
                Agencies are not short of demand.
              </h2>
              <p className="lede" style={{ marginTop: "var(--s4)" }}>
                Ten thousand Americans turn 65 every day and three quarters of adults over 50
                want to age at home. The constraint is not the market. It is that the average
                agency cannot hire and onboard fast enough to say yes.
              </p>
            </Reveal>
            <div>
              <Figures />
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <Reveal>
            <p className="eyebrow">A day, as it actually goes</p>
            <h2 className="display d2" style={{ marginTop: "var(--s4)", maxWidth: "20ch" }}>
              Four moments where the software either helps or does not.
            </h2>
          </Reveal>

          <div className="rows" style={{ marginTop: "var(--s6)" }}>
            {DAY.map((item, index) => (
              <Reveal key={item.term} className="row" delay={index * 60}>
                <dt className="row__term">{item.term}</dt>
                <dd className="row__detail">{item.detail}</dd>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--ink">
        <div className="shell">
          <Reveal>
            <p className="eyebrow">What we build</p>
            <h2 className="display d2" style={{ marginTop: "var(--s4)", maxWidth: "20ch" }}>
              Three layers on one data model.
            </h2>
            <p className="lede" style={{ marginTop: "var(--s4)" }}>
              Each phase is useful alone, and each is designed so the next extends the system
              rather than replacing it. The billing tables exist today, unused, so that a visit
              recorded this year can be traced onto a claim next year without a migration.
            </p>
          </Reveal>

          <div className="cards" style={{ marginTop: "var(--s6)" }}>
            {PHASES.map((phase, index) => (
              <Reveal
                key={phase.title}
                className={`card${phase.now ? " card--now" : ""}`}
                delay={index * 80}
              >
                <span className={`tag${phase.now ? " tag--now" : ""}`}>{phase.tag}</span>
                <h3 className="display d3">{phase.title}</h3>
                <p style={{ color: "var(--ink-2)", fontSize: "0.97rem" }}>{phase.body}</p>
                <ul className="ticks">
                  {phase.items.map((item) => (
                    <li key={item}>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <div className="split">
            <Reveal className="split__aside">
              <p className="eyebrow">How it is built</p>
              <blockquote className="pull" style={{ marginTop: "var(--s4)" }}>
                &ldquo;Multi-tenancy, EVV, and auditability are not features you add once you
                have customers.&rdquo;
              </blockquote>
              <p className="prose" style={{ marginTop: "var(--s5)" }}>
                <span>
                  Each is a decision that reaches every table in the schema, and each is
                  cheaper now than it will ever be again.
                </span>
              </p>
              <p style={{ marginTop: "var(--s5)" }}>
                <Link className="textlink" href="/security/">
                  Read the security page <span className="arrow">→</span>
                </Link>
              </p>
            </Reveal>

            <div className="steps">
              {[
                {
                  title: "Tenant isolation in the database",
                  body: "Every table carries FORCE ROW LEVEL SECURITY and the application connects as a role with no BYPASSRLS. One agency cannot read another's data even if a query forgets to filter — the database refuses, rather than the code remembering.",
                },
                {
                  title: "EVV built in, not bolted on",
                  body: "The six federally required elements are modelled as required fields, so an incomplete visit fails in our code rather than as a state rejection weeks later. No adapter transmits production data until it has been validated against that vendor's sandbox.",
                },
                {
                  title: "Hiring AI you can audit",
                  body: "Ranking runs on a closed allowlist of operational signals. Protected attributes and their known proxies — ZIP code, graduation year, school, salary history — are refused by the scorer itself, and scores stay hidden from decision-makers until a bias audit has run on real outcomes.",
                },
                {
                  title: "Offline is the normal case",
                  body: "Caregivers work in homes with no signal. Clock-in and clock-out queue on the device and sync when the phone finds a network, so a visit is never lost and never transmitted twice.",
                },
              ].map((step, index) => (
                <Reveal key={step.title} className="step" delay={index * 70}>
                  <div>
                    <h3 className="d3 display" style={{ fontSize: "1.16rem" }}>
                      {step.title}
                    </h3>
                    <p style={{ marginTop: "var(--s2)", color: "var(--ink-2)" }}>{step.body}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="section section--sunken">
        <div className="shell shell--narrow" style={{ textAlign: "center" }}>
          <Reveal>
            <h2 className="display d2" style={{ marginInline: "auto", maxWidth: "18ch" }}>
              We are looking for a few agencies to build with.
            </h2>
            <p className="lede" style={{ marginInline: "auto", marginTop: "var(--s4)" }}>
              Not a pilot programme and not a waiting list. A small number of operators willing
              to tell us what is actually broken, in exchange for shaping what gets built.
            </p>
            <div
              style={{
                display: "flex",
                gap: "var(--s3)",
                justifyContent: "center",
                flexWrap: "wrap",
                marginTop: "var(--s6)",
              }}
            >
              <Link className="btn btn--accent" href="/contact/">
                Talk to us <span className="arrow">→</span>
              </Link>
              <a className="btn btn--ghost" href={SIGN_IN_URL}>
                Sign in
              </a>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
