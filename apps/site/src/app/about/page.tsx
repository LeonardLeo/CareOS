import type { Metadata } from "next";
import Link from "next/link";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";

export const metadata: Metadata = {
  title: "About",
  description:
    "Why CareOS starts with staffing rather than documentation, what we believe about building software for home care, and where we actually are.",
};

/**
 * About.
 *
 * Not a story about founders — there is nothing to say there yet that a reader would benefit
 * from. It is about the decisions, because the decisions are the only thing a pre-launch
 * company can honestly show, and they are what a design partner is really assessing.
 */

const BELIEFS = [
  {
    title: "Start where the money leaks",
    body: "Documentation is the loudest complaint in home care and staffing is the expensive one. An agency that cannot fill Thursday's shift loses that revenue permanently, turns down the next case, and eventually loses the client. We build for the shift first and the paperwork second.",
  },
  {
    title: "The caregiver app is the product",
    body: "The admin console is where the agency works. The caregiver app is where the care happens, and it is used by someone standing in a doorway on a five-year-old phone with one bar. If it does not work there it does not work, and everything upstream of it is theatre.",
  },
  {
    title: "Compliance is a feature, not a tax",
    body: "EVV, exclusion screening, and fair-hiring law are the reasons this market is hard to enter and the reasons it is worth entering. Building them properly is slower at the start and is what a thin AI wrapper cannot copy.",
  },
  {
    title: "Say what is not built",
    body: "Every roadmap on a competitor's site is written in the present tense. Ours is not, because a design partner who discovers the gap after signing tells other agency owners, and in a market this small that is the only marketing that matters.",
  },
  {
    title: "AI that shows its working",
    body: "Ranking a person for a job is a decision with legal weight. Every score carries the factors behind it, protected attributes are refused by the scorer rather than by policy, and the output stays hidden until a bias audit has run on real outcomes. A model nobody can audit is one nobody should deploy against hiring.",
  },
];

const STATE = [
  ["Built and verified", "Recruiting and ranking, credentialing, EVV-compliant scheduling, the offline caregiver app, background screening, outbound webhooks, the admin console, and the background worker that drives all of it."],
  ["Under way", "Deployment to a real environment, the first state EVV integration through a vendor sandbox, and compliance counsel review."],
  ["Not started", "Ambient documentation, claims and remittance, telephony clock-in, and a managed identity provider."],
  ["Customers", "None yet. That is the point of this page."],
];

export default function AboutPage() {
  return (
    <>
      <PageHero
        eyebrow="About"
        title="A company with no customers, being honest about it."
        lede="There is not much of a story yet. What there is instead is a set of decisions, and those are what a first agency should be judging."
      />

      <section className="section section--tight">
        <div className="shell">
          <Reveal className="column prose stack-4">
            <p>
              Home-based care is one of the few industries where demand is guaranteed for the
              next thirty years and supply is the entire constraint. Ten thousand Americans
              turn 65 every day. Three quarters of adults over 50 say they want to age at
              home. And in 2023, nearly two thirds of agencies turned down cases they could
              not staff.
            </p>
            <p>
              The software those agencies run on was built to be a system of record. It
              documents what already happened. It is very good at storing a visit and close to
              useless at the ninety minutes between a 6am call-out and a client expecting
              somebody at eight.
            </p>
            <p>
              <strong>CareOS is built for those ninety minutes.</strong> Everything else — the
              documentation layer, the billing layer — is designed to follow from the same data
              model, so an agency does not have to migrate twice.
            </p>
          </Reveal>
        </div>
      </section>

      <section className="section section--ink">
        <div className="shell">
          <Reveal>
            <p className="eyebrow">What we believe</p>
            <h2 className="display d2" style={{ marginTop: "var(--s4)", maxWidth: "18ch" }}>
              Five decisions, and why.
            </h2>
          </Reveal>

          <div className="steps" style={{ marginTop: "var(--s7)" }}>
            {BELIEFS.map((belief, index) => (
              <Reveal key={belief.title} className="step" delay={index * 60}>
                <div>
                  <h3 className="display" style={{ fontSize: "1.3rem" }}>
                    {belief.title}
                  </h3>
                  <p
                    style={{
                      marginTop: "var(--s2)",
                      color: "color-mix(in srgb, var(--paper) 72%, transparent)",
                      maxWidth: "var(--measure)",
                    }}
                  >
                    {belief.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <div className="split">
            <Reveal className="split__aside">
              <p className="eyebrow">Where we actually are</p>
              <h2 className="display d2" style={{ marginTop: "var(--s4)" }}>
                No adjectives.
              </h2>
              <p className="lede" style={{ marginTop: "var(--s4)" }}>
                The same four categories the engineering team tracks internally, in the same
                words.
              </p>
            </Reveal>
            <dl className="rows" style={{ borderTop: "1px solid var(--rule)" }}>
              {STATE.map(([term, detail], index) => (
                <Reveal key={term} className="row" delay={index * 55}>
                  <dt className="row__term">{term}</dt>
                  <dd className="row__detail">{detail}</dd>
                </Reveal>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section className="section section--sunken">
        <div className="shell shell--narrow" style={{ textAlign: "center" }}>
          <Reveal>
            <h2 className="display d2" style={{ marginInline: "auto", maxWidth: "20ch" }}>
              If that sounds like a company you want to build with, say so.
            </h2>
            <div style={{ marginTop: "var(--s6)" }}>
              <Link className="btn btn--accent" href="/contact/">
                Get in touch <span className="arrow">→</span>
              </Link>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
