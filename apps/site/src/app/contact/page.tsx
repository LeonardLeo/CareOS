import type { Metadata } from "next";

import { ContactForm } from "@/components/contact-form";
import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
import { CONTACT_EMAIL, PRIVACY_EMAIL, SECURITY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Talk to us about becoming a design partner, a security review, or working here. One inbox, answered by the people building it.",
};

const ROUTES = [
  {
    term: "Design partners and product",
    detail: CONTACT_EMAIL,
    note: "Answered by whoever is building the thing you are asking about. Usually within a day.",
  },
  {
    term: "Security and vulnerability reports",
    detail: SECURITY_EMAIL,
    note: "Acknowledged within two business days, with what we intend to do and when.",
  },
  {
    term: "Privacy and data requests",
    detail: PRIVACY_EMAIL,
    note: "Including access, correction, and deletion requests under state privacy law.",
  },
];

export default function ContactPage() {
  return (
    <>
      <PageHero
        eyebrow="Contact"
        title="One inbox, answered by the people building it."
        lede="No sales team, no qualification call, no demo request that turns into three emails. Tell us what breaks and we will tell you whether we can help yet."
      />

      <section className="section section--tight">
        <div className="shell">
          <div className="split">
            <Reveal className="split__aside">
              <h2 className="display d3">Where to write</h2>
              <dl className="rows" style={{ marginTop: "var(--s4)" }}>
                {ROUTES.map((route) => (
                  <div
                    key={route.term}
                    style={{
                      paddingBlock: "var(--s4)",
                      borderBottom: "1px solid var(--rule)",
                    }}
                  >
                    <dt className="row__term" style={{ fontSize: "0.95rem" }}>
                      {route.term}
                    </dt>
                    <dd style={{ marginTop: "var(--s2)" }}>
                      <a className="textlink" href={`mailto:${route.detail}`}>
                        {route.detail}
                      </a>
                      <p className="field__hint" style={{ marginTop: "var(--s2)" }}>
                        {route.note}
                      </p>
                    </dd>
                  </div>
                ))}
              </dl>
            </Reveal>

            <Reveal delay={80}>
              <h2 className="display d3" style={{ marginBottom: "var(--s5)" }}>
                Or start here
              </h2>
              <ContactForm />
            </Reveal>
          </div>
        </div>
      </section>

      <section className="section section--sunken">
        <div className="shell">
          <Reveal className="column prose stack-4">
            <p className="eyebrow">What happens next</p>
            <h2 className="display d3" style={{ marginTop: "var(--s3)" }}>
              Honestly, it depends on your state.
            </h2>
            <p>
              Our first EVV integration is New York. If you bill Medicaid somewhere else, we
              would still like to talk — but we will tell you plainly that your state is a new
              adapter and a new vendor sandbox cycle, not a configuration change.
            </p>
            <p>
              If you are private-pay only, EVV does not apply to you and we can move faster.
            </p>
            <p>
              Either way you will hear back from an engineer, and the first question will be
              what your Thursday looks like when someone calls out.
            </p>
          </Reveal>
        </div>
      </section>
    </>
  );
}
