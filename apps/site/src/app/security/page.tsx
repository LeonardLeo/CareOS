import type { Metadata } from "next";
import Link from "next/link";

import { PageHero } from "@/components/page-hero";
import { Reveal } from "@/components/reveal";
import { SECURITY_EMAIL } from "@/content/site";

export const metadata: Metadata = {
  title: "Security & compliance",
  description:
    "How CareOS handles PHI: tenant isolation enforced by Postgres, encryption at rest and in transit, audit logging in the same transaction as the change, and what we have not done yet.",
};

/**
 * The security page.
 *
 * For a product touching PHI this is a sales page, not a legal footnote — the person
 * evaluating it is often the same owner who signed the last HIPAA settlement they read about.
 * So it describes mechanisms rather than adjectives: "enterprise-grade" tells them nothing,
 * "the application role has no BYPASSRLS" tells them exactly what would have to go wrong.
 *
 * It ends with what is *not* done. A security page with no open items is one nobody believes,
 * and the items here are the same ones tracked in the repository's own build status.
 */

const CONTROLS = [
  {
    term: "Tenant isolation, enforced by the database",
    detail: (
      <>
        Every tenant table carries <code>FORCE ROW LEVEL SECURITY</code>, and the application
        connects as a role with no <code>BYPASSRLS</code>. The tenant is set per transaction
        from the token and from nowhere else — no request field can influence it. A query that
        forgets its filter returns nothing rather than another agency&rsquo;s clients.
      </>
    ),
  },
  {
    term: "Encryption at rest and in transit",
    detail: (
      <>
        TLS 1.2 or better at the edge, and the database refuses unencrypted connections at the
        server rather than trusting every client to ask. Disks and backups are encrypted with a
        customer-managed key. Direct identifiers — date of birth, tax ID, addresses, the MFA
        secret — are additionally encrypted at the application layer, so a database file on its
        own does not read as plaintext.
      </>
    ),
  },
  {
    term: "Least privilege, including our own",
    detail: (
      <>
        Six roles, each scoped to what that job needs. A caregiver reaches only visits assigned
        to them. A scheduler can see whether someone is assignable and cannot open their
        background-check results. The containers running the product hold no credential that
        can read a secret; the secrets are injected by the platform, not fetched by the code.
      </>
    ),
  },
  {
    term: "An audit trail that cannot be separated from the change",
    detail: (
      <>
        Reading a client record, opening a schedule, exporting an agency&rsquo;s data, cutting
        off a user&rsquo;s access — each writes an audit row in the same transaction as the
        thing it describes. A trail that can be rolled back independently of the event is not
        a trail.
      </>
    ),
  },
  {
    term: "Multi-factor authentication where it matters",
    detail: (
      <>
        Required for owner/admin, clinical supervisor, and billing — the roles that can read
        every client record in the tenant and export the lot. Enforcement is a boot gate:
        production refuses to start without it, because a requirement that can be left off by
        omission is a recommendation.
      </>
    ),
  },
  {
    term: "Offboarding that actually removes access",
    detail: (
      <>
        Ending a caregiver&rsquo;s access revokes every live session immediately rather than
        waiting for a token to expire, and the caregiver app wipes its cached client data the
        first time the server refuses it. Disabling an account is a separate act from ending
        sessions, and both are recorded with a reason.
      </>
    ),
  },
  {
    term: "Fair hiring, enforced by the scorer",
    detail: (
      <>
        Ranking reads a closed allowlist of operational signals. Protected attributes and their
        known proxies — ZIP code, graduation year, school, salary history, arrest record — are
        refused by the scoring function itself, so no caller can route around it. Applicant
        intake has no field for demographic data at all. Scores stay hidden from decision-makers
        until a bias audit has run on that agency&rsquo;s own outcomes.
      </>
    ),
  },
  {
    term: "EVV that fails in our code, not at the state",
    detail: (
      <>
        The six federally required data elements are modelled as required fields, so an
        incomplete visit is refused here rather than rejected weeks later. No adapter may
        transmit production data until it has been validated against that vendor&rsquo;s
        sandbox, and a nightly reconciliation reports any delivered visit the aggregator has
        not acknowledged.
      </>
    ),
  },
];

const OPEN = [
  [
    "Managed identity provider",
    "Sign-in runs on a local password path today. Federated identity is the intended destination and the seam for it is already in the schema.",
  ],
  [
    "SOC 2",
    "Not started, and we will not imply otherwise. The controls a Type II attests to are being built first, which is the order that makes the audit meaningful.",
  ],
  [
    "Penetration test",
    "Not yet commissioned. Scheduled ahead of a first production agency, not after.",
  ],
  [
    "Subprocessor BAAs",
    "None are needed yet because no PHI-touching vendor is integrated. That changes the moment the first EVV aggregator is connected, and the countersigned agreement comes first.",
  ],
];

export default function SecurityPage() {
  return (
    <>
      <PageHero
        eyebrow="Security & compliance"
        title="What would have to go wrong."
        lede="Every claim below is a mechanism you could check, not an adjective. Where something is not done, it says so."
      />

      <section className="section section--tight">
        <div className="shell">
          <dl className="rows">
            {CONTROLS.map((control, index) => (
              <Reveal key={control.term} className="row" delay={index * 45}>
                <dt className="row__term">{control.term}</dt>
                <dd className="row__detail">{control.detail}</dd>
              </Reveal>
            ))}
          </dl>
        </div>
      </section>

      <section className="section section--sunken">
        <div className="shell">
          <div className="split">
            <Reveal className="split__aside">
              <p className="eyebrow">Not done yet</p>
              <h2 className="display d2" style={{ marginTop: "var(--s4)" }}>
                The open items.
              </h2>
              <p className="lede" style={{ marginTop: "var(--s4)" }}>
                A security page with nothing outstanding is one nobody believes. These are the
                same items tracked in the repository&rsquo;s own build status.
              </p>
            </Reveal>
            <dl className="rows" style={{ borderTop: "1px solid var(--rule)" }}>
              {OPEN.map(([term, detail], index) => (
                <Reveal key={term} className="row" delay={index * 55}>
                  <dt className="row__term">{term}</dt>
                  <dd className="row__detail">{detail}</dd>
                </Reveal>
              ))}
            </dl>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell shell--narrow">
          <Reveal>
            <p className="eyebrow">Reporting something</p>
            <h2 className="display d2" style={{ marginTop: "var(--s4)" }}>
              Found a problem? Tell us before you tell anyone else.
            </h2>
            <div className="prose stack-4" style={{ marginTop: "var(--s5)" }}>
              <p>
                Write to{" "}
                <a className="textlink" href={`mailto:${SECURITY_EMAIL}`}>
                  {SECURITY_EMAIL}
                </a>
                . We will acknowledge within two business days and tell you what we intend to
                do and when.
              </p>
              <p>
                We will not threaten legal action against anyone who reports a vulnerability in
                good faith, does not access data belonging to another agency, and gives us a
                reasonable window before disclosing.
              </p>
            </div>
            <p style={{ marginTop: "var(--s5)" }}>
              <Link className="textlink" href="/legal/subprocessors/">
                See the subprocessor list <span className="arrow">→</span>
              </Link>
            </p>
          </Reveal>
        </div>
      </section>
    </>
  );
}
