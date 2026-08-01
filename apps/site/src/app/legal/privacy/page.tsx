import type { Metadata } from "next";

import { LegalPage } from "@/components/legal-page";
import { PRIVACY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What this website collects, what the CareOS product holds on an agency's behalf, and the difference between the two.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Privacy"
      lede="This page covers two different things, and conflating them is how privacy notices become useless."
      updated="31 July 2026"
    >
      <h2>Two separate systems</h2>
      <p>
        <strong>This website</strong> is a set of static files. <strong>The CareOS product</strong>{" "}
        is the application an agency signs into, and it holds protected health information on
        that agency&rsquo;s behalf. The two are operated differently and this notice treats
        them separately.
      </p>

      <h2>What this website collects</h2>
      <p>
        Nothing. There is no analytics script, no advertising pixel, no session cookie, no
        embedded video, and no font or icon loaded from another company&rsquo;s server. Every
        file this page needs comes from our own origin, which means no third party learns that
        you visited.
      </p>
      <p>
        Our host records ordinary server logs — an IP address, a timestamp, the page requested
        — for security and troubleshooting. We do not join those to anything else, and we do
        not use them to build a profile of you.
      </p>
      <p>
        The contact form does not submit to us. It composes a message and hands it to your own
        mail client, so nothing you type reaches a server until you choose to press send in
        your own email application.
      </p>

      <h2>What the product holds</h2>
      <p>
        When an agency uses CareOS, we are a business associate under HIPAA and the agency is
        the covered entity. Their data is theirs. We process it to provide the service and for
        nothing else — specifically, we do not use one agency&rsquo;s data to improve a product
        experience for another, and we do not train models on protected health information.
      </p>
      <p>The product holds, on the agency&rsquo;s instruction:</p>
      <ul>
        <li>Client names, addresses, dates of birth, care plans, and visit records</li>
        <li>Caregiver identity, credentials, employment status, and screening outcomes</li>
        <li>Electronic visit verification data, including clock-in and clock-out locations</li>
        <li>An audit log of who read or changed what, and when</li>
      </ul>
      <p>
        Applicant records deliberately have no field for date of birth, address, or any
        demographic attribute. The safest way to keep protected characteristics out of a
        hiring model is not to collect them into the hiring record.
      </p>

      <h2>Retention</h2>
      <p>
        Health and billing records are retained for the period the agency&rsquo;s state and
        payer contracts require, which is commonly six years and sometimes longer. Audit logs
        are retained for at least as long as the records they describe. An agency can export
        everything it holds at any time, and can ask for deletion at the end of the
        relationship subject to the retention obligations above.
      </p>

      <h2>Subprocessors</h2>
      <p>
        Any company that could touch protected health information is listed on our{" "}
        <a className="textlink" href="/legal/subprocessors/">
          subprocessor page
        </a>{" "}
        with what it does and where. We sign a business associate agreement before any such
        company receives data, not after.
      </p>

      <h2>Your rights</h2>
      <p>
        If you are a client or caregiver of an agency using CareOS, your relationship is with
        that agency and they are the right people to ask first — they can act on your record
        directly. If they need us, we will help them. If you would rather come to us, write to{" "}
        <a className="textlink" href={`mailto:${PRIVACY_EMAIL}`}>
          {PRIVACY_EMAIL}
        </a>{" "}
        and we will route it and tell you we have.
      </p>

      <h2>Changes</h2>
      <p>
        If this notice changes in a way that affects what we do with data, we will tell
        affected agencies directly rather than relying on the date at the top of this page
        having moved.
      </p>
    </LegalPage>
  );
}
