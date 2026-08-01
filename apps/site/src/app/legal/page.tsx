import type { Metadata } from "next";
import Link from "next/link";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
import { CONTACT_EMAIL, LEGAL_PAGES } from "@/content/site";

export const metadata: Metadata = {
  title: "Policies",
  description:
    "Privacy, terms, cookies, HIPAA, acceptable use, availability, subprocessors, and accessibility — every policy in one place.",
};

/**
 * The policy index.
 *
 * Exists so the footer can carry three links instead of eight. A footer listing every policy
 * buries the ones people actually look for, and a compliance officer sent here would rather
 * see the whole set at once anyway.
 */
export default function LegalIndexPage() {
  return (
    <>
      <PageHero
        eyebrow="Legal"
        title="Every policy, in one place."
        lede="Written to be read. Where a commitment does not exist yet, the page says so rather than implying one."
      />

      <section className="section section--tight">
        <div className="shell">
          <dl className="rows">
            {LEGAL_PAGES.map((page, index) => (
              <Reveal key={page.href} className="row" delay={index * 40}>
                <dt className="row__term">
                  <Link className="textlink" href={page.href}>
                    {page.title} <span className="arrow">→</span>
                  </Link>
                </dt>
                <dd className="row__detail">{page.summary}</dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </section>

      <section className="section section--sunken">
        <div className="shell">
          <Reveal className="column prose stack-4">
            <p className="eyebrow">Something missing?</p>
            <h2 className="display d3" style={{ marginTop: "var(--s3)" }}>
              Ask for it.
            </h2>
            <p>
              If your compliance review needs a document that is not here — a completed
              security questionnaire, a signed business associate agreement, a data-flow
              diagram — write to{" "}
              <a className="textlink" href={`mailto:${CONTACT_EMAIL}`}>
                {CONTACT_EMAIL}
              </a>{" "}
              and we will send it or tell you plainly that it does not exist yet.
            </p>
          </Reveal>
        </div>
      </section>
    </>
  );
}
