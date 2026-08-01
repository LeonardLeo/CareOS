import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage } from "@/components/legal-page";
import { CONTACT_EMAIL, SECURITY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Acceptable use",
  description:
    "What an agency may and may not do with CareOS, written around the two things that actually cause harm here: falsified visit records and hiring decisions that cannot be defended.",
};

/**
 * The acceptable use policy.
 *
 * Most acceptable-use policies are a list of things nobody was going to do — no spam, no
 * malware — which makes them unread. The two rules that matter in this product are specific to
 * it, so they come first and the generic list is kept short and at the bottom.
 */
export default function AcceptableUsePage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Acceptable use"
      lede="Two of these matter far more than the rest, so they come first. They are the two ways this product could be used to hurt someone."
      updated="31 July 2026"
    >
      <h2>Do not falsify a visit record</h2>
      <p>
        Electronic visit verification is a fraud control. Recording a visit that did not happen,
        clocking in from somewhere other than the client&rsquo;s home while representing
        otherwise, clocking in on another person&rsquo;s behalf, or editing a completed visit to
        make a rejected claim payable is Medicaid fraud, and it is fraud whether the person doing
        it thinks of it that way or not.
      </p>
      <p>
        The product is built to make this hard rather than to catch it afterwards. Clock-in
        captures the method and, where the method supports it, the coordinates. Manual entries
        are marked as manual and carry a reason. Edits do not overwrite — the original stays and
        the change is recorded with who made it. Nightly reconciliation reports any delivered
        visit the state&rsquo;s aggregator never acknowledged.
      </p>
      <p>
        We will not remove those markers, disable that logging, or supply a bulk-edit route
        around it, and asking us to is itself grounds for us to end the relationship. If a record
        is wrong, correct it through the exception queue, where the correction and its reason are
        part of the record.
      </p>

      <h2>Do not use ranking as the reason for a decision</h2>
      <p>
        Applicant ranking is a decision aid. It orders candidates on operational signals —
        availability against your open shifts, credential validity, travel distance, reliability
        history — and it is deliberately blind to protected attributes and their known proxies:
        ZIP code, graduation year, school, salary history, arrest record. Intake has no field for
        demographic data at all.
      </p>
      <p>
        That construction reduces one class of harm. It does not make a score a lawful reason to
        reject someone, and in several jurisdictions an automated employment decision tool
        carries obligations of its own — notice, an annual independent bias audit, published
        results. Those obligations sit with the employer, which is you.
      </p>
      <p>
        So: a human decides, the ordering informs, and the reason recorded for an adverse decision
        must be one a person can defend without reference to a number. Scores stay hidden from
        decision-makers on a new agency&rsquo;s account until a bias audit has run on that
        agency&rsquo;s own outcomes and passed — not because we doubt the scorer, but because
        &ldquo;we did not look at it yet&rdquo; is a stronger position than
        &ldquo;we looked at it and assumed it was fine&rdquo;.
      </p>

      <h2>Everything else</h2>
      <p>Do not use CareOS to:</p>
      <ul>
        <li>
          Store data about people your agency has no care or employment relationship with, or
          keep records past the point your retention obligations end
        </li>
        <li>
          Share a login. Every account belongs to one named person, because an audit trail
          attributing an action to a shared account attributes it to nobody
        </li>
        <li>
          Attempt to reach another agency&rsquo;s data, probe for a way to, or hold onto anything
          you reach by accident — tell us instead, at{" "}
          <a className="textlink" href={`mailto:${SECURITY_EMAIL}`}>
            {SECURITY_EMAIL}
          </a>
        </li>
        <li>
          Circumvent rate limits, run automated load beyond ordinary use, or resell access to the
          API without a written agreement
        </li>
        <li>Upload malware, or content unrelated to care delivery, into client or visit records</li>
        <li>
          Retaliate against a caregiver for reporting a compliance concern through the product
        </li>
      </ul>

      <h2>Security research</h2>
      <p>
        Welcome, and out of scope for the paragraph above. Report in good faith, do not access
        data belonging to an agency that has not authorised you, and give us a reasonable window
        before disclosing. We will not pursue anyone who does that. The terms are on the{" "}
        <Link className="textlink" href="/security/">
          security page
        </Link>
        .
      </p>

      <h2>What we do about a breach of this policy</h2>
      <p>
        In most cases, we call you. Something that looks like a misconfiguration or a
        misunderstanding gets a conversation, not a suspension — the failure mode we want to
        avoid is an agency losing access to its schedule on a Friday afternoon over an
        ambiguity, because the people harmed by that are clients waiting for a caregiver.
      </p>
      <p>
        Where there is an active risk to someone&rsquo;s data or a pattern of falsified records,
        we will suspend the specific access involved and tell you why, in writing, the same day.
        Where we are obliged to report to a regulator or a payer, we will, and we will tell you
        we have.
      </p>
      <p>
        Questions about whether something is allowed are better asked than guessed:{" "}
        <a className="textlink" href={`mailto:${CONTACT_EMAIL}`}>
          {CONTACT_EMAIL}
        </a>
        .
      </p>
    </LegalPage>
  );
}
