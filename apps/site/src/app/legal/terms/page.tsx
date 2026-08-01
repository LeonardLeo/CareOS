import type { Metadata } from "next";

import { LegalPage } from "@/components/legal-page";
import { CONTACT_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Terms",
  description:
    "Terms for this website. The product itself is governed by a signed agreement, not by a page you scrolled past.",
};

export default function TermsPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Terms of use"
      lede="These cover the website. The product is governed by a signed agreement — not by a page nobody read."
      updated="31 July 2026"
    >
      <h2>What this covers</h2>
      <p>
        These terms apply to this website. They do not govern use of the CareOS application.
        Access to the product is under a written master services agreement and a business
        associate agreement executed with each agency, and nothing on this page varies either
        of those. Where this page and a signed agreement disagree, the signed agreement wins.
      </p>

      <h2>The content here</h2>
      <p>
        Everything on this site describes a product under active development. Capabilities
        described as built are built; capabilities described as not yet built are not, and we
        have tried hard to keep that distinction visible rather than aspirational. Even so,
        nothing here is a warranty, a commitment to a delivery date, or an offer.
      </p>
      <p>
        The statistics cited carry their source. They come from third-party research we did
        not conduct, and we present them as reported rather than as our own findings.
      </p>

      <h2>Acceptable use</h2>
      <p>Please do not:</p>
      <ul>
        <li>Attempt to gain unauthorised access to any system reachable from this site</li>
        <li>Scrape it in a way that degrades it for anyone else</li>
        <li>Misrepresent an association with CareOS that does not exist</li>
      </ul>
      <p>
        Security research is welcome and is covered by the disclosure commitment on our{" "}
        <a className="textlink" href="/security/">
          security page
        </a>
        .
      </p>

      <h2>Intellectual property</h2>
      <p>
        The name, the mark, the design of this site, and its text are ours. Quoting a
        reasonable extract with attribution is fine and needs no permission.
      </p>

      <h2>Liability</h2>
      <p>
        This site is provided as it is. To the extent the law allows, we are not liable for
        loss arising from reliance on information published here. Nothing in this paragraph
        limits liability that cannot lawfully be limited, and nothing here limits the
        obligations we take on in a signed agreement with an agency.
      </p>

      <h2>Questions</h2>
      <p>
        Write to{" "}
        <a className="textlink" href={`mailto:${CONTACT_EMAIL}`}>
          {CONTACT_EMAIL}
        </a>
        . A person will answer.
      </p>
    </LegalPage>
  );
}
