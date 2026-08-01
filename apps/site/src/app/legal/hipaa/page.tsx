import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage } from "@/components/legal-page";
import { SECURITY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "HIPAA and business associate agreements",
  description:
    "Where CareOS sits in the HIPAA relationship, what we sign before receiving protected health information, and what we will not do with it.",
};

/**
 * The HIPAA page.
 *
 * The one page an agency owner's compliance reviewer opens first, so it answers the two
 * questions they actually have — who is the covered entity, and what does the vendor sign —
 * before anything else. It also states the parts that are not done, because a HIPAA page
 * claiming a finished posture at this stage would be the least believable page on the site.
 */
export default function HipaaPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="HIPAA and business associate agreements"
      lede="Where we sit in the relationship, what we sign before receiving protected health information, and the parts of this posture that are not finished."
      updated="31 July 2026"
    >
      <h2>Who is who</h2>
      <p>
        A home care agency using CareOS is the <strong>covered entity</strong>. We are its{" "}
        <strong>business associate</strong>. That is not a formality: it means the agency holds
        the direct obligations to its clients, and it means we may only use protected health
        information to perform the services the agency has asked for, on its instruction, under
        a written agreement.
      </p>
      <p>
        Clients and caregivers are the people the data is about. If you are one of them, your
        rights run against the agency, and the agency is the right first stop — see{" "}
        <Link className="textlink" href="/legal/privacy/">
          the privacy notice
        </Link>{" "}
        for what to do if that route does not work.
      </p>

      <h2>The agreement comes first</h2>
      <p>
        We execute a business associate agreement with an agency before that agency&rsquo;s
        protected health information reaches our systems — not after the integration works, and
        not as a document to be tidied up before go-live. The same rule runs downstream: any
        vendor of ours that could touch PHI signs one before the first byte, and each is named
        on the{" "}
        <Link className="textlink" href="/legal/subprocessors/">
          subprocessor page
        </Link>
        .
      </p>
      <p>
        We will sign an agency&rsquo;s own paper. If you have a template your counsel prefers,
        send it; we would rather negotiate a redline than ask a small agency to fund a review of
        ours.
      </p>

      <h2>What we commit to</h2>
      <ul>
        <li>
          <strong>Use limited to the service.</strong> We do not use one agency&rsquo;s data to
          improve another agency&rsquo;s experience, we do not sell it, and we do not train
          models on protected health information.
        </li>
        <li>
          <strong>Minimum necessary, enforced structurally.</strong> Access is scoped by role
          rather than by policy alone. A scheduler can see whether a caregiver is assignable and
          cannot open their background-check results, because the endpoint refuses rather than
          because a document asks them not to.
        </li>
        <li>
          <strong>Separation between agencies, enforced by the database.</strong> Row-level
          security is forced on every tenant table and the application role cannot bypass it.
          The consequence worth knowing is that a query which forgets its filter returns nothing
          rather than someone else&rsquo;s clients.
        </li>
        <li>
          <strong>An audit trail written in the same transaction as the change.</strong> Reads
          of a client record included. A trail that can be rolled back independently of the
          event it describes is not a trail.
        </li>
        <li>
          <strong>Breach notification without waiting out the clock.</strong> The rule allows a
          business associate up to 60 days. We commit to telling an affected agency within 72
          hours of concluding that its data was involved, with what we know at that point rather
          than a finished narrative, and to keep telling them as the picture changes.
        </li>
        <li>
          <strong>Return or destruction at the end.</strong> An agency can export everything it
          holds at any time, without asking us and without a fee, so leaving never depends on our
          cooperation.
        </li>
      </ul>

      <h2>What is not finished</h2>
      <p>
        Stating this plainly is the point of the page. As of the date above:
      </p>
      <ul>
        <li>
          <strong>No healthcare-compliance counsel review has been performed.</strong> It is
          required before a first production agency and it is not something engineering can
          substitute for.
        </li>
        <li>
          <strong>No incident-response plan is written.</strong> The breach-notification
          commitment above is a commitment we intend to keep, and the runbook that makes keeping
          it reliable does not exist yet.
        </li>
        <li>
          <strong>No penetration test has been commissioned</strong>, and{" "}
          <strong>SOC 2 has not been started.</strong> We are building the controls an audit
          would attest to before commissioning the audit, which is the order that makes it mean
          something.
        </li>
        <li>
          <strong>No subprocessor business associate agreements are in place</strong> — because
          no PHI-touching vendor is integrated yet. That changes the moment the first electronic
          visit verification aggregator is connected.
        </li>
      </ul>
      <p>
        None of the above is a reason to hand us protected health information today. It is the
        list we expect to be held to before you do.
      </p>

      <h2>Asking for the detail</h2>
      <p>
        Security questionnaires, the draft agreement, a data-flow diagram, or the underlying
        subprocessor contracts:{" "}
        <a className="textlink" href={`mailto:${SECURITY_EMAIL}`}>
          {SECURITY_EMAIL}
        </a>
        . The{" "}
        <Link className="textlink" href="/security/">
          security page
        </Link>{" "}
        describes the mechanisms behind the commitments above.
      </p>
    </LegalPage>
  );
}
